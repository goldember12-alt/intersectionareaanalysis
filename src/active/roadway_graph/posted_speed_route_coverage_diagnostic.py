from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely import wkt

from .crs_utils import WORKING_CRS_AUTHORITY, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/posted_speed_route_coverage_diagnostic")

SPEED_FILE = Path("artifacts/normalized/speed.parquet")
USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
USABLE_SEGMENTS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_segments.csv"
SOURCE_BIN_GEOMETRY_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv"
ROLE_ENRICHED_SEGMENTS_FILE = OUTPUT_ROOT / "tables/current/signal_oriented_roadway_segments_role_enriched.csv"
V2_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v2_base_geometry"
V2_BIN_CONTEXT_FILE = V2_DIR / "directional_bin_speed_context_v2.csv"
V2_MATCH_CANDIDATES_FILE = V2_DIR / "speed_bin_match_candidates_v2.csv"
V2_AMBIGUOUS_FILE = V2_DIR / "speed_bin_ambiguous_matches_v2.csv"
V2_SUMMARY_FILE = V2_DIR / "speed_context_v2_summary.csv"
COVERAGE_DIAGNOSTIC_DIR = OUTPUT_ROOT / "review/current/speed_context_coverage_diagnostic"
COVERAGE_SUMMARY_FILE = COVERAGE_DIAGNOSTIC_DIR / "speed_context_coverage_diagnostic_summary.csv"
STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_schema.csv"
STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_field_role_candidates.csv"
STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_crs_sanity.csv"

