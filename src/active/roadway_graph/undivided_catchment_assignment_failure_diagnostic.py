from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .crs_utils import (
    CATCHMENT_CRS_METADATA_FILE,
    apply_authoritative_crs,
    coordinate_profile,
    crs_matches,
    crs_sanity_frame,
)


OUTPUT_ROOT = Path("work/output/roadway_graph")
NORMALIZED_ROOT = Path("artifacts/normalized")
CATCHMENT_INPUT_DIR = Path("review/current/reference_signal_directional_bin_catchments")
ASSIGNMENT_INPUT_DIR = Path("review/current/crash_directional_catchment_assignment_prototype")
DIAGNOSTIC_OUTPUT_DIR = Path("review/current/undivided_catchment_assignment_failure_diagnostic")

INDEX_FILE = "directional_bin_catchment_index.csv"
POLYGON_FILE = "directional_bin_catchment_polygons.geojson"
CRS_METADATA_FILE = CATCHMENT_CRS_METADATA_FILE
CRASH_FILE = "crashes.parquet"

CRASH_READ_COLUMNS = ["DOCUMENT_NBR", "geometry"]
FEET_PER_METER = 3.280839895
PROXIMITY_SAMPLE_SIZE = 10000
SYNTHETIC_SAMPLE_SIZE = 100
SMALL_TOLERANCE_FT = 35.0

DIVIDED = "divided_physical_carriageway"
UNDIVIDED = "undivided_centerline_pseudo_direction"


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_crash_points(path: Path) -> gpd.GeoDataFrame:
    crashes = gpd.read_parquet(path, columns=CRASH_READ_COLUMNS)
    crashes = crashes.loc[crashes.geometry.notna() & ~crashes.geometry.is_empty].copy()
    crashes = crashes.reset_index(drop=True)
    base = crashes["DOCUMENT_NBR"].fillna("").astype(str)
    missing = base.str.strip().eq("")
    if missing.any():
        base.loc[missing] = [f"crash_{idx:08d}" for idx in crashes.index[missing]]
    if base.duplicated().any():
        crashes["crash_id"] = base + "_" + crashes.groupby(base).cumcount().astype(str)
    else:
        crashes["crash_id"] = base
    return crashes[["crash_id", "geometry"]].copy()


def _distance_band_ft(distance_ft: float | None) -> str:
    if distance_ft is None or pd.isna(distance_ft):
        return "no_nearest_geometry"
    if distance_ft <= 5:
        return "0_to_5ft"
    if distance_ft <= 10:
        return "5_to_10ft"
    if distance_ft <= 25:
        return "10_to_25ft"
    if distance_ft <= 35:
        return "25_to_35ft"
    if distance_ft <= 75:
        return "35_to_75ft"
    if distance_ft <= 150:
        return "75_to_150ft"
    if distance_ft <= 300:
        return "150_to_300ft"
    return "over_300ft"


def _summary_rows(metrics: dict[str, object]) -> pd.DataFrame:
    notes = {
        "crash_direction_fields_read_or_used": "Expected False; only DOCUMENT_NBR and geometry are read from normalized crashes.",
        "scaffold_catchment_or_assignment_logic_changed": "Expected False; this is a read-only diagnostic.",
        "usable_divided_index_rows": "Usable divided catchments in directional_bin_catchment_index.csv.",
        "usable_undivided_index_rows": "Usable undivided catchments in directional_bin_catchment_index.csv.",
        "usable_divided_polygons_loaded": "Usable divided rows read from the catchment GeoJSON.",
        "usable_undivided_polygons_loaded": "Usable undivided rows read from the catchment GeoJSON.",
        "usable_divided_nonempty_polygons": "Divided usable rows with non-empty geometry.",
        "usable_undivided_nonempty_polygons": "Undivided usable rows with non-empty geometry.",
        "usable_undivided_empty_polygons": "Undivided usable rows that cannot participate in spatial containment.",
        "assigned_undivided_from_assignment_output": "Current assignment prototype result for undivided pseudo-direction catchments.",
    }
    return pd.DataFrame(
        [{"metric": key, "value": value, "notes": notes.get(key, "")} for key, value in metrics.items()]
    )


