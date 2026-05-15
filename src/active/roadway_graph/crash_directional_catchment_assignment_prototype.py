from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

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
ASSIGNMENT_OUTPUT_DIR = Path("review/current/crash_directional_catchment_assignment_prototype")

INDEX_FILE = "directional_bin_catchment_index.csv"
POLYGON_FILE = "directional_bin_catchment_polygons.geojson"
CRASH_FILE = "crashes.parquet"

ASSIGNMENT_METHOD = "point_in_usable_directional_catchment"
ASSIGNED_STATUS = "assigned_unique_catchment"
AMBIGUOUS_STATUS = "ambiguous_multiple_usable_directional_catchments"
UNRESOLVED_REASON = "no_usable_directional_catchment_contains_point"

CRASH_READ_COLUMNS = ["DOCUMENT_NBR", "geometry"]

ASSIGNED_COLUMNS = [
    "crash_id",
    "reference_signal_id",
    "far_anchor_id",
    "reference_directional_segment_id",
    "reference_directional_bin_id",
    "catchment_id",
    "signal_relative_direction",
    "bin_index_from_reference_signal",
    "bin_start_ft_from_reference_signal",
    "bin_end_ft_from_reference_signal",
    "roadway_representation_type",
    "travel_direction",
    "catchment_method",
    "assignment_method",
    "assignment_status",
    "assignment_confidence",
    "inherited_direction_from_catchment",
]

AMBIGUOUS_COLUMNS = [
    "crash_id",
    "candidate_catchment_count",
    "candidate_reference_signal_count",
    "candidate_directional_segment_count",
    "candidate_bin_count",
    "candidate_signal_relative_directions",
    "ambiguity_reason",
    "candidate_catchment_ids",
]

UNRESOLVED_COLUMNS = ["crash_id", "unresolved_reason"]


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_catchment_index(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_usable_catchment_polygons(path: Path) -> gpd.GeoDataFrame:
    try:
        catchments = gpd.read_file(path, where="catchment_status = 'usable'")
    except Exception:
        catchments = gpd.read_file(path)
    if "catchment_status" not in catchments.columns:
        raise ValueError(f"Missing catchment_status field in {path}")
    catchments = catchments.loc[catchments["catchment_status"].astype(str).eq("usable")].copy()
    return catchments


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


def _crs_coordinate_sanity(
    catchments_declared: gpd.GeoDataFrame,
    catchments_aligned: gpd.GeoDataFrame,
    crashes: gpd.GeoDataFrame,
    handling: str,
    metadata_path: Path,
) -> pd.DataFrame:
    rows = [
        coordinate_profile(catchments_declared, "catchment_geojson_as_loaded"),
        coordinate_profile(catchments_aligned, "catchment_authoritative_assignment_crs"),
        coordinate_profile(crashes, "normalized_crashes"),
    ]
    sanity = crs_sanity_frame(rows)
    sanity["catchment_crs_handling"] = handling
    sanity["metadata_file"] = str(metadata_path)
    return sanity


def _join_values(values: Iterable[object]) -> str:
    unique = sorted({str(value) for value in values if str(value) != ""})
    return "|".join(unique)


def _group_count(frame: pd.DataFrame, columns: list[str], count_name: str = "crash_count") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*columns, count_name])
    return frame.groupby(columns, dropna=False).size().reset_index(name=count_name).sort_values(count_name, ascending=False)


def _summary_rows(metrics: dict[str, object]) -> pd.DataFrame:
    notes = {
        "catchment_index_rows": "Rows in directional_bin_catchment_index.csv.",
        "catchment_index_usable_rows": "Rows with catchment_status = usable in the catchment index.",
        "usable_polygon_rows_loaded": "Usable polygon rows loaded into the assignable surface.",
        "unstable_or_blocked_polygon_rows_used": "Expected 0; unstable_review and blocked catchments are excluded.",
        "crash_direction_fields_read_or_used": "Expected False; only DOCUMENT_NBR and geometry are read from crashes.",
        "scaffold_or_catchment_construction_changed": "Expected False; this module only reads existing scaffold/catchment outputs.",
        "total_crashes_considered": "Normalized crash rows with usable point geometry.",
        "uniquely_assigned_crashes": "Crash points contained by exactly one usable directional catchment.",
        "ambiguous_crashes": "Crash points contained by more than one usable directional catchment.",
        "unresolved_crashes": "Crash points contained by no usable directional catchment.",
        "assigned_downstream_crashes": "Unique assignments inheriting downstream_of_reference_signal from the catchment.",
        "assigned_upstream_crashes": "Unique assignments inheriting upstream_of_reference_signal from the catchment.",
        "assigned_divided_physical_crashes": "Unique assignments to divided_physical_carriageway catchments.",
        "assigned_undivided_pseudo_direction_crashes": "Unique assignments to undivided_centerline_pseudo_direction catchments.",
    }
    return pd.DataFrame(
        [{"metric": key, "value": value, "notes": notes.get(key, "")} for key, value in metrics.items()]
    )