FEET_TO_METERS = 0.3048
CAR_SPEED_FIELD = "CAR_SPEED_LIMIT"
TRUCK_SPEED_FIELD = "TRUCK_SPEED_LIMIT"
STABLE_ROUTE_FIELDS = [
    "route_name",
    "route_common",
    "route_id",
    "event_source",
    "road_component_id",
    "RTE_TYPE_N",
    "rte_type_name",
    "RTE_CATEGO",
    "rte_category",
    "RTE_RAMP_C",
    "rte_ramp_code",
    "facility_code",
    "facility_text",
    "roadway_role_class",
]
SPEED_ROUTE_FIELDS = [
    "ROUTE_COMMON_NAME",
    "RTE_TYPE_CD",
    "RTE_TYPE_NM",
    "LOC_COMP_DIRECTIONALITY_NAME",
    "ROUTE_FROM_MEASURE",
    "ROUTE_TO_MEASURE",
    "EVENT_SOURCE_ID",
    "EVENT_LOCATION_ID",
    "EVENT_COMPONENT_ID",
    "FROM_JURISDICTION",
    "TO_JURISDICTION",
    "FROM_DISTRICT",
    "TO_DISTRICT",
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


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if usecols is not None:
        usecols = [c for c in usecols if c in header]
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _normalize_route(value: Any) -> str:
    text = str(value or "").upper().strip()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\s+", "", text)
    text = text.replace("R-VA", "VA").replace(" ", "")
    text = text.replace("STATEHIGHWAY", "").replace("STATEROUTE", "")
    text = re.sub(r"[^A-Z0-9-]", "", text)
    return text


def _distance_band(distance_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([distance_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    if value <= 0:
        return "0ft"
    if value <= 5:
        return "0_5ft"
    if value <= 25:
        return "5_25ft"
    if value <= 50:
        return "25_50ft"
    if value <= 100:
        return "50_100ft"
    if value <= 250:
        return "100_250ft"
    if value <= 500:
        return "250_500ft"
    return "over_500ft"


def _field_inventory(frame: pd.DataFrame, dataset: str, fields: list[str]) -> pd.DataFrame:
    rows = []
    for field in fields:
        if field not in frame.columns:
            rows.append({"dataset": dataset, "field_name": field, "exists": False, "non_null_count": 0, "unique_non_null_count": 0, "sample_values": ""})
            continue
        series = frame[field].replace("", pd.NA)
        rows.append(
            {
                "dataset": dataset,
                "field_name": field,
                "exists": True,
                "non_null_count": int(series.notna().sum()),
                "unique_non_null_count": int(series.dropna().nunique()),
                "sample_values": " | ".join(series.dropna().astype(str).drop_duplicates().head(6).tolist()),
            }
        )
    return pd.DataFrame(rows)


def _load_speed() -> gpd.GeoDataFrame:
    speed = gpd.read_parquet(SPEED_FILE)
    speed = speed.to_crs(WORKING_CRS_AUTHORITY).reset_index(names="speed_source_index")
    speed["speed_geometry_is_null"] = speed.geometry.isna()
    speed["speed_geometry_is_valid"] = speed.geometry.notna() & speed.geometry.is_valid
    speed["speed_route_norm"] = speed["ROUTE_COMMON_NAME"].map(_normalize_route) if "ROUTE_COMMON_NAME" in speed.columns else ""
    return speed


def _load_stable_route_context() -> pd.DataFrame:
    bins = _read_csv(USABLE_BINS_FILE)
    role_fields = ["oriented_segment_id", *STABLE_ROUTE_FIELDS]
    roles = _read_csv(ROLE_ENRICHED_SEGMENTS_FILE, usecols=role_fields)
    roles = roles.rename(columns={"oriented_segment_id": "base_segment_id"})
    out = bins.merge(roles, on="base_segment_id", how="left")
    out["stable_route_norm"] = out["route_common"].map(_normalize_route) if "route_common" in out.columns else ""
    out["stable_route_type_norm"] = out["RTE_TYPE_N"].map(_normalize_route) if "RTE_TYPE_N" in out.columns else ""
    return out


def _load_base_geometries(source_keys: set[str]) -> gpd.GeoDataFrame:
    source = pd.read_csv(SOURCE_BIN_GEOMETRY_FILE, dtype=str, keep_default_na=False, usecols=["oriented_segment_id", "bin_id", "geometry"])
    source = source.loc[source["bin_id"].astype(str).isin(source_keys)].copy()
    source["geometry"] = source["geometry"].map(lambda value: wkt.loads(value) if isinstance(value, str) and value.strip() else None)
    source = source.rename(columns={"oriented_segment_id": "base_segment_id", "bin_id": "source_bin_key"})
    return gpd.GeoDataFrame(source, geometry="geometry", crs=WORKING_CRS_AUTHORITY)


def _nearest_speed_for_bins(target_bins: pd.DataFrame, speed: gpd.GeoDataFrame, stable_routes: pd.DataFrame) -> pd.DataFrame:
    target_keys = set(target_bins["source_bin_key"].dropna().astype(str))
    base = _load_base_geometries(target_keys)
    valid_speed = speed.loc[speed["speed_geometry_is_valid"]].copy()
    speed_cols = ["speed_source_index", CAR_SPEED_FIELD, TRUCK_SPEED_FIELD, *[c for c in SPEED_ROUTE_FIELDS if c in valid_speed.columns], "speed_route_norm", "geometry"]
    nearest = gpd.sjoin_nearest(base, valid_speed[speed_cols], how="left", distance_col="nearest_speed_distance_m")
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_speed_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest = nearest.sort_values(["source_bin_key", "nearest_speed_distance_ft", "speed_source_index"]).groupby("source_bin_key", dropna=False).head(1)
    stable_keep = ["reference_directional_bin_id", "source_bin_key", "base_segment_id", "reference_signal_id", "roadway_representation_type", "signal_relative_direction", "distance_window", "far_anchor_type", *[c for c in STABLE_ROUTE_FIELDS if c in stable_routes.columns], "stable_route_norm"]
    stable_for_merge = stable_routes.loc[stable_routes["source_bin_key"].astype(str).isin(target_keys), [c for c in stable_keep if c in stable_routes.columns]].copy()
    out = stable_for_merge.merge(nearest, on=["source_bin_key", "base_segment_id"], how="left", suffixes=("", "_nearest_speed"))
    out["nearest_speed_distance_ft"] = pd.to_numeric(out["nearest_speed_distance_ft"], errors="coerce").round(3)
    out["nearest_speed_distance_band"] = out["nearest_speed_distance_ft"].map(_distance_band)
    out["route_name_exact_match"] = out["stable_route_norm"].eq(out["speed_route_norm"])
    out["route_name_available_both"] = out["stable_route_norm"].astype(str).ne("") & out["speed_route_norm"].astype(str).ne("")
    return out


def _route_overlap_candidates(stable_routes: pd.DataFrame, speed: gpd.GeoDataFrame) -> pd.DataFrame:
    stable_names = set(stable_routes["stable_route_norm"].dropna().astype(str)) - {""}
    speed_names = set(speed["speed_route_norm"].dropna().astype(str)) - {""}
    rows = [
        {"comparison": "normalized_route_name", "stable_unique_values": len(stable_names), "speed_unique_values": len(speed_names), "overlap_unique_values": len(stable_names & speed_names), "stable_values_missing_from_speed": len(stable_names - speed_names), "speed_values_not_in_stable": len(speed_names - stable_names)},
    ]
    stable_types = set(stable_routes.get("RTE_TYPE_N", pd.Series(dtype=str)).map(_normalize_route).dropna().astype(str)) - {""}
    speed_types = set(speed.get("RTE_TYPE_NM", pd.Series(dtype=str)).map(_normalize_route).dropna().astype(str)) - {""}
    rows.append({"comparison": "route_type_name", "stable_unique_values": len(stable_types), "speed_unique_values": len(speed_types), "overlap_unique_values": len(stable_types & speed_types), "stable_values_missing_from_speed": len(stable_types - speed_types), "speed_values_not_in_stable": len(speed_types - stable_types)})
    return pd.DataFrame(rows)


def _agreement_summary(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    return (
        frame.groupby(["nearest_speed_distance_band", "route_name_available_both", "route_name_exact_match"], dropna=False)
        .agg(bin_count=("reference_directional_bin_id", "nunique"), median_nearest_speed_distance_ft=("nearest_speed_distance_ft", "median"))
        .reset_index()
        .assign(diagnostic_group=label)
    )


def _fallback_distance_by_route_agreement(candidates: pd.DataFrame, stable_routes: pd.DataFrame) -> pd.DataFrame:
    work = candidates.loc[candidates["speed_context_method"].eq("base_line_nearest_within_tolerance")].copy()
    if work.empty:
        return pd.DataFrame()
    stable = stable_routes[["source_bin_key", "stable_route_norm", "route_common", "roadway_representation_type", "distance_window"]].drop_duplicates("source_bin_key")
    work = work.merge(stable, on="source_bin_key", how="left")
    work["speed_route_norm"] = work["ROUTE_COMMON_NAME"].map(_normalize_route) if "ROUTE_COMMON_NAME" in work.columns else ""
    work["route_name_exact_match"] = work["stable_route_norm"].eq(work["speed_route_norm"])
    work["nearest_speed_distance_ft"] = pd.to_numeric(work["nearest_speed_distance_ft"], errors="coerce")
    work["nearest_speed_distance_band"] = work["nearest_speed_distance_ft"].map(_distance_band)
    return (
        work.groupby(["nearest_speed_distance_band", "route_name_exact_match", "roadway_representation_type", "distance_window"], dropna=False)
        .agg(candidate_count=("source_bin_key", "count"), base_bin_count=("source_bin_key", "nunique"), median_distance_ft=("nearest_speed_distance_ft", "median"))
        .reset_index()
    )


def _severe_conflict_route_diagnostic(ambiguous: pd.DataFrame, stable_routes: pd.DataFrame) -> pd.DataFrame:
    if ambiguous.empty:
        return pd.DataFrame()
    stable = stable_routes[["source_bin_key", "stable_route_norm", "route_common", "roadway_representation_type", "distance_window"]].drop_duplicates("source_bin_key")
    work = ambiguous.merge(stable, on="source_bin_key", how="left")
    work["speed_route_norm"] = work["ROUTE_COMMON_NAME"].map(_normalize_route) if "ROUTE_COMMON_NAME" in work.columns else ""
    work["route_name_exact_match"] = work["stable_route_norm"].eq(work["speed_route_norm"])
    rows = []
    for key, group in work.groupby("source_bin_key", dropna=False):
        car_values = pd.to_numeric(group[CAR_SPEED_FIELD], errors="coerce").dropna().sort_values().unique().tolist()
        truck_values = pd.to_numeric(group[TRUCK_SPEED_FIELD], errors="coerce").dropna().sort_values().unique().tolist()
        all_values = sorted(set(car_values + truck_values))
        spread = max(all_values) - min(all_values) if all_values else pd.NA
        rows.append(
            {
                "source_bin_key": key,
                "candidate_count": len(group),
                "stable_route_name": group["route_common"].dropna().astype(str).head(1).iloc[0] if "route_common" in group.columns and not group["route_common"].dropna().empty else "",
                "speed_route_names": "|".join(sorted(group["ROUTE_COMMON_NAME"].dropna().astype(str).unique().tolist())) if "ROUTE_COMMON_NAME" in group.columns else "",
                "all_candidates_match_stable_route": bool(group["route_name_exact_match"].all()),
                "any_candidate_matches_stable_route": bool(group["route_name_exact_match"].any()),
                "car_speed_values": "|".join(_format_speed(v) for v in car_values),
                "truck_speed_values": "|".join(_format_speed(v) for v in truck_values),
                "speed_spread_mph": spread,
                "severe_conflict_spread_ge_15mph": bool(pd.notna(spread) and spread >= 15),
                "roadway_representation_type": group["roadway_representation_type"].dropna().astype(str).head(1).iloc[0] if "roadway_representation_type" in group.columns and not group["roadway_representation_type"].dropna().empty else "",
                "distance_window": group["distance_window"].dropna().astype(str).head(1).iloc[0] if "distance_window" in group.columns and not group["distance_window"].dropna().empty else "",
            }
        )
    return pd.DataFrame(rows).sort_values(["severe_conflict_spread_ge_15mph", "speed_spread_mph", "candidate_count"], ascending=[False, False, False])


def _format_speed(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric) and float(numeric).is_integer():
        return str(int(numeric))
    return str(value)


def _base_overlap_failure(candidates: pd.DataFrame, v2_summary: pd.DataFrame, fallback_agreement: pd.DataFrame) -> pd.DataFrame:
    nearest = candidates.loc[candidates["speed_context_method"].eq("base_line_nearest_within_tolerance")].copy()
    nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_speed_distance_ft"], errors="coerce")
    zero_distance = int(nearest["nearest_speed_distance_ft"].eq(0).sum())
    within_5 = int(nearest["nearest_speed_distance_ft"].le(5).sum())
    route_match_share = pd.NA
    if not fallback_agreement.empty:
        total = fallback_agreement["base_bin_count"].sum()
        matches = fallback_agreement.loc[fallback_agreement["route_name_exact_match"].astype(bool), "base_bin_count"].sum()
        route_match_share = round(float(matches / total), 6) if total else pd.NA
    return pd.DataFrame(
        [
            {"diagnostic": "base_overlap_count", "value": _summary_count(v2_summary, "bins_with_speed_by_base_overlap"), "interpretation": "Exact line overlap did not assign bins."},
            {"diagnostic": "base_nearest_fallback_count", "value": _summary_count(v2_summary, "bins_with_speed_by_base_nearest_fallback"), "interpretation": "Assignments depend on nearest-line geometry, not collinear overlap."},
            {"diagnostic": "nearest_candidate_rows_at_0ft", "value": zero_distance, "interpretation": "Distance-zero nearest rows with zero overlap indicate crossing/touching or non-collinear source linework."},
            {"diagnostic": "nearest_candidate_rows_within_5ft", "value": within_5, "interpretation": "Near-zero offsets point to related but differently segmented or differently represented networks."},
            {"diagnostic": "fallback_route_match_share", "value": route_match_share, "interpretation": "High route agreement would support a route-assisted spatial filter."},
        ]
    )


def _summary_count(summary: pd.DataFrame, metric: str) -> Any:
    row = summary.loc[summary["metric"].eq(metric)]
    return "" if row.empty else row.iloc[0]["count"]


def _summary(
    stable_inventory: pd.DataFrame,
    speed_inventory: pd.DataFrame,
    overlap: pd.DataFrame,
    missing_diag: pd.DataFrame,
    fallback_agreement: pd.DataFrame,
    severe_diag: pd.DataFrame,
    base_failure: pd.DataFrame,
) -> pd.DataFrame:
    stable_route_fields = int(stable_inventory["exists"].astype(bool).sum())
    speed_route_fields = int(speed_inventory["exists"].astype(bool).sum())
    route_overlap = overlap.loc[overlap["comparison"].eq("normalized_route_name")]
    route_overlap_count = int(route_overlap.iloc[0]["overlap_unique_values"]) if not route_overlap.empty else 0
    missing_total = missing_diag["reference_directional_bin_id"].nunique() if not missing_diag.empty else 0
    missing_route_available = int(missing_diag["route_name_available_both"].astype(bool).sum()) if not missing_diag.empty else 0
    missing_route_match = int(missing_diag["route_name_exact_match"].astype(bool).sum()) if not missing_diag.empty else 0
    fallback_total = int(fallback_agreement["base_bin_count"].sum()) if not fallback_agreement.empty else 0
    fallback_route_match = int(fallback_agreement.loc[fallback_agreement["route_name_exact_match"].astype(bool), "base_bin_count"].sum()) if not fallback_agreement.empty else 0
    severe_count = int(severe_diag["severe_conflict_spread_ge_15mph"].astype(bool).sum()) if not severe_diag.empty else 0
    zero_overlap = str(base_failure.loc[base_failure["diagnostic"].eq("base_overlap_count"), "value"].iloc[0])
    return pd.DataFrame(
        [
            {"metric": "stable_route_fields_existing", "value": "", "count": stable_route_fields},
            {"metric": "speed_route_fields_existing", "value": "", "count": speed_route_fields},
            {"metric": "normalized_route_name_overlap_unique_values", "value": "", "count": route_overlap_count},
            {"metric": "missing_speed_bins_diagnosed", "value": "", "count": missing_total},
            {"metric": "missing_bins_with_route_available_both", "value": "", "count": missing_route_available},
            {"metric": "missing_bins_nearest_speed_route_exact_match", "value": "", "count": missing_route_match},
            {"metric": "fallback_base_bins_with_route_diagnostic", "value": "", "count": fallback_total},
            {"metric": "fallback_base_bins_route_exact_match", "value": "", "count": fallback_route_match},
            {"metric": "severe_conflict_base_bins", "value": "", "count": severe_count},
            {"metric": "base_overlap_count", "value": zero_overlap, "count": ""},
            {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
            {"metric": "speed_scaffold_assignment_access_logic_changed", "value": False, "count": ""},
        ]
    )


def _findings(summary: pd.DataFrame, outputs: dict[str, Path]) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["count"]

    route_feasible = int(count("normalized_route_name_overlap_unique_values") or 0) > 0 and int(count("fallback_base_bins_route_exact_match") or 0) > 0
    overlap_zero = summary.loc[summary["metric"].eq("base_overlap_count"), "value"].iloc[0]
    return "\n".join(
        [
            "# Posted Speed Route Coverage Diagnostic Findings",
            "",
            "## Bounded Question",
            "",
            "Diagnose posted-speed route/source compatibility without changing speed joins, scaffold, catchments, crash assignment, access context, or upstream/downstream labels.",
            "",
            "## Key Findings",
            "",
            f"- stable route/name fields present: {count('stable_route_fields_existing')}",
            f"- speed route/name fields present: {count('speed_route_fields_existing')}",
            f"- normalized route-name overlap values: {count('normalized_route_name_overlap_unique_values')}",
            f"- missing speed bins diagnosed: {count('missing_speed_bins_diagnosed')}",
            f"- missing bins where stable and nearest speed route fields both exist: {count('missing_bins_with_route_available_both')}",
            f"- missing bins whose nearest speed route exactly matches stable route: {count('missing_bins_nearest_speed_route_exact_match')}",
            f"- fallback base bins with route diagnostic: {count('fallback_base_bins_with_route_diagnostic')}",
            f"- fallback base bins with exact route match: {count('fallback_base_bins_route_exact_match')}",
            f"- severe conflict base bins: {count('severe_conflict_base_bins')}",
            f"- base overlap count: {overlap_zero}",
            "",
            "## Interpretation",
            "",
            "- Stable route/name fields exist on role-enriched segment records, not on the simple scaffold bin table.",
            "- Posted-speed source route fields also exist, especially `ROUTE_COMMON_NAME`, route type, directionality, and route measure fields.",
            "- Base overlap is likely zero because posted-speed source events and Travelway/source bin lines are related but not represented as collinear identical linework; nearest distance can be zero while overlap length remains zero when lines cross, touch, or are differently segmented.",
            "- Missing bins should be treated as a mix of source coverage/route representation gaps and join-method filtering gaps, not as an upstream/downstream issue.",
            f"- Route-assisted speed join feasible: {route_feasible}",
            "",
            "## Boundary Checks",
            "",
            f"- crash direction fields read or used: {summary.loc[summary['metric'].eq('crash_direction_fields_read_or_used'), 'value'].iloc[0]}",
            f"- speed/scaffold/assignment/access logic changed: {summary.loc[summary['metric'].eq('speed_scaffold_assignment_access_logic_changed'), 'value'].iloc[0]}",
            "",
            "## Files Created",
            "",
            *[f"- `{path}`" for path in outputs.values()],
            "",
            "## Recommended Next Speed Fix",
            "",
            "Prototype a route-assisted nearest base-line join: require normalized route-name agreement where available, summarize route type and distance bands, and keep non-matching nearest candidates in review rather than assigning them as stable speed context.",
            "",
        ]
    )


def build_posted_speed_route_coverage_diagnostic(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    speed = _load_speed()
    stable_routes = _load_stable_route_context()
    v2_context = _read_csv(V2_BIN_CONTEXT_FILE)
    v2_candidates = _read_csv(V2_MATCH_CANDIDATES_FILE)
    v2_ambiguous = _read_csv(V2_AMBIGUOUS_FILE)
    v2_summary = _read_csv(V2_SUMMARY_FILE)
    if COVERAGE_SUMMARY_FILE.exists():
        _ = _read_csv(COVERAGE_SUMMARY_FILE)
    if STAGING_SCHEMA_FILE.exists():
        _ = _read_csv(STAGING_SCHEMA_FILE)
    if STAGING_FIELD_ROLES_FILE.exists():
        _ = _read_csv(STAGING_FIELD_ROLES_FILE)
    if STAGING_CRS_SANITY_FILE.exists():
        _ = _read_csv(STAGING_CRS_SANITY_FILE)
    _ = _read_csv(USABLE_SEGMENTS_FILE)

    stable_routes = stable_routes.merge(v2_context[["reference_directional_bin_id", "source_bin_key", "distance_window", "speed_context_status"]], on="reference_directional_bin_id", how="left")
    stable_inventory = _field_inventory(stable_routes, "stable_role_enriched_segments", STABLE_ROUTE_FIELDS)
    speed_inventory = _field_inventory(pd.DataFrame(speed.drop(columns=["geometry"], errors="ignore")), "posted_speed_source", SPEED_ROUTE_FIELDS)
    route_overlap = _route_overlap_candidates(stable_routes, speed)
    missing = stable_routes.loc[stable_routes["speed_context_status"].eq("no_speed_nearby")].copy()
    missing_diag = _nearest_speed_for_bins(missing, speed, stable_routes)
    fallback_agreement = _fallback_distance_by_route_agreement(v2_candidates, stable_routes)
    nearest_agreement = pd.concat([_agreement_summary(missing_diag, "missing_speed_bins")], ignore_index=True)
    severe_diag = _severe_conflict_route_diagnostic(v2_ambiguous, stable_routes)
    base_failure = _base_overlap_failure(v2_candidates, v2_summary, fallback_agreement)
    summary = _summary(stable_inventory, speed_inventory, route_overlap, missing_diag, fallback_agreement, severe_diag, base_failure)

    outputs = {
        "summary_csv": out_dir / "posted_speed_route_coverage_summary.csv",
        "stable_route_inventory_csv": out_dir / "stable_bin_route_field_inventory.csv",
        "speed_route_inventory_csv": out_dir / "speed_source_route_field_inventory.csv",
        "route_field_overlap_csv": out_dir / "route_field_overlap_candidates.csv",
        "missing_route_diagnostic_csv": out_dir / "missing_speed_bins_route_diagnostic.csv",
        "nearest_route_agreement_csv": out_dir / "nearest_speed_route_agreement_diagnostic.csv",
        "fallback_distance_by_route_agreement_csv": out_dir / "speed_fallback_distance_by_route_agreement.csv",
        "severe_conflict_route_diagnostic_csv": out_dir / "severe_speed_conflict_route_diagnostic.csv",
        "base_overlap_failure_csv": out_dir / "base_overlap_failure_diagnostic.csv",
        "findings_md": out_dir / "posted_speed_route_coverage_findings.md",
        "manifest_json": out_dir / "posted_speed_route_coverage_manifest.json",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(stable_inventory, outputs["stable_route_inventory_csv"])
    _write_csv(speed_inventory, outputs["speed_route_inventory_csv"])
    _write_csv(route_overlap, outputs["route_field_overlap_csv"])
    _write_csv(missing_diag, outputs["missing_route_diagnostic_csv"])
    _write_csv(nearest_agreement, outputs["nearest_route_agreement_csv"])
    _write_csv(fallback_agreement, outputs["fallback_distance_by_route_agreement_csv"])
    _write_csv(severe_diag, outputs["severe_conflict_route_diagnostic_csv"])
    _write_csv(base_failure, outputs["base_overlap_failure_csv"])
    _write_text(_findings(summary, outputs), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only posted-speed source coverage and route-representation diagnostic",
        "crash_direction_fields_read_or_used": False,
        "speed_join_logic_changed": False,
        "scaffold_catchment_assignment_access_logic_changed": False,
        "inputs": {
            "speed": str(SPEED_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "usable_segments": str(USABLE_SEGMENTS_FILE),
            "source_bin_geometry": str(SOURCE_BIN_GEOMETRY_FILE),
            "role_enriched_segments": str(ROLE_ENRICHED_SEGMENTS_FILE),
            "v2_bin_context": str(V2_BIN_CONTEXT_FILE),
            "v2_candidates": str(V2_MATCH_CANDIDATES_FILE),
            "v2_ambiguous": str(V2_AMBIGUOUS_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "speed_crs": crs_to_string(speed.crs),
        "speed_crs_matches_working_crs": crs_matches(speed.crs, WORKING_CRS_AUTHORITY),
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose posted-speed route/source compatibility.")
    parser.parse_args()
    outputs = build_posted_speed_route_coverage_diagnostic()
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
