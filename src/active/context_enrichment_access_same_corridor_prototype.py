import argparse
import json
from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd

from .config import load_runtime_config
from .context_enrichment import (
    ACCESS_NEAR_SIGNAL_THRESHOLD_FT,
    METERS_TO_FEET,
    _flow_matches_line_direction,
    _copy_output_to_history,
    _normalize_line_geometry,
    _normalize_route_name,
    _output_subdir,
    _prepare_geojson_export,
    _prepare_output_path,
    _require_fields,
    _to_int64,
    _to_numeric,
    _write_csv_frame,
    _write_json_object,
    _write_text_file,
)


OUTPUT_FOLDER_NAME = "context_enrichment_access_same_corridor_prototype"
DEFAULT_FAMILY_TABLE = Path("docs/workflow/context_enrichment_access_same_corridor_seed_families.csv")
REVIEWED_FAMILY_REQUIRED_FIELDS = [
    "FamilyKey",
    "ReviewDecision",
    "AccessRouteNorm",
    "StudyRouteNorm",
    "LocalDistanceMaxFt",
    "ReviewReason",
    "ReviewNotes",
]
ACCESS_POINT_REQUIRED_FIELDS = [
    "Access_PointID",
    "StudyAreaID",
    "Signal_RowID",
    "StudyRoad_RowID",
    "Access_Route",
    "Access_Measure",
    "Access_ToRowDistanceFt",
    "Access_ProjectionFt",
    "Access_SignalProjectionFt",
    "Access_SignalRelativePosition",
    "Access_AssignmentStatus",
    "Access_AssignmentReason",
    "Access_AssignmentRule",
]
APPROACH_ROW_REQUIRED_FIELDS = [
    "StudyAreaID",
    "Signal_RowID",
    "StudyRoad_RowID",
    "ApproachRoad_RTE_NM",
    "ApproachLengthMeters",
]
SIGNAL_REQUIRED_FIELDS = [
    "StudyAreaID",
    "Signal_RowID",
]
DISTANCE_TIE_TOLERANCE_FT = 0.01
PROTOTYPE_RULE = "reviewed_family_local_distance_unique_row_project_compare"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bounded same-corridor access prototype outside production matching."
    )
    parser.add_argument(
        "--context-output-root",
        help="Optional override for the production context enrichment output root.",
    )
    parser.add_argument(
        "--output-root",
        help="Optional override for the prototype output root.",
    )
    parser.add_argument(
        "--family-table",
        help="Optional override for the reviewed same-corridor family table CSV.",
    )
    parser.add_argument(
        "--run-label",
        help="Optional label stored in the prototype run summary.",
    )
    return parser.parse_args()


def _resolve_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, str]:
    config = load_runtime_config()
    context_output_root = Path(args.context_output_root) if args.context_output_root else config.output_dir / "context_enrichment"
    output_root = Path(args.output_root) if args.output_root else config.output_dir / OUTPUT_FOLDER_NAME
    family_table = Path(args.family_table) if args.family_table else config.repo_root / DEFAULT_FAMILY_TABLE
    return context_output_root, output_root, family_table, config.working_crs