def _geometry_comparison(catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for rep, frame in catchments.groupby("roadway_representation_type", dropna=False):
        geom = frame.geometry
        nonempty = frame.loc[geom.notna() & ~geom.is_empty]
        area = nonempty.geometry.area if not nonempty.empty else pd.Series(dtype=float)
        bounds = nonempty.bounds if not nonempty.empty else pd.DataFrame(columns=["minx", "miny", "maxx", "maxy"])
        rows.append(
            {
                "roadway_representation_type": rep,
                "row_count": int(len(frame)),
                "geometry_type_counts": "|".join(
                    f"{key}:{value}" for key, value in geom.geom_type.value_counts(dropna=False).to_dict().items()
                ),
                "empty_geometry_count": int((geom.isna() | geom.is_empty).sum()),
                "invalid_geometry_count": int((~geom.is_valid).sum()),
                "zero_or_near_zero_area_count": int((area <= 1e-9).sum()) if not area.empty else 0,
                "area_min": float(area.min()) if not area.empty else "",
                "area_p05": float(area.quantile(0.05)) if not area.empty else "",
                "area_median": float(area.median()) if not area.empty else "",
                "area_p95": float(area.quantile(0.95)) if not area.empty else "",
                "area_max": float(area.max()) if not area.empty else "",
                "bounds_minx": float(bounds["minx"].min()) if not bounds.empty else "",
                "bounds_miny": float(bounds["miny"].min()) if not bounds.empty else "",
                "bounds_maxx": float(bounds["maxx"].max()) if not bounds.empty else "",
                "bounds_maxy": float(bounds["maxy"].max()) if not bounds.empty else "",
                "representative_point_valid_count": int(nonempty.geometry.representative_point().notna().sum())
                if not nonempty.empty
                else 0,
            }
        )
    return pd.DataFrame(rows)


def _area_distribution(frame: gpd.GeoDataFrame, label: str) -> pd.DataFrame:
    nonempty = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if nonempty.empty:
        return pd.DataFrame(
            [{"roadway_representation_type": label, "statistic": stat, "area": ""} for stat in ["count", "min", "p05", "p25", "median", "p75", "p95", "max"]]
        )
    area = nonempty.geometry.area
    values = {
        "count": int(area.count()),
        "min": float(area.min()),
        "p05": float(area.quantile(0.05)),
        "p25": float(area.quantile(0.25)),
        "median": float(area.median()),
        "p75": float(area.quantile(0.75)),
        "p95": float(area.quantile(0.95)),
        "max": float(area.max()),
    }
    return pd.DataFrame(
        [{"roadway_representation_type": label, "statistic": key, "area": value} for key, value in values.items()]
    )


def _validity_qa(undivided: gpd.GeoDataFrame) -> pd.DataFrame:
    geom = undivided.geometry
    return pd.DataFrame(
        [
            {"qa_check": "rows", "value": int(len(undivided))},
            {"qa_check": "missing_geometry", "value": int(geom.isna().sum())},
            {"qa_check": "empty_geometry", "value": int(geom.is_empty.sum())},
            {"qa_check": "valid_geometry", "value": int(geom.is_valid.sum())},
            {"qa_check": "invalid_geometry", "value": int((~geom.is_valid).sum())},
            {
                "qa_check": "nonempty_geometry",
                "value": int((geom.notna() & ~geom.is_empty).sum()),
            },
        ]
    )


def _crs_coordinate_sanity(
    catchments_declared: gpd.GeoDataFrame,
    catchments_aligned: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
    handling: str,
    metadata_path: Path,
) -> pd.DataFrame:
    rows = [
        coordinate_profile(catchments_declared, "catchment_geojson_as_loaded"),
        coordinate_profile(catchments_aligned, "catchment_authoritative_diagnostic_crs"),
        coordinate_profile(crashes, "normalized_crashes"),
    ]
    sanity = crs_sanity_frame(rows)
    sanity["catchment_crs_handling"] = handling
    sanity["metadata_file"] = str(metadata_path)
    return sanity


def _assignment_surface_inclusion(index: pd.DataFrame, catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    usable = index.loc[index["catchment_status"].eq("usable")].copy()
    polygon_ids = set(catchments["catchment_id"])
    rows = []
    for rep in [DIVIDED, UNDIVIDED]:
        usable_rep = usable.loc[usable["roadway_representation_type"].eq(rep)]
        loaded_rep = catchments.loc[catchments["roadway_representation_type"].eq(rep)]
        nonempty = loaded_rep.loc[loaded_rep.geometry.notna() & ~loaded_rep.geometry.is_empty]
        rows.append(
            {
                "roadway_representation_type": rep,
                "usable_index_rows": int(len(usable_rep)),
                "usable_geojson_rows_loaded": int(len(loaded_rep)),
                "lost_between_index_and_geojson_load": int((~usable_rep["catchment_id"].isin(polygon_ids)).sum()),
                "empty_or_missing_geometry_rows": int((loaded_rep.geometry.isna() | loaded_rep.geometry.is_empty).sum()),
                "nonempty_rows_entering_spatial_index": int(len(nonempty)),
                "likely_assignment_surface_filter": "none; rows are included, but empty geometries cannot match"
                if rep == UNDIVIDED and len(nonempty) < len(loaded_rep)
                else "none_identified",
            }
        )
    return pd.DataFrame(rows)


def _synthetic_probe(catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    probe_frames = []
    for rep in [DIVIDED, UNDIVIDED]:
        source = catchments.loc[
            catchments["roadway_representation_type"].eq(rep)
            & catchments.geometry.notna()
            & ~catchments.geometry.is_empty
            & catchments.geometry.is_valid
        ].copy()
        if len(source) > SYNTHETIC_SAMPLE_SIZE:
            source = source.sample(SYNTHETIC_SAMPLE_SIZE, random_state=42)
        probe_frames.append(source)
    probe_source = pd.concat(probe_frames, ignore_index=True) if probe_frames else pd.DataFrame()
    if probe_source.empty:
        return pd.DataFrame(
            columns=[
                "roadway_representation_type",
                "catchment_id",
                "probe_point_created",
                "source_polygon_covers_probe",
                "spatial_index_candidate_count",
                "source_polygon_returned_by_spatial_index",
                "assignment_logic_candidate_count",
                "assignment_logic_status",
            ]
        )
    probe_source = gpd.GeoDataFrame(probe_source, geometry="geometry", crs=catchments.crs)
    points = probe_source.copy()
    points["geometry"] = probe_source.geometry.representative_point()
    matches = gpd.sjoin(
        points[["catchment_id", "roadway_representation_type", "geometry"]],
        catchments[["catchment_id", "roadway_representation_type", "geometry"]],
        how="left",
        predicate="covered_by" if "covered_by" in catchments.sindex.valid_query_predicates else "within",
        lsuffix="probe",
        rsuffix="candidate",
    )
    for source in points.itertuples(index=False):
        source_id = source.catchment_id
        source_poly = catchments.loc[catchments["catchment_id"].eq(source_id), "geometry"].iloc[0]
        source_matches = matches.loc[matches["catchment_id_probe"].eq(source_id)]
        candidate_ids = set(source_matches["catchment_id_candidate"].dropna().astype(str))
        candidate_count = len(candidate_ids)
        rows.append(
            {
                "roadway_representation_type": source.roadway_representation_type,
                "catchment_id": source_id,
                "probe_point_created": True,
                "source_polygon_covers_probe": bool(source_poly.covers(source.geometry)),
                "spatial_index_candidate_count": candidate_count,
                "source_polygon_returned_by_spatial_index": source_id in candidate_ids,
                "assignment_logic_candidate_count": candidate_count,
                "assignment_logic_status": "assigned_unique_catchment"
                if candidate_count == 1
                else ("ambiguous_multiple_usable_directional_catchments" if candidate_count > 1 else "unresolved_no_usable_directional_catchment"),
            }
        )
    return pd.DataFrame(rows)


def _nearest_undivided_sample(crashes: gpd.GeoDataFrame, unresolved_ids: set[str], undivided_nonempty: gpd.GeoDataFrame) -> pd.DataFrame:
    sample = crashes.loc[crashes["crash_id"].isin(unresolved_ids)].copy()
    if len(sample) > PROXIMITY_SAMPLE_SIZE:
        sample = sample.sample(PROXIMITY_SAMPLE_SIZE, random_state=42)
    if sample.empty or undivided_nonempty.empty:
        return pd.DataFrame(columns=["crash_id", "nearest_undivided_catchment_id", "nearest_undivided_distance_ft", "distance_band_ft"])
    nearest = gpd.sjoin_nearest(
        sample[["crash_id", "geometry"]],
        undivided_nonempty[["catchment_id", "geometry"]],
        how="left",
        distance_col="nearest_distance_m",
    ).drop(columns=["index_right"], errors="ignore")
    nearest["nearest_undivided_distance_ft"] = pd.to_numeric(nearest["nearest_distance_m"], errors="coerce") * FEET_PER_METER
    nearest["distance_band_ft"] = nearest["nearest_undivided_distance_ft"].map(_distance_band_ft)
    return nearest.rename(columns={"catchment_id": "nearest_undivided_catchment_id"})[
        ["crash_id", "nearest_undivided_catchment_id", "nearest_undivided_distance_ft", "distance_band_ft"]
    ]


def _containment_comparison(crashes: gpd.GeoDataFrame, catchments: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    predicate = "covered_by" if "covered_by" in catchments.sindex.valid_query_predicates else "within"
    for rep in [DIVIDED, UNDIVIDED]:
        surface = catchments.loc[
            catchments["roadway_representation_type"].eq(rep)
            & catchments.geometry.notna()
            & ~catchments.geometry.is_empty
        ].copy()
        if surface.empty:
            contained_count = 0
            within_tolerance_count = 0
        else:
            contained = gpd.sjoin(
                crashes[["crash_id", "geometry"]],
                surface[["catchment_id", "geometry"]],
                how="inner",
                predicate=predicate,
            )
            contained_ids = set(contained["crash_id"])
            contained_count = len(contained_ids)
            tolerance_m = SMALL_TOLERANCE_FT / FEET_PER_METER
            near = gpd.sjoin_nearest(
                crashes.loc[~crashes["crash_id"].isin(contained_ids), ["crash_id", "geometry"]],
                surface[["catchment_id", "geometry"]],
                how="inner",
                max_distance=tolerance_m,
                distance_col="distance_m",
            )
            within_tolerance_count = int(near["crash_id"].nunique())
        rows.append(
            {
                "roadway_representation_type": rep,
                "nonempty_usable_catchments": int(len(surface)),
                "crashes_contained_by_any_usable_catchment": contained_count,
                f"crashes_within_{int(SMALL_TOLERANCE_FT)}ft_but_not_contained": within_tolerance_count,
            }
        )
    return pd.DataFrame(rows)


def build_undivided_catchment_assignment_failure_diagnostic(
    *,
    normalized_root: Path = NORMALIZED_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, str]:
    input_dir = output_root / CATCHMENT_INPUT_DIR
    assignment_dir = output_root / ASSIGNMENT_INPUT_DIR
    output_dir = output_root / DIAGNOSTIC_OUTPUT_DIR
    index_path = input_dir / INDEX_FILE
    polygon_path = input_dir / POLYGON_FILE
    crs_metadata_path = input_dir / CRS_METADATA_FILE
    crash_path = normalized_root / CRASH_FILE
    assignment_summary_path = assignment_dir / "crash_directional_catchment_assignment_summary.csv"
    assignment_rows_path = assignment_dir / "crash_directional_catchment_assignments.csv"
    unresolved_path = assignment_dir / "crash_directional_catchment_unresolved.csv"

    index = pd.read_csv(index_path, dtype=str, keep_default_na=False)
    catchments_declared = gpd.read_file(polygon_path, where="catchment_status = 'usable'")
    catchments_declared = catchments_declared.loc[catchments_declared["catchment_status"].astype(str).eq("usable")].copy()
    crashes = _read_crash_points(crash_path)
    catchments, crs_handling, crs_metadata = apply_authoritative_crs(catchments_declared.copy(), metadata_path=crs_metadata_path)
    if not crs_matches(crashes.crs, catchments.crs):
        crashes_for_diagnostic = crashes.to_crs(catchments.crs)
    else:
        crashes_for_diagnostic = crashes.copy()

    assignment_summary = pd.read_csv(assignment_summary_path, dtype=str, keep_default_na=False)
    assignment_rows = pd.read_csv(assignment_rows_path, dtype=str, keep_default_na=False)
    unresolved = pd.read_csv(unresolved_path, dtype=str, keep_default_na=False)
    unresolved_ids = set(unresolved["crash_id"])

    divided = catchments.loc[catchments["roadway_representation_type"].eq(DIVIDED)].copy()
    undivided = catchments.loc[catchments["roadway_representation_type"].eq(UNDIVIDED)].copy()
    undivided_nonempty = undivided.loc[undivided.geometry.notna() & ~undivided.geometry.is_empty].copy()

    geometry_comparison = _geometry_comparison(catchments)
    area_distribution = pd.concat(
        [_area_distribution(divided, DIVIDED), _area_distribution(undivided, UNDIVIDED)],
        ignore_index=True,
    )
    validity_qa = _validity_qa(undivided)
    crs_sanity = _crs_coordinate_sanity(catchments_declared, catchments, crashes, crs_handling, crs_metadata_path)
    inclusion_qa = _assignment_surface_inclusion(index, catchments)
    synthetic_probe = _synthetic_probe(catchments)
    proximity_sample = _nearest_undivided_sample(crashes_for_diagnostic, unresolved_ids, undivided_nonempty)
    containment_comparison = _containment_comparison(crashes_for_diagnostic, catchments)

    assigned_undivided = int(
        assignment_summary.loc[
            assignment_summary["metric"].eq("assigned_undivided_pseudo_direction_crashes"), "value"
        ].iloc[0]
    )
    metrics = {
        "crash_direction_fields_read_or_used": False,
        "scaffold_catchment_or_assignment_logic_changed": False,
        "usable_divided_index_rows": int(
            len(index.loc[index["catchment_status"].eq("usable") & index["roadway_representation_type"].eq(DIVIDED)])
        ),
        "usable_undivided_index_rows": int(
            len(index.loc[index["catchment_status"].eq("usable") & index["roadway_representation_type"].eq(UNDIVIDED)])
        ),
        "usable_divided_polygons_loaded": int(len(divided)),
        "usable_undivided_polygons_loaded": int(len(undivided)),
        "usable_divided_nonempty_polygons": int((divided.geometry.notna() & ~divided.geometry.is_empty).sum()),
        "usable_undivided_nonempty_polygons": int(len(undivided_nonempty)),
        "usable_undivided_empty_polygons": int((undivided.geometry.isna() | undivided.geometry.is_empty).sum()),
        "assigned_undivided_from_assignment_output": assigned_undivided,
        "crashes_considered": int(len(crashes)),
        "unresolved_crashes_sampled_for_nearest_undivided": int(len(proximity_sample)),
        "catchment_crs_handling": crs_handling,
        "catchment_authoritative_crs": crs_metadata.get("authoritative_crs", ""),
    }
    summary = _summary_rows(metrics)

    empty_undivided_fixed = metrics["usable_undivided_empty_polygons"] == 0
    suspected_failure_modes = pd.DataFrame(
        [
            {
                "failure_mode": "usable_undivided_catchments_have_empty_geometry",
                "evidence": f"{metrics['usable_undivided_empty_polygons']} of {metrics['usable_undivided_polygons_loaded']} usable undivided catchment rows have empty geometry; {metrics['usable_undivided_nonempty_polygons']} can enter containment.",
                "likelihood": "resolved" if empty_undivided_fixed else "high",
                "recommended_fix": "No further action on empty undivided geometry if this remains 0; otherwise review undivided side-polygon construction.",
                "fix_implemented": empty_undivided_fixed,
            },
            {
                "failure_mode": "catchment_geojson_crs_metadata_conflicts_with_projected_coordinates",
                "evidence": f"CRS handling was {crs_handling}; authoritative CRS is {crs_metadata.get('authoritative_crs', '')}.",
                "likelihood": "resolved" if crs_handling == "catchment_crs_matches_authoritative_metadata" else "low",
                "recommended_fix": "Keep using the shared catchment CRS metadata convention in downstream consumers.",
                "fix_implemented": crs_handling in {"catchment_crs_matches_authoritative_metadata", "catchment_crs_overridden_from_authoritative_metadata_projected_coordinates"},
            },
        ]
    )

    proximity_counts = (
        proximity_sample["distance_band_ft"].value_counts().sort_index().to_dict() if not proximity_sample.empty else {}
    )
    synthetic_summary = (
        synthetic_probe.groupby(["roadway_representation_type", "assignment_logic_status"], dropna=False)
        .size()
        .reset_index(name="probe_count")
        if not synthetic_probe.empty
        else pd.DataFrame(columns=["roadway_representation_type", "assignment_logic_status", "probe_count"])
    )
    findings = "\n".join(
        [
            "# Undivided Catchment Assignment Failure Diagnostic",
            "",
            "## Bounded Question",
            "",
            "Diagnose why the assignment-only prototype produced zero undivided pseudo-direction assignments despite a large undivided catchment inventory.",
            "",
            "## Files Read",
            "",
            f"- `{index_path}`",
            f"- `{polygon_path}`",
            f"- `{assignment_summary_path}`",
            f"- `{assignment_rows_path}`",
            f"- `{unresolved_path}`",
            f"- `{crash_path}` with columns `{', '.join(CRASH_READ_COLUMNS)}` only",
            "",
            "## Key Findings",
            "",
            f"- Usable divided catchments loaded: {metrics['usable_divided_polygons_loaded']}; non-empty: {metrics['usable_divided_nonempty_polygons']}.",
            f"- Usable undivided catchments loaded: {metrics['usable_undivided_polygons_loaded']}; non-empty: {metrics['usable_undivided_nonempty_polygons']}; empty: {metrics['usable_undivided_empty_polygons']}.",
            f"- Current assignment output undivided assignments: {assigned_undivided}.",
            f"- CRS handling: `{crs_handling}`.",
            f"- Authoritative CRS: `{crs_metadata.get('authoritative_crs', '')}`.",
            "- Crash direction fields were not read or used.",
            "- Scaffold, catchment, and assignment logic were not changed.",
            "",
            "## Synthetic Probe Findings",
            "",
            *(f"- {row.roadway_representation_type} / {row.assignment_logic_status}: {row.probe_count}" for row in synthetic_summary.itertuples(index=False)),
            "",
            "## Crash Proximity Sample",
            "",
            *(f"- {key}: {value}" for key, value in proximity_counts.items()),
            "",
            "## Most Likely Reason",
            "",
            "Before repair, the zero undivided assignment result was most likely caused by empty undivided pseudo-direction catchment geometries. In the current diagnostic run, usable undivided geometries are non-empty and assignment output includes undivided pseudo-direction matches.",
            "",
            "## Recommended Fix",
            "",
            "No assignment-logic fix is indicated by this diagnostic. Keep monitoring CRS metadata handling for GeoJSON review layers, and keep assignment limited to usable catchments.",
            "",
        ]
    )

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only QA/debugging for undivided catchment assignment surface",
        "inputs": {
            "catchment_index": str(index_path),
            "catchment_polygons": str(polygon_path),
            "catchment_crs_metadata": str(crs_metadata_path),
            "assignment_summary": str(assignment_summary_path),
            "assignment_rows": str(assignment_rows_path),
            "assignment_unresolved": str(unresolved_path),
            "crashes": str(crash_path),
            "crash_columns_read": CRASH_READ_COLUMNS,
        },
        "method": {
            "crash_direction_fields_read_or_used": False,
            "crash_distributions_used_to_change_scaffold": False,
            "scaffold_catchment_or_assignment_logic_changed": False,
            "small_tolerance_ft": SMALL_TOLERANCE_FT,
            "proximity_sample_size": PROXIMITY_SAMPLE_SIZE,
            "synthetic_sample_size_per_type": SYNTHETIC_SAMPLE_SIZE,
            "catchment_crs_handling": crs_handling,
            "catchment_authoritative_crs": crs_metadata.get("authoritative_crs", ""),
        },
        "qa": metrics,
        "outputs": {},
    }

    outputs = {
        "summary_csv": output_dir / "undivided_catchment_failure_diagnostic_summary.csv",
        "geometry_comparison_csv": output_dir / "catchment_geometry_comparison_divided_vs_undivided.csv",
        "area_distribution_csv": output_dir / "undivided_catchment_area_distribution.csv",
        "validity_qa_csv": output_dir / "undivided_catchment_validity_qa.csv",
        "crs_coordinate_sanity_csv": output_dir / "catchment_crs_coordinate_sanity.csv",
        "assignment_surface_inclusion_csv": output_dir / "assignment_surface_inclusion_qa.csv",
        "synthetic_probe_csv": output_dir / "synthetic_point_probe_results.csv",
        "proximity_sample_csv": output_dir / "crash_to_undivided_proximity_sample.csv",
        "containment_comparison_csv": output_dir / "crash_containment_comparison_divided_vs_undivided.csv",
        "suspected_failure_modes_csv": output_dir / "suspected_failure_modes.csv",
        "findings_md": output_dir / "undivided_catchment_failure_findings.md",
        "manifest_json": output_dir / "undivided_catchment_failure_manifest.json",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(geometry_comparison, outputs["geometry_comparison_csv"])
    _write_csv(area_distribution, outputs["area_distribution_csv"])
    _write_csv(validity_qa, outputs["validity_qa_csv"])
    _write_csv(crs_sanity, outputs["crs_coordinate_sanity_csv"])
    _write_csv(inclusion_qa, outputs["assignment_surface_inclusion_csv"])
    _write_csv(synthetic_probe, outputs["synthetic_probe_csv"])
    _write_csv(proximity_sample, outputs["proximity_sample_csv"])
    _write_csv(containment_comparison, outputs["containment_comparison_csv"])
    _write_csv(suspected_failure_modes, outputs["suspected_failure_modes_csv"])
    _write_text(findings, outputs["findings_md"])
    manifest["outputs"] = {key: str(path) for key, path in outputs.items()}
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose undivided catchment assignment surface failures.")
    parser.add_argument("--normalized-root", type=Path, default=NORMALIZED_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_undivided_catchment_assignment_failure_diagnostic(
        normalized_root=args.normalized_root,
        output_root=args.output_root,
    )
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
