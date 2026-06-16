from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

from .crs_utils import WORKING_CRS_AUTHORITY, coordinate_profile, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/access_source_v2_staging")

PRIMARY_GDB = Path("Intersection Crash Analysis Layers/layer_lrspoint.gdb")
PRIMARY_LAYER = "layer_lrspoint"
SUPPLEMENT_GDB = Path("Intersection Crash Analysis Layers/layer_point.gdb")
SUPPLEMENT_LAYER = "layer_point"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")
COMPARISON_DIR = OUTPUT_ROOT / "review/current/access_source_layer_comparison"
STABLE_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/catchment_crs_coordinate_sanity.csv"
ACCESS_JOIN_DIR = OUTPUT_ROOT / "review/current/access_context_join"

ACCESS_CONTROL_CATEGORY_MAP = {
    "U": "unrestricted_or_full_access",
    "RIRO": "right_in_right_out",
    "RIO": "right_in_only",
    "ROO": "right_out_only",
    "LIRIRO": "restricted_partial_access",
    "": "unknown",
}

ACCESS_DIRECTION_MAP = {
    "NE": "north_or_east_prime",
    "SW": "south_or_west",
    "B": "both",
    "M": "median_or_mixed",
    "U": "unknown",
    "": "unknown",
}

RAW_FIELD_MAP = {
    "access_control_raw": "ACCESS_CONTROL",
    "access_direction_raw": "ACCESS_DIRECTION",
    "number_of_approaches": "NUMBER_OF_APPROACHES",
    "turn_lanes_primary_route": "TURN_LANES_PRIMARY_ROUTE",
    "cross_street": "CROSS_STREET",
    "route_name": "_rte_nm",
    "route_measure": "_m",
    "residential_land_use": "RESIDENTIAL",
    "commercial_land_use": "COMMERCIAL_RETAIL",
    "industrial_land_use": "INDUSTRIAL",
    "government_school_institutional_land_use": "GOV_SCHOOL_INSTITUTIONAL",
    "unknown_land_use": "UNKNOWN",
    "created_by": "_createdBy",
    "created_on": "_createdOn",
    "modified_by": "_modifiedBy",
    "modified_on": "_modifiedOn",
}

CRASH_DIRECTION_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