def build_crash_directional_catchment_assignment(
    *,
    normalized_root: Path = NORMALIZED_ROOT,
    output_root: Path = OUTPUT_ROOT,
) -> dict[str, str]:
    input_dir = output_root / CATCHMENT_INPUT_DIR
    output_dir = output_root / ASSIGNMENT_OUTPUT_DIR
    index_path = input_dir / INDEX_FILE
    polygon_path = input_dir / POLYGON_FILE
    crs_metadata_path = input_dir / CATCHMENT_CRS_METADATA_FILE
    crash_path = normalized_root / CRASH_FILE

    catchment_index = _read_catchment_index(index_path)
    if "catchment_status" not in catchment_index.columns:
        raise ValueError(f"Missing catchment_status field in {index_path}")
    index_status_counts = catchment_index["catchment_status"].value_counts(dropna=False).to_dict()
    usable_index_ids = set(catchment_index.loc[catchment_index["catchment_status"].eq("usable"), "catchment_id"])

    crashes = _read_crash_points(crash_path)
    catchments_declared = _read_usable_catchment_polygons(polygon_path)
    catchments = catchments_declared.loc[catchments_declared["catchment_id"].isin(usable_index_ids)].copy()
    catchments, catchment_crs_handling, crs_metadata = apply_authoritative_crs(catchments, metadata_path=crs_metadata_path)
    crs_sanity = _crs_coordinate_sanity(catchments_declared, catchments, crashes, catchment_crs_handling, crs_metadata_path)
    nonusable_loaded = int(catchments["catchment_status"].astype(str).ne("usable").sum())
    if catchments.empty:
        raise ValueError("No usable catchment polygons were available for assignment.")

    if not crs_matches(crashes.crs, catchments.crs):
        crashes_for_join = crashes.to_crs(catchments.crs)
    else:
        crashes_for_join = crashes.copy()

    catchment_columns = [column for column in ASSIGNED_COLUMNS if column in catchments.columns]
    join_columns = sorted(set(catchment_columns + ["geometry"]))
    predicate = "covered_by" if "covered_by" in catchments.sindex.valid_query_predicates else "within"
    matches = gpd.sjoin(
        crashes_for_join[["crash_id", "geometry"]],
        catchments[join_columns],
        how="inner",
        predicate=predicate,
    ).drop(columns=["index_right", "geometry"], errors="ignore")

    if matches.empty:
        candidate_counts = pd.Series(dtype=int)
    else:
        candidate_counts = matches.groupby("crash_id")["catchment_id"].count()
    unique_ids = set(candidate_counts.loc[candidate_counts.eq(1)].index)
    ambiguous_ids = set(candidate_counts.loc[candidate_counts.gt(1)].index)
    all_crash_ids = set(crashes["crash_id"])
    unresolved_ids = all_crash_ids - unique_ids - ambiguous_ids

    assigned = matches.loc[matches["crash_id"].isin(unique_ids)].copy()
    assigned["assignment_method"] = ASSIGNMENT_METHOD
    assigned["assignment_status"] = ASSIGNED_STATUS
    assigned["assignment_confidence"] = "high"
    assigned["inherited_direction_from_catchment"] = True
    assigned = assigned[[column for column in ASSIGNED_COLUMNS if column in assigned.columns]].sort_values("crash_id")

    ambiguous_source = matches.loc[matches["crash_id"].isin(ambiguous_ids)].copy()
    if ambiguous_source.empty:
        ambiguous = pd.DataFrame(columns=AMBIGUOUS_COLUMNS)
    else:
        ambiguous = (
            ambiguous_source.groupby("crash_id", dropna=False)
            .agg(
                candidate_catchment_count=("catchment_id", "nunique"),
                candidate_reference_signal_count=("reference_signal_id", "nunique"),
                candidate_directional_segment_count=("reference_directional_segment_id", "nunique"),
                candidate_bin_count=("reference_directional_bin_id", "nunique"),
                candidate_signal_relative_directions=("signal_relative_direction", _join_values),
                candidate_catchment_ids=("catchment_id", _join_values),
            )
            .reset_index()
        )
        ambiguous["ambiguity_reason"] = AMBIGUOUS_STATUS
        ambiguous = ambiguous[AMBIGUOUS_COLUMNS].sort_values(
            ["candidate_catchment_count", "crash_id"], ascending=[False, True]
        )

    unresolved = pd.DataFrame({"crash_id": sorted(unresolved_ids)})
    unresolved["unresolved_reason"] = UNRESOLVED_REASON
    unresolved = unresolved[UNRESOLVED_COLUMNS]

    by_reference_signal = _group_count(assigned, ["reference_signal_id"])
    by_direction = _group_count(assigned, ["signal_relative_direction"])
    by_representation = _group_count(assigned, ["roadway_representation_type"])
    by_catchment_method = _group_count(assigned, ["catchment_method"])
    by_bin_index = _group_count(assigned, ["bin_index_from_reference_signal"])
    ambiguity_summary = _group_count(ambiguous, ["ambiguity_reason"], "crash_count")
    unresolved_summary = _group_count(unresolved, ["unresolved_reason"], "crash_count")

    direction_counts = assigned["signal_relative_direction"].value_counts(dropna=False).to_dict()
    representation_counts = assigned["roadway_representation_type"].value_counts(dropna=False).to_dict()
    metrics = {
        "catchment_index_rows": int(len(catchment_index)),
        "catchment_index_usable_rows": int(index_status_counts.get("usable", 0)),
        "usable_polygon_rows_loaded": int(len(catchments)),
        "unstable_or_blocked_polygon_rows_used": nonusable_loaded,
        "crash_direction_fields_read_or_used": False,
        "scaffold_or_catchment_construction_changed": False,
        "total_crashes_considered": int(len(crashes)),
        "uniquely_assigned_crashes": int(len(assigned)),
        "ambiguous_crashes": int(len(ambiguous)),
        "unresolved_crashes": int(len(unresolved)),
        "assigned_downstream_crashes": int(direction_counts.get("downstream_of_reference_signal", 0)),
        "assigned_upstream_crashes": int(direction_counts.get("upstream_of_reference_signal", 0)),
        "assigned_divided_physical_crashes": int(representation_counts.get("divided_physical_carriageway", 0)),
        "assigned_undivided_pseudo_direction_crashes": int(
            representation_counts.get("undivided_centerline_pseudo_direction", 0)
        ),
        "catchment_crs_handling": catchment_crs_handling,
        "catchment_authoritative_crs": crs_metadata.get("authoritative_crs", ""),
    }
    summary = _summary_rows(metrics)
    top_ambiguity_lines = (
        [f"- {row.ambiguity_reason}: {row.crash_count}" for row in ambiguity_summary.head(10).itertuples(index=False)]
        if not ambiguity_summary.empty
        else ["- none"]
    )
    top_unresolved_lines = (
        [f"- {row.unresolved_reason}: {row.crash_count}" for row in unresolved_summary.head(10).itertuples(index=False)]
        if not unresolved_summary.empty
        else ["- none"]
    )

    findings = "\n".join(
        [
            "# Crash Directional Catchment Assignment Prototype",
            "",
            "## Bounded Question",
            "",
            "Assign normalized crash points to the existing usable roadway-only directional catchment surface.",
            "This is assignment-only and is not final crash analysis.",
            "",
            "## Method",
            "",
            f"- Crash source read columns: {', '.join(CRASH_READ_COLUMNS)}.",
            "- Usable catchments only: `catchment_status = usable`.",
            f"- Spatial predicate: `{predicate}`.",
            f"- Catchment CRS handling: `{catchment_crs_handling}`.",
            "- Unique point-in-catchment matches inherit signal-relative direction from the catchment row.",
            "- Multiple usable containing catchments are ambiguous; no containing usable catchment is unresolved.",
            "- No nearest-bin assignment, crash direction fields, crash distributions, or crash-derived upstream/downstream logic were used.",
            "",
            "## Counts",
            "",
            f"- Total crashes considered: {metrics['total_crashes_considered']}",
            f"- Uniquely assigned crashes: {metrics['uniquely_assigned_crashes']}",
            f"- Ambiguous crashes: {metrics['ambiguous_crashes']}",
            f"- Unresolved crashes: {metrics['unresolved_crashes']}",
            f"- Assigned downstream crashes: {metrics['assigned_downstream_crashes']}",
            f"- Assigned upstream crashes: {metrics['assigned_upstream_crashes']}",
            f"- Assigned divided physical crashes: {metrics['assigned_divided_physical_crashes']}",
            f"- Assigned undivided pseudo-direction crashes: {metrics['assigned_undivided_pseudo_direction_crashes']}",
            "",
            "## Top Ambiguity Reasons",
            "",
            *top_ambiguity_lines,
            "",
            "## Top Unresolved Reasons",
            "",
            *top_unresolved_lines,
            "",
            "## QA",
            "",
            f"- Usable catchment rows loaded: {metrics['usable_polygon_rows_loaded']}",
            f"- Unstable or blocked catchment rows used: {metrics['unstable_or_blocked_polygon_rows_used']}",
            "- Crash direction fields read or used: False",
            "- Scaffold or catchment construction changed: False",
            "- Assigned rows inherit upstream/downstream only from `signal_relative_direction` on matched catchments.",
            "",
            "## Remaining Uncertainty",
            "",
            "- Boundary behavior follows the available GeoPandas spatial predicate listed above.",
            "- Ambiguous overlaps are preserved for review rather than resolved by nearest-distance logic.",
            "- Unresolved rows are not interpreted as absence of downstream relevance; they only failed containment in the current usable surface.",
            "",
        ]
    )

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "crash point assignment to usable roadway-only directional catchment polygons",
        "assignment_only_not_crash_analysis": True,
        "inputs": {
            "catchment_index": str(index_path),
            "catchment_polygons": str(polygon_path),
            "catchment_crs_metadata": str(crs_metadata_path),
            "crashes": str(crash_path),
            "crash_columns_read": CRASH_READ_COLUMNS,
        },
        "outputs": {},
        "method": {
            "usable_catchment_filter": "catchment_status = usable",
            "assignment_method": ASSIGNMENT_METHOD,
            "spatial_predicate": predicate,
            "catchment_crs_handling": catchment_crs_handling,
            "catchment_authoritative_crs": crs_metadata.get("authoritative_crs", ""),
            "nearest_assignment_used": False,
            "crash_direction_fields_read_or_used": False,
            "crash_distributions_used": False,
            "scaffold_or_catchment_construction_changed": False,
            "unstable_review_or_blocked_catchments_used": False,
        },
        "qa": metrics,
    }

    outputs = {
        "summary_csv": output_dir / "crash_directional_catchment_assignment_summary.csv",
        "assignments_csv": output_dir / "crash_directional_catchment_assignments.csv",
        "ambiguous_csv": output_dir / "crash_directional_catchment_ambiguous.csv",
        "unresolved_csv": output_dir / "crash_directional_catchment_unresolved.csv",
        "by_reference_signal_csv": output_dir / "crash_directional_assignment_by_reference_signal.csv",
        "by_signal_relative_direction_csv": output_dir / "crash_directional_assignment_by_signal_relative_direction.csv",
        "by_roadway_representation_type_csv": output_dir / "crash_directional_assignment_by_roadway_representation_type.csv",
        "by_catchment_method_csv": output_dir / "crash_directional_assignment_by_catchment_method.csv",
        "by_bin_index_csv": output_dir / "crash_directional_assignment_by_bin_index.csv",
        "ambiguity_summary_csv": output_dir / "crash_directional_assignment_ambiguity_summary.csv",
        "unresolved_summary_csv": output_dir / "crash_directional_assignment_unresolved_summary.csv",
        "crs_sanity_csv": output_dir / "crash_directional_assignment_crs_sanity.csv",
        "findings_md": output_dir / "crash_directional_catchment_assignment_findings.md",
        "manifest_json": output_dir / "crash_directional_catchment_assignment_manifest.json",
    }

    _write_csv(summary, outputs["summary_csv"])
    _write_csv(assigned, outputs["assignments_csv"])
    _write_csv(ambiguous, outputs["ambiguous_csv"])
    _write_csv(unresolved, outputs["unresolved_csv"])
    _write_csv(by_reference_signal, outputs["by_reference_signal_csv"])
    _write_csv(by_direction, outputs["by_signal_relative_direction_csv"])
    _write_csv(by_representation, outputs["by_roadway_representation_type_csv"])
    _write_csv(by_catchment_method, outputs["by_catchment_method_csv"])
    _write_csv(by_bin_index, outputs["by_bin_index_csv"])
    _write_csv(ambiguity_summary, outputs["ambiguity_summary_csv"])
    _write_csv(unresolved_summary, outputs["unresolved_summary_csv"])
    _write_csv(crs_sanity, outputs["crs_sanity_csv"])
    _write_text(findings, outputs["findings_md"])

    manifest["outputs"] = {key: str(path) for key, path in outputs.items()}
    _write_json(manifest, outputs["manifest_json"])

    return {key: str(path) for key, path in outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assign crash points to usable reference-signal directional catchment polygons."
    )
    parser.add_argument("--normalized-root", type=Path, default=NORMALIZED_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_crash_directional_catchment_assignment(
        normalized_root=args.normalized_root,
        output_root=args.output_root,
    )
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