def _find_latest_production_run_summary(context_output_root: Path) -> Path:
    candidates = []
    for subdir in (
        context_output_root / "runs" / "current",
        context_output_root / "runs" / "history",
    ):
        candidates.extend(subdir.glob("context_enrichment_run_summary*.json"))
    if not candidates:
        raise FileNotFoundError(f"No context enrichment run summary found under {context_output_root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _load_geojson(path: Path, required_fields: list[str], label: str, target_crs: str) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    if frame.crs is None:
        raise ValueError(f"{label} has no CRS: {path}")
    frame = frame.to_crs(target_crs)
    _require_fields(frame, required_fields, label)
    return gpd.GeoDataFrame(frame, geometry="geometry", crs=frame.crs)


def _load_family_table(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    _require_fields(frame, REVIEWED_FAMILY_REQUIRED_FIELDS, path.name)
    frame["ReviewDecision"] = frame["ReviewDecision"].astype(str).str.strip().str.lower()
    frame["AccessRouteNorm"] = frame["AccessRouteNorm"].map(_normalize_route_name)
    frame["StudyRouteNorm"] = frame["StudyRouteNorm"].map(_normalize_route_name)
    frame["LocalDistanceMaxFt"] = _to_numeric(frame["LocalDistanceMaxFt"])
    duplicate_pairs = frame.duplicated(subset=["ReviewDecision", "AccessRouteNorm", "StudyRouteNorm"], keep=False)
    if bool(duplicate_pairs.any()):
        raise ValueError(
            "Reviewed same-corridor family table contains duplicate review rows for the same decision and pair."
        )
    include_missing_threshold = frame["ReviewDecision"].eq("include") & (
        frame["LocalDistanceMaxFt"].isna() | frame["LocalDistanceMaxFt"].le(0)
    )
    if bool(include_missing_threshold.any()):
        raise ValueError("Included reviewed same-corridor families require a positive LocalDistanceMaxFt.")
    return frame


def _pick_flow_direction_column(frame: pd.DataFrame) -> str:
    for column in ("FlowDirection", "FlowDirectionUsed"):
        if column in frame.columns:
            return column
    raise ValueError("Approach rows must contain FlowDirection or FlowDirectionUsed for prototype projection checks.")


def _load_production_inputs(summary_path: Path, working_crs: str) -> tuple[dict[str, object], gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    output_files = summary["output_files"]
    source_paths = summary["source_paths"]
    access_points = _load_geojson(
        Path(output_files["access_assignment_points_geojson"]),
        ACCESS_POINT_REQUIRED_FIELDS,
        "access_assignment_points_geojson",
        working_crs,
    )
    approach_rows = _load_geojson(
        Path(output_files["approach_row_context_enriched_geojson"]),
        APPROACH_ROW_REQUIRED_FIELDS,
        "approach_row_context_enriched_geojson",
        working_crs,
    )
    signals = _load_geojson(
        Path(source_paths["signals"]),
        SIGNAL_REQUIRED_FIELDS,
        "signals.geojson",
        working_crs,
    )
    access_points["StudyAreaID"] = access_points["StudyAreaID"].astype(str)
    access_points["Signal_RowID"] = _to_int64(access_points["Signal_RowID"])
    access_points["StudyRoad_RowID"] = _to_int64(access_points["StudyRoad_RowID"])
    access_points["Access_Route_Normalized"] = access_points["Access_Route"].map(_normalize_route_name)
    access_points["Access_Measure"] = _to_numeric(access_points["Access_Measure"])

    approach_rows["StudyAreaID"] = approach_rows["StudyAreaID"].astype(str)
    approach_rows["Signal_RowID"] = _to_int64(approach_rows["Signal_RowID"])
    approach_rows["StudyRoad_RowID"] = _to_int64(approach_rows["StudyRoad_RowID"])
    approach_rows["Approach_Route_Normalized"] = approach_rows["ApproachRoad_RTE_NM"].map(_normalize_route_name)

    signals["StudyAreaID"] = signals["StudyAreaID"].astype(str)
    signals["Signal_RowID"] = _to_int64(signals["Signal_RowID"])
    return summary, access_points, approach_rows, signals


def _nearest_distance_rank(values: list[dict[str, object]]) -> dict[int, int]:
    ranked = {}
    sortable = [
        (float(item["Candidate_ToRowDistanceFt"]), int(item["Candidate_StudyRoad_RowID"]))
        for item in values
        if item["Candidate_ToRowDistanceFt"] is not None and pd.notna(item["Candidate_StudyRoad_RowID"])
    ]
    sortable.sort(key=lambda item: (item[0], item[1]))
    for rank, (_, row_id) in enumerate(sortable, start=1):
        ranked[row_id] = rank
    return ranked


def _prototype_status_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {str(key): int(value) for key, value in frame.fillna("<null>").value_counts(dropna=False).to_dict().items()}


def _reviewed_family_candidate_decision(
    evaluations: list[dict[str, object]],
    *,
    signal_projection_supported: bool = True,
    distance_tie_tolerance_ft: float = DISTANCE_TIE_TOLERANCE_FT,
) -> dict[str, object]:
    approved_route_present = any(bool(item.get("approved_pair")) for item in evaluations)
    if not approved_route_present:
        return {
            "status": "approved_study_route_not_present",
            "reason": "approved_family_route_absent_in_study_area",
            "winner": None,
        }

    approved_within_threshold = [item for item in evaluations if bool(item.get("within_threshold"))]
    if not approved_within_threshold:
        return {
            "status": "no_local_geometry_support",
            "reason": "approved_family_row_outside_local_threshold",
            "winner": None,
        }
    if len(approved_within_threshold) > 1:
        return {
            "status": "ambiguous_local_geometry",
            "reason": "multiple_approved_rows_within_threshold",
            "winner": None,
        }

    ordered_evaluations = sorted(
        [item for item in evaluations if item.get("distance_ft") is not None],
        key=lambda item: (float(item["distance_ft"]), int(item["StudyRoad_RowID"])),
    )
    if not ordered_evaluations:
        return {
            "status": "no_local_geometry_support",
            "reason": "no_usable_candidate_geometry",
            "winner": None,
        }

    winner = approved_within_threshold[0]
    overall_nearest = ordered_evaluations[0]
    overall_second = ordered_evaluations[1] if len(ordered_evaluations) > 1 else None
    if int(overall_nearest["StudyRoad_RowID"]) != int(winner["StudyRoad_RowID"]):
        return {
            "status": "nearest_row_not_approved_pair",
            "reason": "nearest_row_not_in_reviewed_family",
            "winner": None,
        }
    if (
        overall_second is not None
        and abs(float(overall_second["distance_ft"]) - float(overall_nearest["distance_ft"]))
        <= distance_tie_tolerance_ft
    ):
        return {
            "status": "ambiguous_nearest_row",
            "reason": "nearest_row_tie_within_0_01ft",
            "winner": None,
        }
    if not signal_projection_supported:
        return {
            "status": "missing_flow_or_projection",
            "reason": "missing_flow_or_projection",
            "winner": None,
        }
    return {
        "status": "candidate_supported",
        "reason": "reviewed_family_unique_local_geometry_supported",
        "winner": winner,
    }


def _json_ready(value: object) -> object:
    if isinstance(value, pd.DataFrame):
        return [_json_ready(record) for record in value.astype(object).where(pd.notna(value), None).to_dict(orient="records")]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def _count_by_class(frame: pd.DataFrame, status_col: str, position_col: str, prefix: str) -> pd.DataFrame:
    assigned = frame.loc[frame[status_col].isin(["matched", "near_signal"])].copy()
    if assigned.empty:
        return pd.DataFrame()
    assigned["_impact_position"] = assigned[position_col].where(
        assigned[position_col].isin(["upstream", "downstream", "near_signal"]),
        "unresolved",
    )
    grouped = (
        assigned.groupby(["StudyAreaID", "Signal_RowID"], dropna=False)
        .agg(
            **{
                f"{prefix}_AccessCount": ("Access_PointID", "size"),
                f"{prefix}_UniqueAccessPointCount": ("Access_PointID", "nunique"),
                f"{prefix}_UpstreamCount": ("_impact_position", lambda values: int(pd.Series(values).eq("upstream").sum())),
                f"{prefix}_DownstreamCount": ("_impact_position", lambda values: int(pd.Series(values).eq("downstream").sum())),
                f"{prefix}_NearSignalCount": ("_impact_position", lambda values: int(pd.Series(values).eq("near_signal").sum())),
                f"{prefix}_UnresolvedPositionCount": (
                    "_impact_position",
                    lambda values: int(pd.Series(values).eq("unresolved").sum()),
                ),
            }
        )
        .reset_index()
    )
    return grouped


def _count_by_row(frame: pd.DataFrame, status_col: str, row_col: str, position_col: str, prefix: str) -> pd.DataFrame:
    assigned = frame.loc[frame[status_col].isin(["matched", "near_signal"])].copy()
    assigned[row_col] = _to_int64(assigned[row_col])
    assigned = assigned.loc[assigned[row_col].notna()].copy()
    if assigned.empty:
        return pd.DataFrame()
    assigned["_impact_position"] = assigned[position_col].where(
        assigned[position_col].isin(["upstream", "downstream", "near_signal"]),
        "unresolved",
    )
    grouped = (
        assigned.groupby(["StudyAreaID", "Signal_RowID", row_col], dropna=False)
        .agg(
            **{
                f"{prefix}_AccessCount": ("Access_PointID", "size"),
                f"{prefix}_UniqueAccessPointCount": ("Access_PointID", "nunique"),
                f"{prefix}_UpstreamCount": ("_impact_position", lambda values: int(pd.Series(values).eq("upstream").sum())),
                f"{prefix}_DownstreamCount": ("_impact_position", lambda values: int(pd.Series(values).eq("downstream").sum())),
                f"{prefix}_NearSignalCount": ("_impact_position", lambda values: int(pd.Series(values).eq("near_signal").sum())),
            }
        )
        .reset_index()
        .rename(columns={row_col: "StudyRoad_RowID"})
    )
    grouped["StudyRoad_RowID"] = _to_int64(grouped["StudyRoad_RowID"])
    return grouped


def _fill_count_columns(frame: pd.DataFrame) -> pd.DataFrame:
    count_columns = [
        column
        for column in frame.columns
        if column.endswith("Count") or column.endswith("Rows") or column.endswith("UniqueAccessPoints")
    ]
    for column in count_columns:
        frame[column] = _to_numeric(frame[column]).fillna(0).astype(int)
    return frame


def _merge_count_frames(left: pd.DataFrame, right: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    if left.empty and right.empty:
        return pd.DataFrame(columns=keys)
    if left.empty:
        merged = right.copy()
    elif right.empty:
        merged = left.copy()
    else:
        merged = left.merge(right, on=keys, how="outer")
    return _fill_count_columns(merged)


def _build_signal_approach_impact_summary(assignments: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object], str]:
    impact = assignments.copy()
    impact["StudyAreaID"] = impact["StudyAreaID"].astype(str)
    impact["Signal_RowID"] = _to_int64(impact["Signal_RowID"])
    impact["StudyRoad_RowID"] = _to_int64(impact["StudyRoad_RowID"])
    impact["Prototype_EffectiveStudyRoad_RowID"] = _to_int64(impact["Prototype_EffectiveStudyRoad_RowID"])
    impact["Prototype_Recovered"] = impact["Prototype_Recovered"].astype(bool)
    impact["Prototype_Evaluated"] = impact["Prototype_Evaluated"].astype(bool)

    production_signal = _count_by_class(
        impact,
        "Access_AssignmentStatus",
        "Access_SignalRelativePosition",
        "Production",
    )
    prototype_signal = _count_by_class(
        impact,
        "Prototype_EffectiveAssignmentStatus",
        "Prototype_EffectiveSignalRelativePosition",
        "Prototype",
    )
    signal_impact = _merge_count_frames(production_signal, prototype_signal, ["StudyAreaID", "Signal_RowID"])
    if not signal_impact.empty:
        for column in (
            "Production_AccessCount",
            "Production_UniqueAccessPointCount",
            "Production_UpstreamCount",
            "Production_DownstreamCount",
            "Production_NearSignalCount",
            "Production_UnresolvedPositionCount",
            "Prototype_AccessCount",
            "Prototype_UniqueAccessPointCount",
            "Prototype_UpstreamCount",
            "Prototype_DownstreamCount",
            "Prototype_NearSignalCount",
            "Prototype_UnresolvedPositionCount",
        ):
            if column not in signal_impact.columns:
                signal_impact[column] = 0
        recovered_signal = (
            impact.loc[impact["Prototype_Recovered"]]
            .groupby(["StudyAreaID", "Signal_RowID"], dropna=False)
            .agg(
                RecoveredRows=("Access_PointID", "size"),
                RecoveredUniqueAccessPoints=("Access_PointID", "nunique"),
                RecoveredUpstreamRows=(
                    "Prototype_EffectiveSignalRelativePosition",
                    lambda values: int(pd.Series(values).eq("upstream").sum()),
                ),
                RecoveredDownstreamRows=(
                    "Prototype_EffectiveSignalRelativePosition",
                    lambda values: int(pd.Series(values).eq("downstream").sum()),
                ),
                RecoveredNearSignalRows=(
                    "Prototype_EffectiveSignalRelativePosition",
                    lambda values: int(pd.Series(values).eq("near_signal").sum()),
                ),
            )
            .reset_index()
        )
        refused_signal = (
            impact.loc[impact["Prototype_Evaluated"] & ~impact["Prototype_Recovered"]]
            .groupby(["StudyAreaID", "Signal_RowID"], dropna=False)
            .agg(
                RefusedReviewedFamilyRows=("Access_PointID", "size"),
                RefusedUniqueAccessPoints=("Access_PointID", "nunique"),
                RefusalReasons=("Prototype_AssignmentReason", lambda values: "|".join(sorted({str(value) for value in values}))),
            )
            .reset_index()
        )
        signal_impact = _merge_count_frames(signal_impact, recovered_signal, ["StudyAreaID", "Signal_RowID"])
        signal_impact = _merge_count_frames(signal_impact, refused_signal, ["StudyAreaID", "Signal_RowID"])
        for column in (
            "RecoveredRows",
            "RecoveredUniqueAccessPoints",
            "RecoveredUpstreamRows",
            "RecoveredDownstreamRows",
            "RecoveredNearSignalRows",
            "RefusedReviewedFamilyRows",
            "RefusedUniqueAccessPoints",
        ):
            if column not in signal_impact.columns:
                signal_impact[column] = 0
        signal_impact["SignalAccessCountDelta"] = signal_impact["Prototype_AccessCount"] - signal_impact["Production_AccessCount"]
        signal_impact["SignalUniqueAccessPointDelta"] = (
            signal_impact["Prototype_UniqueAccessPointCount"] - signal_impact["Production_UniqueAccessPointCount"]
        )
        signal_impact["NeedsManualReview"] = signal_impact["RefusedReviewedFamilyRows"].gt(0)
        signal_impact["ReviewReason"] = signal_impact["NeedsManualReview"].map(
            lambda value: "refused_reviewed_family_candidates_present" if bool(value) else "no_refused_reviewed_family_candidates"
        )
        signal_impact = signal_impact.sort_values(
            ["SignalAccessCountDelta", "RefusedReviewedFamilyRows", "StudyAreaID"],
            ascending=[False, False, True],
        ).reset_index(drop=True)

    production_row = _count_by_row(
        impact,
        "Access_AssignmentStatus",
        "StudyRoad_RowID",
        "Access_SignalRelativePosition",
        "Production",
    )
    prototype_row = _count_by_row(
        impact,
        "Prototype_EffectiveAssignmentStatus",
        "Prototype_EffectiveStudyRoad_RowID",
        "Prototype_EffectiveSignalRelativePosition",
        "Prototype",
    )
    approach_row_impact = _merge_count_frames(production_row, prototype_row, ["StudyAreaID", "Signal_RowID", "StudyRoad_RowID"])
    if not approach_row_impact.empty:
        for column in (
            "Production_AccessCount",
            "Production_UniqueAccessPointCount",
            "Production_UpstreamCount",
            "Production_DownstreamCount",
            "Production_NearSignalCount",
            "Prototype_AccessCount",
            "Prototype_UniqueAccessPointCount",
            "Prototype_UpstreamCount",
            "Prototype_DownstreamCount",
            "Prototype_NearSignalCount",
        ):
            if column not in approach_row_impact.columns:
                approach_row_impact[column] = 0
        recovered_row = (
            impact.loc[impact["Prototype_Recovered"] & impact["Prototype_EffectiveStudyRoad_RowID"].notna()]
            .groupby(["StudyAreaID", "Signal_RowID", "Prototype_EffectiveStudyRoad_RowID"], dropna=False)
            .agg(
                RecoveredRows=("Access_PointID", "size"),
                RecoveredUniqueAccessPoints=("Access_PointID", "nunique"),
                RecoveredUpstreamRows=(
                    "Prototype_EffectiveSignalRelativePosition",
                    lambda values: int(pd.Series(values).eq("upstream").sum()),
                ),
                RecoveredDownstreamRows=(
                    "Prototype_EffectiveSignalRelativePosition",
                    lambda values: int(pd.Series(values).eq("downstream").sum()),
                ),
                RecoveredNearSignalRows=(
                    "Prototype_EffectiveSignalRelativePosition",
                    lambda values: int(pd.Series(values).eq("near_signal").sum()),
                ),
            )
            .reset_index()
            .rename(columns={"Prototype_EffectiveStudyRoad_RowID": "StudyRoad_RowID"})
        )
        recovered_row["StudyRoad_RowID"] = _to_int64(recovered_row["StudyRoad_RowID"])
        approach_row_impact = _merge_count_frames(
            approach_row_impact,
            recovered_row,
            ["StudyAreaID", "Signal_RowID", "StudyRoad_RowID"],
        )
        for column in (
            "RecoveredRows",
            "RecoveredUniqueAccessPoints",
            "RecoveredUpstreamRows",
            "RecoveredDownstreamRows",
            "RecoveredNearSignalRows",
        ):
            if column not in approach_row_impact.columns:
                approach_row_impact[column] = 0
        approach_row_impact["ApproachRowAccessCountDelta"] = (
            approach_row_impact["Prototype_AccessCount"] - approach_row_impact["Production_AccessCount"]
        )
        approach_row_impact["ApproachRowUniqueAccessPointDelta"] = (
            approach_row_impact["Prototype_UniqueAccessPointCount"] - approach_row_impact["Production_UniqueAccessPointCount"]
        )
        approach_row_impact = approach_row_impact.sort_values(
            ["ApproachRowAccessCountDelta", "RecoveredRows", "StudyAreaID", "StudyRoad_RowID"],
            ascending=[False, False, True, True],
        ).reset_index(drop=True)

    impacted_signals = signal_impact.loc[signal_impact.get("SignalAccessCountDelta", pd.Series(dtype=int)).gt(0)].copy()
    impacted_rows = approach_row_impact.loc[
        approach_row_impact.get("ApproachRowAccessCountDelta", pd.Series(dtype=int)).gt(0)
    ].copy()
    refused_impacts = signal_impact.loc[signal_impact.get("RefusedReviewedFamilyRows", pd.Series(dtype=int)).gt(0)].copy()

    summary = {
        "signal_level": {
            "signals_with_access_count_change": int(len(impacted_signals)),
            "max_signal_access_count_delta": int(impacted_signals["SignalAccessCountDelta"].max()) if not impacted_signals.empty else 0,
            "total_signal_access_count_delta": int(impacted_signals["SignalAccessCountDelta"].sum()) if not impacted_signals.empty else 0,
            "signals_with_refused_reviewed_family_candidates": int(len(refused_impacts)),
            "refused_reviewed_family_rows": int(refused_impacts["RefusedReviewedFamilyRows"].sum()) if not refused_impacts.empty else 0,
        },
        "approach_row_level": {
            "approach_rows_with_access_count_change": int(len(impacted_rows)),
            "max_approach_row_access_count_delta": int(impacted_rows["ApproachRowAccessCountDelta"].max())
            if not impacted_rows.empty
            else 0,
            "total_approach_row_access_count_delta": int(impacted_rows["ApproachRowAccessCountDelta"].sum())
            if not impacted_rows.empty
            else 0,
        },
        "concentration": {
            "recovered_rows": int(impact["Prototype_Recovered"].sum()),
            "recovered_unique_access_points": int(impact.loc[impact["Prototype_Recovered"], "Access_PointID"].nunique()),
            "recovered_study_area_count": int(impact.loc[impact["Prototype_Recovered"], "StudyAreaID"].nunique()),
            "recovered_signal_count": int(impact.loc[impact["Prototype_Recovered"], "Signal_RowID"].nunique()),
        },
        "top_signal_impacts": impacted_signals.head(10).to_dict(orient="records"),
        "top_approach_row_impacts": impacted_rows.head(10).to_dict(orient="records"),
        "refused_signal_review": refused_impacts.head(10).to_dict(orient="records"),
    }

    lines = [
        "# Same-Corridor Access Signal/Approach Impact Summary",
        "",
        "This artifact compares production access counts with the prototype-effective same-corridor assignment counts.",
        "It is validation evidence only; it does not authorize production promotion.",
        "",
        "## Topline",
        "",
        f"- Signals/study areas with access-count changes: `{summary['signal_level']['signals_with_access_count_change']}`",
        f"- Total signal-level access-count delta: `{summary['signal_level']['total_signal_access_count_delta']}`",
        f"- Maximum signal-level access-count delta: `{summary['signal_level']['max_signal_access_count_delta']}`",
        f"- Approach rows with access-count changes: `{summary['approach_row_level']['approach_rows_with_access_count_change']}`",
        f"- Total approach-row access-count delta: `{summary['approach_row_level']['total_approach_row_access_count_delta']}`",
        f"- Maximum approach-row access-count delta: `{summary['approach_row_level']['max_approach_row_access_count_delta']}`",
        f"- Recovered rows: `{summary['concentration']['recovered_rows']}`",
        f"- Recovered unique access points: `{summary['concentration']['recovered_unique_access_points']}`",
        f"- Recovered study areas: `{summary['concentration']['recovered_study_area_count']}`",
        "",
        "## Refused Reviewed-Family Candidates",
        "",
        f"- Signals/study areas with refused reviewed-family candidates: `{summary['signal_level']['signals_with_refused_reviewed_family_candidates']}`",
        f"- Refused reviewed-family rows: `{summary['signal_level']['refused_reviewed_family_rows']}`",
        "",
        "These refused rows are not count changes. They are review flags because they were in an approved family, but the approved study route was absent or assignment support was otherwise insufficient.",
        "",
        "## Decision Boundary",
        "",
        "- validated prototype evidence: reviewed-family rows with unique local geometry support can recover access assignments that exact route matching misses",
        "- still required: mapped review of recovered and refused candidates",
        "- not authorized: fuzzy matching, unreviewed aliases, or production promotion",
    ]
    return signal_impact, approach_row_impact, summary, "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    context_output_root, output_root, family_table_path, working_crs = _resolve_paths(args)

    summary_path = _find_latest_production_run_summary(context_output_root)
    summary, access_points, approach_rows, signals = _load_production_inputs(summary_path, working_crs)
    family_table = _load_family_table(family_table_path)
    flow_direction_column = _pick_flow_direction_column(approach_rows)

    tables_current_dir = _output_subdir(output_root, "tables", "current")
    tables_history_dir = _output_subdir(output_root, "tables", "history")
    review_current_dir = _output_subdir(output_root, "review", "current")
    review_history_dir = _output_subdir(output_root, "review", "history")
    review_geojson_current_dir = _output_subdir(output_root, "review", "geojson", "current")
    review_geojson_history_dir = _output_subdir(output_root, "review", "geojson", "history")
    runs_current_dir = _output_subdir(output_root, "runs", "current")
    runs_history_dir = _output_subdir(output_root, "runs", "history")

    include_families = family_table.loc[family_table["ReviewDecision"].eq("include")].copy()
    rows_by_study_area = {
        str(study_area_id): frame.copy()
        for study_area_id, frame in approach_rows.groupby("StudyAreaID", dropna=False)
    }
    signal_points = (
        signals[["StudyAreaID", "geometry"]]
        .drop_duplicates(subset=["StudyAreaID"], keep="first")
        .set_index("StudyAreaID")["geometry"]
        .to_dict()
    )
    include_routes_by_access = {
        access_route: frame.copy()
        for access_route, frame in include_families.groupby("AccessRouteNorm", dropna=False)
    }
    excluded_routes_by_access = {
        access_route: frame.copy()
        for access_route, frame in family_table.loc[family_table["ReviewDecision"].eq("exclude")].groupby(
            "AccessRouteNorm",
            dropna=False,
        )
    }

    assignment_rows: list[dict[str, object]] = []
    candidate_review_rows: list[dict[str, object]] = []

    for _, record in access_points.iterrows():
        record_dict = record.drop(labels=["geometry"]).to_dict()
        study_area_id = str(record["StudyAreaID"])
        access_route = record["Access_Route_Normalized"]
        production_status = record["Access_AssignmentStatus"]
        candidate_rows = rows_by_study_area.get(study_area_id, approach_rows.iloc[0:0].copy())

        assignment = {
            **record_dict,
            "Prototype_Evaluated": False,
            "Prototype_FamilyKey": None,
            "Prototype_FamilyKeysAvailable": None,
            "Prototype_ReviewDecision": None,
            "Prototype_LocalDistanceMaxFt": None,
            "Prototype_AssignmentStatus": "not_route_conflict" if production_status != "route_conflict" else "not_evaluated",
            "Prototype_AssignmentReason": None,
            "Prototype_AssignmentRule": None,
            "Prototype_Recovered": False,
            "Prototype_StudyRoad_RowID": record_dict.get("StudyRoad_RowID"),
            "Prototype_ToRowDistanceFt": record_dict.get("Access_ToRowDistanceFt"),
            "Prototype_SecondNearestDistanceFt": None,
            "Prototype_ApprovedRowCountWithinThreshold": 0,
            "Prototype_ProjectionFt": record_dict.get("Access_ProjectionFt"),
            "Prototype_SignalProjectionFt": record_dict.get("Access_SignalProjectionFt"),
            "Prototype_SignalRelativePosition": record_dict.get("Access_SignalRelativePosition"),
            "Prototype_EffectiveAssignmentStatus": record_dict.get("Access_AssignmentStatus"),
            "Prototype_EffectiveAssignmentReason": record_dict.get("Access_AssignmentReason"),
            "Prototype_EffectiveAssignmentRule": record_dict.get("Access_AssignmentRule"),
            "Prototype_EffectiveStudyRoad_RowID": record_dict.get("StudyRoad_RowID"),
            "Prototype_EffectiveSignalRelativePosition": record_dict.get("Access_SignalRelativePosition"),
        }

        if production_status != "route_conflict":
            assignment_rows.append({**assignment, "geometry": record["geometry"]})
            continue

        include_rows = include_routes_by_access.get(access_route)
        exclude_rows = excluded_routes_by_access.get(access_route)
        if include_rows is None or include_rows.empty:
            assignment["Prototype_Evaluated"] = False
            if exclude_rows is not None and not exclude_rows.empty:
                assignment["Prototype_AssignmentStatus"] = "family_excluded"
                assignment["Prototype_AssignmentReason"] = "review_table_excluded_for_prototype"
                assignment["Prototype_FamilyKeysAvailable"] = "|".join(exclude_rows["FamilyKey"].astype(str).tolist())
                assignment["Prototype_ReviewDecision"] = "exclude"
            else:
                assignment["Prototype_AssignmentStatus"] = "no_reviewed_family"
                assignment["Prototype_AssignmentReason"] = "no_reviewed_same_corridor_family"
            assignment_rows.append({**assignment, "geometry": record["geometry"]})
            continue

        assignment["Prototype_Evaluated"] = True
        assignment["Prototype_FamilyKeysAvailable"] = "|".join(include_rows["FamilyKey"].astype(str).tolist())
        assignment["Prototype_ReviewDecision"] = "include"
        if len(include_rows) == 1:
            assignment["Prototype_FamilyKey"] = str(include_rows.iloc[0]["FamilyKey"])
            assignment["Prototype_LocalDistanceMaxFt"] = float(include_rows.iloc[0]["LocalDistanceMaxFt"])

        evaluations: list[dict[str, object]] = []
        approved_route_present = False
        for _, row in candidate_rows.iterrows():
            candidate_route = row["Approach_Route_Normalized"]
            line = _normalize_line_geometry(row["geometry"])
            distance_ft = float(record["geometry"].distance(row["geometry"]) * METERS_TO_FEET) if line is not None else None
            matching_family = include_rows.loc[include_rows["StudyRouteNorm"].eq(candidate_route)].copy()
            approved_pair = not matching_family.empty
            approved_route_present = approved_route_present or approved_pair
            family_key = str(matching_family.iloc[0]["FamilyKey"]) if approved_pair else None
            local_distance_max_ft = (
                float(matching_family.iloc[0]["LocalDistanceMaxFt"]) if approved_pair else None
            )
            within_threshold = approved_pair and distance_ft is not None and distance_ft <= local_distance_max_ft
            evaluations.append(
                {
                    "StudyRoad_RowID": int(row["StudyRoad_RowID"]),
                    "ApproachRoad_RTE_NM": row["ApproachRoad_RTE_NM"],
                    "Approach_Route_Normalized": candidate_route,
                    "FlowDirection": row[flow_direction_column],
                    "distance_ft": distance_ft,
                    "line": line,
                    "family_key": family_key,
                    "local_distance_max_ft": local_distance_max_ft,
                    "approved_pair": approved_pair,
                    "within_threshold": within_threshold,
                }
            )

        rank_lookup = _nearest_distance_rank(
            [
                {
                    "Candidate_StudyRoad_RowID": item["StudyRoad_RowID"],
                    "Candidate_ToRowDistanceFt": item["distance_ft"],
                }
                for item in evaluations
            ]
        )
        for item in evaluations:
            candidate_review_rows.append(
                {
                    "Access_PointID": str(record["Access_PointID"]),
                    "StudyAreaID": study_area_id,
                    "Signal_RowID": assignment["Signal_RowID"],
                    "Production_AssignmentStatus": production_status,
                    "Access_Route": record["Access_Route"],
                    "Access_Route_Normalized": access_route,
                    "FamilyKey": item["family_key"],
                    "Prototype_ReviewDecision": "include" if item["approved_pair"] else None,
                    "LocalDistanceMaxFt": item["local_distance_max_ft"],
                    "Candidate_StudyRoad_RowID": item["StudyRoad_RowID"],
                    "Candidate_StudyRoute": item["ApproachRoad_RTE_NM"],
                    "Candidate_StudyRoute_Normalized": item["Approach_Route_Normalized"],
                    "Candidate_ToRowDistanceFt": item["distance_ft"],
                    "Candidate_DistanceRank": rank_lookup.get(item["StudyRoad_RowID"]),
                    "Candidate_IsApprovedPair": item["approved_pair"],
                    "Candidate_WithinThreshold": item["within_threshold"],
                    "Candidate_LineUsable": item["line"] is not None,
                    "Candidate_FlowDirection": item["FlowDirection"],
                }
            )

        approved_within_threshold = [item for item in evaluations if item["within_threshold"]]
        nearest_distances = sorted(
            [item["distance_ft"] for item in evaluations if item["distance_ft"] is not None]
        )
        assignment["Prototype_ApprovedRowCountWithinThreshold"] = int(len(approved_within_threshold))
        assignment["Prototype_SecondNearestDistanceFt"] = (
            float(nearest_distances[1]) if len(nearest_distances) > 1 else None
        )

        decision = _reviewed_family_candidate_decision(evaluations)
        if decision["status"] != "candidate_supported":
            assignment["Prototype_AssignmentStatus"] = decision["status"]
            assignment["Prototype_AssignmentReason"] = decision["reason"]
            assignment_rows.append({**assignment, "geometry": record["geometry"]})
            continue

        winner = decision["winner"]
        signal_point = signal_points.get(study_area_id)
        flow_follows_geometry = _flow_matches_line_direction(winner["line"], winner["FlowDirection"])
        if signal_point is None or winner["line"] is None or flow_follows_geometry is None:
            assignment["Prototype_AssignmentStatus"] = "missing_flow_or_projection"
            assignment["Prototype_AssignmentReason"] = "missing_flow_or_projection"
            assignment_rows.append({**assignment, "geometry": record["geometry"]})
            continue

        point_projection_ft = float(winner["line"].project(record["geometry"]) * METERS_TO_FEET)
        signal_projection_ft = float(winner["line"].project(signal_point) * METERS_TO_FEET)
        assignment["Prototype_FamilyKey"] = winner["family_key"]
        assignment["Prototype_LocalDistanceMaxFt"] = winner["local_distance_max_ft"]
        assignment["Prototype_StudyRoad_RowID"] = winner["StudyRoad_RowID"]
        assignment["Prototype_ToRowDistanceFt"] = winner["distance_ft"]
        assignment["Prototype_ProjectionFt"] = point_projection_ft
        assignment["Prototype_SignalProjectionFt"] = signal_projection_ft
        delta_ft = point_projection_ft - signal_projection_ft
        if abs(delta_ft) <= ACCESS_NEAR_SIGNAL_THRESHOLD_FT:
            assignment["Prototype_AssignmentStatus"] = "recovered_near_signal"
            assignment["Prototype_AssignmentReason"] = "reviewed_same_corridor_projection_within_65_6ft_of_signal"
            assignment["Prototype_SignalRelativePosition"] = "near_signal"
            assignment["Prototype_Recovered"] = True
            assignment["Prototype_EffectiveAssignmentStatus"] = "near_signal"
            assignment["Prototype_EffectiveAssignmentReason"] = assignment["Prototype_AssignmentReason"]
            assignment["Prototype_EffectiveAssignmentRule"] = PROTOTYPE_RULE
            assignment["Prototype_EffectiveStudyRoad_RowID"] = winner["StudyRoad_RowID"]
            assignment["Prototype_EffectiveSignalRelativePosition"] = "near_signal"
        else:
            if flow_follows_geometry:
                position = "upstream" if point_projection_ft < signal_projection_ft else "downstream"
            else:
                position = "upstream" if point_projection_ft > signal_projection_ft else "downstream"
            assignment["Prototype_AssignmentStatus"] = "recovered_matched"
            assignment["Prototype_AssignmentReason"] = "reviewed_same_corridor_unique_local_projection_match"
            assignment["Prototype_SignalRelativePosition"] = position
            assignment["Prototype_Recovered"] = True
            assignment["Prototype_EffectiveAssignmentStatus"] = "matched"
            assignment["Prototype_EffectiveAssignmentReason"] = assignment["Prototype_AssignmentReason"]
            assignment["Prototype_EffectiveAssignmentRule"] = PROTOTYPE_RULE
            assignment["Prototype_EffectiveStudyRoad_RowID"] = winner["StudyRoad_RowID"]
            assignment["Prototype_EffectiveSignalRelativePosition"] = position
        assignment["Prototype_AssignmentRule"] = PROTOTYPE_RULE
        assignment_rows.append({**assignment, "geometry": record["geometry"]})

    assignments_geo = gpd.GeoDataFrame(assignment_rows, geometry="geometry", crs=access_points.crs)
    assignments = pd.DataFrame(assignments_geo.drop(columns="geometry"))
    candidate_review = pd.DataFrame(candidate_review_rows)

    recovered_geo = assignments_geo.loc[assignments_geo["Prototype_Recovered"]].copy()
    refused_geo = assignments_geo.loc[
        assignments_geo["Prototype_Evaluated"] & ~assignments_geo["Prototype_Recovered"]
    ].copy()
    family_summary = (
        assignments.loc[assignments["Prototype_FamilyKey"].notna()]
        .groupby("Prototype_FamilyKey", dropna=False)
        .agg(
            PointStudyAreaRows=("Access_PointID", "size"),
            UniqueAccessPoints=("Access_PointID", "nunique"),
            RecoveredRows=("Prototype_Recovered", "sum"),
            RecoveredNearSignalRows=("Prototype_AssignmentStatus", lambda values: int(pd.Series(values).eq("recovered_near_signal").sum())),
            RecoveredMatchedRows=("Prototype_AssignmentStatus", lambda values: int(pd.Series(values).eq("recovered_matched").sum())),
            RefusedRows=("Prototype_Recovered", lambda values: int((~pd.Series(values).astype(bool)).sum())),
        )
        .reset_index()
        .sort_values(["RecoveredRows", "PointStudyAreaRows", "Prototype_FamilyKey"], ascending=[False, False, True])
    )
    signal_impact, approach_row_impact, impact_summary, impact_summary_markdown = _build_signal_approach_impact_summary(
        assignments
    )

    production_route_conflicts = assignments["Access_AssignmentStatus"].eq("route_conflict")
    prototype_recovered = assignments["Prototype_Recovered"]
    evaluated = assignments["Prototype_Evaluated"]

    methodology_lines = [
        "# Same-Corridor Access Prototype Methodology",
        "",
        "This prototype stays outside production matching and only evaluates production `route_conflict` access rows.",
        "",
        "Prototype evidence chain:",
        "",
        "1. access route must appear in the reviewed family table with `ReviewDecision = include`",
        "2. the approved study-route family must be present in the same study area",
        "3. exactly one approved study row must fall within the family-specific local threshold",
        "4. that approved row must also be the unique nearest study row overall",
        "5. projection onto the row and signal-relative comparison must succeed",
        "6. otherwise the candidate is refused and production matching remains unchanged",
        "",
        "The seed family table is copied to the prototype output lane for auditability.",
    ]
    validation_lines = [
        "# Same-Corridor Access Prototype Validation",
        "",
        f"- latest production run summary: `{summary_path}`",
        f"- reviewed family table: `{family_table_path}`",
        f"- total production point-study-area rows carried into prototype: `{int(len(assignments))}`",
        f"- production `route_conflict` rows: `{int(production_route_conflicts.sum())}`",
        f"- prototype-evaluated rows: `{int(evaluated.sum())}`",
        f"- recovered rows: `{int(prototype_recovered.sum())}`",
        f"- recovered unique access points: `{int(assignments.loc[prototype_recovered, 'Access_PointID'].nunique())}`",
        f"- refused evaluated rows: `{int((evaluated & ~prototype_recovered).sum())}`",
        "",
        "Prototype status distribution:",
        "",
    ]
    validation_lines.extend(
        [f"- `{key}`: `{value}`" for key, value in _prototype_status_counts(assignments["Prototype_AssignmentStatus"]).items()]
    )

    readme_lines = [
        "# Context Enrichment Same-Corridor Access Prototype",
        "",
        "This output lane contains a bounded reviewed-family prototype for same-corridor access assignment.",
        "",
        "It does not change production context enrichment outputs.",
        "",
        "Key artifacts:",
        "",
        "- `tables/current/same_corridor_prototype_assignments.csv`",
        "- `tables/current/same_corridor_candidate_review.csv`",
        "- `tables/current/same_corridor_family_summary.csv`",
        "- `review/current/same_corridor_prototype_methodology.md`",
        "- `review/current/same_corridor_prototype_validation.md`",
        "- `review/current/signal_approach_impact_summary.csv`",
        "- `review/current/approach_row_impact_summary.csv`",
        "- `review/current/signal_approach_impact_summary.json`",
        "- `review/current/signal_approach_impact_summary.md`",
        "- `review/geojson/current/recovered_same_corridor_assignments.geojson`",
        "- `review/geojson/current/refused_same_corridor_candidates.geojson`",
        "- `runs/current/same_corridor_prototype_run_summary.json`",
        "",
        "The seed reviewed family table copied into this output lane is the authoritative prototype review input used for the run.",
    ]

    output_files = {
        "reviewed_same_corridor_family_table": str(
            _write_csv_frame(
                family_table,
                tables_current_dir / "reviewed_same_corridor_family_table.csv",
                history_dir=tables_history_dir,
            )
        ),
        "same_corridor_prototype_assignments": str(
            _write_csv_frame(
                assignments,
                tables_current_dir / "same_corridor_prototype_assignments.csv",
                history_dir=tables_history_dir,
            )
        ),
        "same_corridor_candidate_review": str(
            _write_csv_frame(
                candidate_review,
                tables_current_dir / "same_corridor_candidate_review.csv",
                history_dir=tables_history_dir,
            )
        ),
        "same_corridor_family_summary": str(
            _write_csv_frame(
                family_summary,
                tables_current_dir / "same_corridor_family_summary.csv",
                history_dir=tables_history_dir,
            )
        ),
        "same_corridor_prototype_methodology": str(
            _write_text_file(
                "\n".join(methodology_lines),
                review_current_dir / "same_corridor_prototype_methodology.md",
                history_dir=review_history_dir,
            )
        ),
        "same_corridor_prototype_validation": str(
            _write_text_file(
                "\n".join(validation_lines),
                review_current_dir / "same_corridor_prototype_validation.md",
                history_dir=review_history_dir,
            )
        ),
        "signal_approach_impact_summary_csv": str(
            _write_csv_frame(
                signal_impact,
                review_current_dir / "signal_approach_impact_summary.csv",
                history_dir=review_history_dir,
            )
        ),
        "approach_row_impact_summary_csv": str(
            _write_csv_frame(
                approach_row_impact,
                review_current_dir / "approach_row_impact_summary.csv",
                history_dir=review_history_dir,
            )
        ),
        "signal_approach_impact_summary_json": str(
            _write_json_object(
                _json_ready(impact_summary),
                review_current_dir / "signal_approach_impact_summary.json",
                history_dir=review_history_dir,
            )
        ),
        "signal_approach_impact_summary_markdown": str(
            _write_text_file(
                impact_summary_markdown,
                review_current_dir / "signal_approach_impact_summary.md",
                history_dir=review_history_dir,
            )
        ),
        "recovered_same_corridor_assignments_geojson": str(
            _prepare_output_path(
                review_geojson_current_dir / "recovered_same_corridor_assignments.geojson",
                history_dir=review_geojson_history_dir,
            )
        ),
        "refused_same_corridor_candidates_geojson": str(
            _prepare_output_path(
                review_geojson_current_dir / "refused_same_corridor_candidates.geojson",
                history_dir=review_geojson_history_dir,
            )
        ),
        "readme": str(
            _write_text_file(
                "\n".join(readme_lines),
                output_root / "README.md",
                history_dir=output_root,
            )
        ),
    }

    recovered_path = Path(output_files["recovered_same_corridor_assignments_geojson"])
    recovered_path.write_text(_prepare_geojson_export(recovered_geo).to_json(drop_id=True), encoding="utf-8")
    _copy_output_to_history(recovered_path, review_geojson_history_dir)
    refused_path = Path(output_files["refused_same_corridor_candidates_geojson"])
    refused_path.write_text(_prepare_geojson_export(refused_geo).to_json(drop_id=True), encoding="utf-8")
    _copy_output_to_history(refused_path, review_geojson_history_dir)

    run_summary = {
        "interpreter": sys.executable,
        "command": "python -m src.active.context_enrichment_access_same_corridor_prototype",
        "run_label": args.run_label,
        "working_crs": working_crs,
        "production_run_summary": str(summary_path),
        "family_table": str(family_table_path),
        "prototype_assumptions": [
            "Prototype only evaluates production route_conflict rows.",
            "Only explicit reviewed include families are eligible for recovery.",
            "Approved same-corridor families ignore production measure-overlap support and instead require local geometry, unique nearest-row support, and projection success.",
            "Ambiguous or offset candidates are refused rather than forced.",
        ],
        "counts": {
            "total_point_study_area_rows": int(len(assignments)),
            "production_route_conflict_rows": int(production_route_conflicts.sum()),
            "prototype_evaluated_rows": int(evaluated.sum()),
            "prototype_recovered_rows": int(prototype_recovered.sum()),
            "prototype_recovered_unique_access_points": int(assignments.loc[prototype_recovered, "Access_PointID"].nunique()),
            "prototype_refused_rows": int((evaluated & ~prototype_recovered).sum()),
            "prototype_status_counts": _prototype_status_counts(assignments["Prototype_AssignmentStatus"]),
            "prototype_effective_assignment_status_counts": _prototype_status_counts(
                assignments["Prototype_EffectiveAssignmentStatus"]
            ),
            "signal_approach_impact": _json_ready(impact_summary),
        },
        "output_files": output_files,
    }
    run_summary_path = runs_current_dir / "same_corridor_prototype_run_summary.json"
    output_files["same_corridor_prototype_run_summary"] = str(run_summary_path)
    run_summary["output_files"] = output_files
    _write_json_object(
        run_summary,
        runs_current_dir / "same_corridor_prototype_run_summary.json",
        history_dir=runs_history_dir,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