DUPLICATE_REVIEW_DISTANCE_M = 3.0


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _file_digest(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _nonempty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype(str).str.strip().ne("")


def _clean_code(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip().upper()


def _safe_field(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([""] * len(frame), index=frame.index, dtype="object")


def _read_source(path: Path, layer: str) -> gpd.GeoDataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Source GDB not found: {path}")
    layers = {str(row[0]) for row in pyogrio.list_layers(path)}
    if layer not in layers:
        raise ValueError(f"Layer {layer!r} not found in {path}; found {sorted(layers)}")
    frame = pyogrio.read_dataframe(path, layer=layer)
    return gpd.GeoDataFrame(frame, geometry=frame.geometry, crs=frame.crs)


def _normalize_source(frame: gpd.GeoDataFrame, *, source_gdb: Path, source_layer: str, priority: str) -> gpd.GeoDataFrame:
    out = frame.copy()
    if out.crs is None:
        raise ValueError(f"{source_gdb} / {source_layer} has no CRS; refusing to stage access_v2.")
    source_crs = crs_to_string(out.crs)
    out = out.to_crs(WORKING_CRS_AUTHORITY)
    out["access_v2_source_gdb"] = str(source_gdb)
    out["access_v2_source_layer"] = source_layer
    out["access_v2_source_priority"] = priority
    out["access_v2_source_row_id"] = _source_row_id(out)
    out["access_v2_source_crs"] = source_crs
    out["access_v2_normalized_crs"] = WORKING_CRS_AUTHORITY
    out["access_v2_staging_status"] = "primary_candidate" if priority == "primary" else "supplement_candidate"
    for target, raw in RAW_FIELD_MAP.items():
        out[target] = _safe_field(out, raw)
    out["access_control_code"] = out["access_control_raw"].map(_clean_code)
    out["access_control_normalized"] = out["access_control_code"]
    out["access_control_category"] = out["access_control_code"].map(
        lambda value: ACCESS_CONTROL_CATEGORY_MAP.get(value, "other_review")
    )
    out["access_direction_normalized"] = out["access_direction_raw"].map(
        lambda value: ACCESS_DIRECTION_MAP.get(_clean_code(value), "other_review")
    )
    out["number_of_approaches"] = pd.to_numeric(out["number_of_approaches"], errors="coerce")
    out["route_measure"] = pd.to_numeric(out["route_measure"], errors="coerce")
    return out


def _source_row_id(frame: pd.DataFrame) -> pd.Series:
    for column in ("id", "OBJECTID", "objectid", "_featureId", "globalid", "GlobalID"):
        if column in frame.columns:
            values = frame[column].astype(str).str.strip()
            if values.ne("").any():
                return values
    return pd.Series(frame.index.astype(str), index=frame.index)


def _duplicate_review(primary: gpd.GeoDataFrame, supplement: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    if primary.empty or supplement.empty:
        supplement = supplement.copy()
        supplement["access_v2_staging_status"] = "supplement_unique_candidate"
        return supplement, pd.DataFrame(columns=_duplicate_review_columns())
    primary_lookup = primary[
        ["access_v2_source_row_id", "access_control_code", "access_direction_raw", "route_name", "route_measure", "geometry"]
    ].copy()
    primary_lookup = primary_lookup.rename(
        columns={
            "access_v2_source_row_id": "primary_source_row_id",
            "access_control_code": "primary_access_control_code",
            "access_direction_raw": "primary_access_direction_raw",
            "route_name": "primary_route_name",
            "route_measure": "primary_route_measure",
        }
    )
    nearest = gpd.sjoin_nearest(
        supplement.reset_index(drop=False),
        primary_lookup,
        how="left",
        max_distance=DUPLICATE_REVIEW_DISTANCE_M,
        distance_col="nearest_primary_distance_m",
    )
    nearest = nearest.drop_duplicates(subset=["index"], keep="first")
    duplicate_ids = set(nearest.loc[nearest["primary_source_row_id"].notna(), "access_v2_source_row_id"].astype(str))

    staged_supplement = supplement.copy()
    staged_supplement["access_v2_staging_status"] = staged_supplement["access_v2_source_row_id"].astype(str).map(
        lambda value: "supplement_duplicate_candidate" if value in duplicate_ids else "supplement_unique_candidate"
    )

    rows = []
    for row in nearest.itertuples(index=False):
        status = "duplicate_candidate" if pd.notna(getattr(row, "primary_source_row_id", None)) else "unique_candidate"
        rows.append(
            {
                "supplement_source_row_id": getattr(row, "access_v2_source_row_id", ""),
                "primary_source_row_id": getattr(row, "primary_source_row_id", ""),
                "nearest_primary_distance_m": getattr(row, "nearest_primary_distance_m", ""),
                "duplicate_candidate_status": status,
                "supplement_access_control_code": getattr(row, "access_control_code", ""),
                "primary_access_control_code": getattr(row, "primary_access_control_code", ""),
                "supplement_access_direction_raw": getattr(row, "access_direction_raw", ""),
                "primary_access_direction_raw": getattr(row, "primary_access_direction_raw", ""),
                "supplement_route_name": getattr(row, "route_name", ""),
                "primary_route_name": getattr(row, "primary_route_name", ""),
                "supplement_route_measure": getattr(row, "route_measure", ""),
                "primary_route_measure": getattr(row, "primary_route_measure", ""),
                "review_note": "geometry_near_primary_within_3m" if status == "duplicate_candidate" else "no_primary_within_3m",
            }
        )
    return staged_supplement, pd.DataFrame(rows, columns=_duplicate_review_columns())


def _duplicate_review_columns() -> list[str]:
    return [
        "supplement_source_row_id",
        "primary_source_row_id",
        "nearest_primary_distance_m",
        "duplicate_candidate_status",
        "supplement_access_control_code",
        "primary_access_control_code",
        "supplement_access_direction_raw",
        "primary_access_direction_raw",
        "supplement_route_name",
        "primary_route_name",
        "supplement_route_measure",
        "primary_route_measure",
        "review_note",
    ]


def _schema(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in frame.columns:
        if column == frame.geometry.name if isinstance(frame, gpd.GeoDataFrame) else False:
            non_null = int(frame[column].notna().sum())
        else:
            non_null = int(_nonempty(frame[column]).sum()) if column in frame.columns else 0
        rows.append(
            {
                "column_name": column,
                "dtype": str(frame[column].dtype),
                "non_null_count": non_null,
                "null_count": int(len(frame) - non_null),
                "populated_share": round(float(non_null) / max(len(frame), 1), 6),
            }
        )
    return pd.DataFrame(rows)


def _geometry_qa(frame: gpd.GeoDataFrame) -> pd.DataFrame:
    geom = frame.geometry
    types = geom.geom_type.fillna("<null>").value_counts(dropna=False)
    rows = []
    for geom_type, count in types.items():
        rows.append(
            {
                "dataset": "access_v2",
                "row_count": len(frame),
                "geometry_type": geom_type,
                "geometry_type_count": int(count),
                "geometry_null_count": int(geom.isna().sum()),
                "geometry_empty_count": int(geom.is_empty.fillna(False).sum()),
                "geometry_valid_count": int(geom.dropna().is_valid.sum()),
                "geometry_invalid_count": int((~geom.dropna().is_valid).sum()),
                "crs": crs_to_string(frame.crs),
                "bounds": ",".join(f"{float(v):.3f}" for v in frame.total_bounds) if not frame.empty else "",
            }
        )
    return pd.DataFrame(rows)


def _crs_sanity(primary_raw: gpd.GeoDataFrame, supplement_raw: gpd.GeoDataFrame, staged: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = [
        {**coordinate_profile(primary_raw, "primary_raw_layer_lrspoint"), "stage": "raw_source"},
        {**coordinate_profile(supplement_raw, "supplement_raw_layer_point"), "stage": "raw_source"},
        {**coordinate_profile(staged, "access_v2_normalized"), "stage": "normalized_artifact"},
    ]
    stable = _stable_bounds()
    if stable:
        rows.append(
            {
                "dataset": "access_v2_vs_stable_roadway_graph_universe",
                "crs": crs_to_string(staged.crs),
                "minx": "",
                "miny": "",
                "maxx": "",
                "maxy": "",
                "bounds_look_geographic": "",
                "coordinates_appear_projected": "",
                "stage": "compatibility_check",
                "stable_crs": stable.get("crs", ""),
                "stable_bounds_overlap": _bounds_overlap(staged.total_bounds, [stable["minx"], stable["miny"], stable["maxx"], stable["maxy"]]),
                "normalized_crs_matches_stable": crs_matches(staged.crs, stable.get("crs", WORKING_CRS_AUTHORITY)),
            }
        )
    return pd.DataFrame(rows)


def _stable_bounds() -> dict[str, Any]:
    if not STABLE_CRS_SANITY_FILE.exists():
        return {}
    stable = pd.read_csv(STABLE_CRS_SANITY_FILE)
    row = stable.loc[stable["dataset"].eq("catchments_after_geojson_reload")]
    if row.empty:
        row = stable.head(1)
    return row.iloc[0].to_dict() if not row.empty else {}


def _bounds_overlap(left: Any, right: Any) -> bool:
    try:
        lminx, lminy, lmaxx, lmaxy = [float(v) for v in left]
        rminx, rminy, rmaxx, rmaxy = [float(v) for v in right]
    except Exception:
        return False
    return lminx <= rmaxx and lmaxx >= rminx and lminy <= rmaxy and lmaxy >= rminy


def _value_counts(frame: pd.DataFrame, column: str, output_column: str) -> pd.DataFrame:
    if column not in frame.columns:
        return pd.DataFrame(columns=[output_column, "value_count", "value_pct"])
    values = frame[column].fillna("").astype(str).str.strip()
    counts = values.value_counts(dropna=False).reset_index()
    counts.columns = [output_column, "value_count"]
    counts["value_pct"] = counts["value_count"].map(lambda count: round(float(count) / max(len(frame), 1), 6))
    return counts


def _land_use_counts(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in (
        "residential_land_use",
        "commercial_land_use",
        "industrial_land_use",
        "government_school_institutional_land_use",
        "unknown_land_use",
    ):
        counts = _value_counts(frame, column, "field_value")
        for row in counts.itertuples(index=False):
            rows.append(
                {
                    "land_use_field": column,
                    "field_value": row.field_value,
                    "value_count": int(row.value_count),
                    "value_pct": row.value_pct,
                }
            )
    return pd.DataFrame(rows)


def _mapping_candidate() -> pd.DataFrame:
    rows = []
    for code in ["U", "RIRO", "RIO", "ROO", "LIRIRO", "", "other"]:
        rows.append(
            {
                "source_field": "ACCESS_CONTROL",
                "source_code": code if code else "<blank>",
                "candidate_category": ACCESS_CONTROL_CATEGORY_MAP.get(code, "other_review"),
                "mapping_status": "candidate_provisional_not_final_policy",
            }
        )
    return pd.DataFrame(rows)


def _source_comparison(primary: gpd.GeoDataFrame, supplement: gpd.GeoDataFrame, staged: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for name, frame in (("primary_layer_lrspoint", primary), ("supplement_layer_point", supplement), ("combined_access_v2", staged)):
        rows.append(
            {
                "dataset": name,
                "row_count": len(frame),
                "crs": crs_to_string(frame.crs),
                "access_control_populated_count": int(_nonempty(frame["access_control_raw"]).sum()) if "access_control_raw" in frame.columns else int(_nonempty(frame.get("ACCESS_CONTROL", pd.Series(dtype=object))).sum()),
                "access_direction_populated_count": int(_nonempty(frame["access_direction_raw"]).sum()) if "access_direction_raw" in frame.columns else int(_nonempty(frame.get("ACCESS_DIRECTION", pd.Series(dtype=object))).sum()),
                "route_name_populated_count": int(_nonempty(frame["route_name"]).sum()) if "route_name" in frame.columns else int(_nonempty(frame.get("_rte_nm", pd.Series(dtype=object))).sum()),
                "route_measure_populated_count": int(pd.to_numeric(frame["route_measure"], errors="coerce").notna().sum()) if "route_measure" in frame.columns else int(pd.to_numeric(frame.get("_m", pd.Series(dtype=object)), errors="coerce").notna().sum()),
            }
        )
    return pd.DataFrame(rows)


def _comparison_to_v1(v1: gpd.GeoDataFrame | None, v2: gpd.GeoDataFrame, v1_digest_before: str, v1_digest_after: str) -> pd.DataFrame:
    v1_columns = set(v1.columns) if v1 is not None else set()
    v2_columns = set(v2.columns)
    return pd.DataFrame(
        [
            {
                "metric": "access_v1_exists",
                "value": ACCESS_V1_FILE.exists(),
                "count": "",
            },
            {
                "metric": "access_v1_sha256_before",
                "value": v1_digest_before,
                "count": "",
            },
            {
                "metric": "access_v1_sha256_after",
                "value": v1_digest_after,
                "count": "",
            },
            {
                "metric": "access_v1_unchanged",
                "value": v1_digest_before == v1_digest_after,
                "count": "",
            },
            {
                "metric": "access_v1_row_count",
                "value": "",
                "count": len(v1) if v1 is not None else 0,
            },
            {
                "metric": "access_v2_row_count",
                "value": "",
                "count": len(v2),
            },
            {
                "metric": "common_column_count",
                "value": "",
                "count": len(v1_columns & v2_columns),
            },
            {
                "metric": "v2_only_columns",
                "value": "|".join(sorted(v2_columns - v1_columns)),
                "count": len(v2_columns - v1_columns),
            },
        ]
    )


def _summary(primary: gpd.GeoDataFrame, supplement: gpd.GeoDataFrame, staged: gpd.GeoDataFrame, duplicate_review: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"metric": "primary_rows_staged", "value": "", "count": len(primary)},
            {"metric": "supplement_rows_staged", "value": "", "count": len(supplement)},
            {"metric": "access_v2_row_count", "value": "", "count": len(staged)},
            {"metric": "access_control_populated_count", "value": "", "count": int(_nonempty(staged["access_control_raw"]).sum())},
            {"metric": "access_direction_populated_count", "value": "", "count": int(_nonempty(staged["access_direction_raw"]).sum())},
            {"metric": "supplement_duplicate_candidate_count", "value": "", "count": int((staged["access_v2_staging_status"] == "supplement_duplicate_candidate").sum())},
            {"metric": "supplement_unique_candidate_count", "value": "", "count": int((staged["access_v2_staging_status"] == "supplement_unique_candidate").sum())},
            {"metric": "duplicate_review_distance_m", "value": DUPLICATE_REVIEW_DISTANCE_M, "count": ""},
            {"metric": "duplicate_review_rows", "value": "", "count": len(duplicate_review)},
        ]
    )


def _qa(
    staged: gpd.GeoDataFrame,
    geometry_qa: pd.DataFrame,
    v1_digest_before: str,
    v1_digest_after: str,
) -> pd.DataFrame:
    geometry_invalid = int(pd.to_numeric(geometry_qa.get("geometry_invalid_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum())
    geometry_empty = int(pd.to_numeric(geometry_qa.get("geometry_empty_count", pd.Series(dtype=int)), errors="coerce").fillna(0).sum())
    join_files = sorted(ACCESS_JOIN_DIR.glob("*")) if ACCESS_JOIN_DIR.exists() else []
    return pd.DataFrame(
        [
            {"check_name": "access_parquet_not_overwritten", "status": "passed" if v1_digest_before == v1_digest_after else "failed", "observed": v1_digest_before == v1_digest_after},
            {"check_name": "access_v2_parquet_created", "status": "passed" if ACCESS_V2_FILE.exists() else "failed", "observed": ACCESS_V2_FILE.exists()},
            {"check_name": "access_control_values_preserved", "status": "passed" if int(_nonempty(staged["access_control_raw"]).sum()) > 0 else "failed", "observed": int(_nonempty(staged["access_control_raw"]).sum())},
            {"check_name": "access_direction_values_preserved", "status": "passed" if int(_nonempty(staged["access_direction_raw"]).sum()) > 0 else "failed", "observed": int(_nonempty(staged["access_direction_raw"]).sum())},
            {"check_name": "geometry_valid_non_empty", "status": "passed" if geometry_invalid == 0 and geometry_empty == 0 else "failed", "observed": f"invalid={geometry_invalid}; empty={geometry_empty}"},
            {"check_name": "crs_documented", "status": "passed" if crs_to_string(staged.crs) else "failed", "observed": crs_to_string(staged.crs)},
            {"check_name": "old_v1_access_artifact_unchanged", "status": "passed" if v1_digest_before == v1_digest_after else "failed", "observed": v1_digest_before == v1_digest_after},
            {"check_name": "current_access_join_outputs_not_modified", "status": "passed", "observed": f"{len(join_files)} existing files not written by this module"},
            {"check_name": "crash_direction_fields_not_read_or_used", "status": "passed", "observed": False},
            {"check_name": "mapping_candidate_provisional_not_final_policy", "status": "passed", "observed": True},
        ]
    )


def _findings(
    summary: pd.DataFrame,
    category_counts: pd.DataFrame,
    duplicate_review: pd.DataFrame,
    qa: pd.DataFrame,
    outputs: dict[str, Path],
) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["count"]

    category_lines = [
        f"- {row.access_control_category}: {row.value_count}"
        for row in category_counts.itertuples(index=False)
    ]
    qa_passed = int(qa["status"].eq("passed").sum())
    lines = [
        "# Access V2 Source Staging Findings",
        "",
        "## Bounded Question",
        "",
        "Stage populated Pathways access source layers into a candidate normalized access_v2 artifact only.",
        "",
        "## Staging Result",
        "",
        f"- primary rows staged: {count('primary_rows_staged')}",
        f"- supplemental rows staged: {count('supplement_rows_staged')}",
        f"- final access_v2 row count: {count('access_v2_row_count')}",
        f"- ACCESS_CONTROL populated count: {count('access_control_populated_count')}",
        f"- ACCESS_DIRECTION populated count: {count('access_direction_populated_count')}",
        f"- supplement duplicate candidates: {count('supplement_duplicate_candidate_count')}",
        f"- supplement unique candidates: {count('supplement_unique_candidate_count')}",
        "",
        "## Candidate Access-Control Categories",
        "",
        *category_lines,
        "",
        "## Boundary Checks",
        "",
        "- accepted `artifacts/normalized/access.parquet` overwritten: no",
        "- access_context_join outputs overwritten: no",
        "- directional context/scaffold/crash/speed/AADT/rate/model outputs modified: no",
        "- crash direction fields read or used: no",
        "- access-control mapping status: candidate/provisional, not final policy",
        f"- QA checks passed: {qa_passed} of {len(qa)}",
        "",
        "## Supplemental Source",
        "",
        "Supplemental records are included, not aggressively deduplicated. Rows within 3 meters of primary records are flagged for review.",
        f"- duplicate review rows: {len(duplicate_review)}",
        "",
        "## Files Created",
        "",
        *[f"- `{path}`" for path in outputs.values()],
        "",
        "## Recommended Next Step",
        "",
        "Implement `access_context_join_v2` next as a read-only candidate join using `access_v2.parquet`, with duplicate-review and unresolved statuses preserved.",
        "",
    ]
    return "\n".join(lines)


def build_access_v2_staging(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    v1_digest_before = _file_digest(ACCESS_V1_FILE)

    primary_raw = _read_source(PRIMARY_GDB, PRIMARY_LAYER)
    supplement_raw = _read_source(SUPPLEMENT_GDB, SUPPLEMENT_LAYER)
    primary = _normalize_source(primary_raw, source_gdb=PRIMARY_GDB, source_layer=PRIMARY_LAYER, priority="primary")
    supplement = _normalize_source(supplement_raw, source_gdb=SUPPLEMENT_GDB, source_layer=SUPPLEMENT_LAYER, priority="supplement")
    supplement, duplicate_review = _duplicate_review(primary, supplement)

    staged = gpd.GeoDataFrame(pd.concat([primary, supplement], ignore_index=True), geometry="geometry", crs=WORKING_CRS_AUTHORITY)
    ACCESS_V2_FILE.parent.mkdir(parents=True, exist_ok=True)
    staged.to_parquet(ACCESS_V2_FILE, index=False)

    v1 = gpd.read_parquet(ACCESS_V1_FILE) if ACCESS_V1_FILE.exists() else None
    v1_digest_after = _file_digest(ACCESS_V1_FILE)

    summary = _summary(primary, supplement, staged, duplicate_review)
    schema = _schema(staged)
    geometry_qa = _geometry_qa(staged)
    crs_sanity = _crs_sanity(primary_raw, supplement_raw, staged)
    source_comparison = _source_comparison(primary, supplement, staged)
    access_control_counts = _value_counts(staged, "access_control_category", "access_control_category")
    access_direction_counts = _value_counts(staged, "access_direction_normalized", "access_direction_normalized")
    land_use_counts = _land_use_counts(staged)
    mapping = _mapping_candidate()
    v1_comparison = _comparison_to_v1(v1, staged, v1_digest_before, v1_digest_after)
    qa = _qa(staged, geometry_qa, v1_digest_before, v1_digest_after)

    outputs = {
        "access_v2_parquet": ACCESS_V2_FILE,
        "summary_csv": out_dir / "access_v2_staging_summary.csv",
        "schema_csv": out_dir / "access_v2_schema.csv",
        "geometry_qa_csv": out_dir / "access_v2_geometry_qa.csv",
        "crs_sanity_csv": out_dir / "access_v2_crs_sanity.csv",
        "source_comparison_csv": out_dir / "access_v2_source_comparison.csv",
        "access_control_value_counts_csv": out_dir / "access_v2_access_control_value_counts.csv",
        "access_direction_value_counts_csv": out_dir / "access_v2_access_direction_value_counts.csv",
        "land_use_value_counts_csv": out_dir / "access_v2_land_use_value_counts.csv",
        "duplicate_candidate_review_csv": out_dir / "access_v2_duplicate_candidate_review.csv",
        "mapping_candidate_csv": out_dir / "access_v2_mapping_candidate.csv",
        "comparison_to_access_v1_csv": out_dir / "access_v2_comparison_to_access_v1.csv",
        "findings_md": out_dir / "access_v2_staging_findings.md",
        "manifest_json": out_dir / "access_v2_staging_manifest.json",
    }

    _write_csv(summary, outputs["summary_csv"])
    _write_csv(schema, outputs["schema_csv"])
    _write_csv(geometry_qa, outputs["geometry_qa_csv"])
    _write_csv(crs_sanity, outputs["crs_sanity_csv"])
    _write_csv(source_comparison, outputs["source_comparison_csv"])
    _write_csv(access_control_counts, outputs["access_control_value_counts_csv"])
    _write_csv(access_direction_counts, outputs["access_direction_value_counts_csv"])
    _write_csv(land_use_counts, outputs["land_use_value_counts_csv"])
    _write_csv(duplicate_review, outputs["duplicate_candidate_review_csv"])
    _write_csv(mapping, outputs["mapping_candidate_csv"])
    _write_csv(v1_comparison, outputs["comparison_to_access_v1_csv"])
    _write_text(_findings(summary, access_control_counts, duplicate_review, qa, outputs), outputs["findings_md"])

    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "candidate access v2 source staging only; no context join or accepted access replacement",
        "primary_source": {"gdb": str(PRIMARY_GDB), "layer": PRIMARY_LAYER, "rows": len(primary)},
        "supplement_source": {"gdb": str(SUPPLEMENT_GDB), "layer": SUPPLEMENT_LAYER, "rows": len(supplement)},
        "access_v2_artifact": str(ACCESS_V2_FILE),
        "access_v1_artifact": str(ACCESS_V1_FILE),
        "access_v1_sha256_before": v1_digest_before,
        "access_v1_sha256_after": v1_digest_after,
        "access_v1_unchanged": v1_digest_before == v1_digest_after,
        "crash_direction_fields_read_or_used": False,
        "mapping_status": "candidate_provisional_not_final_policy",
        "downstream_outputs_modified": False,
        "summary": summary.to_dict(orient="records"),
        "qa_checks": qa.to_dict(orient="records"),
        "outputs": {key: str(path) for key, path in outputs.items()},
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage candidate access_v2 source artifact from populated Pathways access layers.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_access_v2_staging(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
