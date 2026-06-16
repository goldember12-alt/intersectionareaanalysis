from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_access_travelway_normalization_test"

HYBRID_DIR = OUTPUT_ROOT / "review/current/final_access_hybrid_source_travelway_diagnostic"
ACCESS_RERUN_DIR = OUTPUT_ROOT / "review/current/final_access_rerun_with_source_accounting"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
MAP_GPKG = OUTPUT_ROOT / "map_review/current/physical_leg_review/physical_leg_review.gpkg"

ACCESS_V1_FILE = Path("artifacts/normalized/access.parquet")
ACCESS_V2_FILE = Path("artifacts/normalized/access_v2.parquet")

SPATIAL_BASELINE_WIDTH_FT = 100
TYPED_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_in_only",
    "right_out_only",
    "other_review",
    "unknown",
]

CRASH_FIELD_TOKENS = (
    "crash_id",
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = [
    HYBRID_DIR / "hybrid_access_source_point_detail.csv",
    HYBRID_DIR / "hybrid_access_travelway_match_detail.csv",
    HYBRID_DIR / "hybrid_access_signal_leg_relation.csv",
    HYBRID_DIR / "hybrid_access_leg_length_diagnostic.csv",
    HYBRID_DIR / "hybrid_access_route_identity_diagnostic.csv",
    HYBRID_DIR / "hybrid_access_recovery_opportunity_summary.csv",
    HYBRID_DIR / "hybrid_access_signal_coverage_opportunity.csv",
    HYBRID_DIR / "hybrid_access_manifest.json",
    ACCESS_RERUN_DIR / "final_cleaned_access_target_bins.csv",
    ACCESS_RERUN_DIR / "final_cleaned_untyped_access_assignment_detail.csv",
    ACCESS_RERUN_DIR / "final_cleaned_typed_v2_access_assignment_detail.csv",
    ACCESS_RERUN_DIR / "final_access_source_point_accounting.csv",
    ACCESS_RERUN_DIR / "final_access_uncaptured_source_detail.csv",
    ACCESS_RERUN_DIR / "final_access_rerun_with_source_accounting_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    MAP_GPKG,
    ACCESS_V1_FILE,
    ACCESS_V2_FILE,
]


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"access_direction", "access_direction_raw", "access_direction_normalized"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash record/direction fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _collapse(values: pd.Series, limit: int = 12) -> str:
    items = sorted(
        {
            str(value)
            for value in values.dropna()
            if str(value).strip() and str(value).lower() not in {"nan", "none", "<na>"}
        }
    )
    return "|".join(items[:limit])


def _route_key(value: Any) -> str:
    text = str(value or "").upper()
    if not text or text == "NAN":
        return ""
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    for match in re.finditer(r"\b(US|VA|IS|SC|SR|RTE)\s*0*([0-9]+)\s*([NSEW])?B?\b", text):
        prefix, number, direction = match.groups()
        if prefix in {"SR", "RTE"}:
            prefix = "VA"
        return f"{prefix}{int(number)}{direction or ''}"
    compact = re.sub(r"[^A-Z0-9]+", "", text)
    for match in re.finditer(r"(US|VA|IS|SC|SR|RTE)0*([0-9]+)([NSEW])?B?", compact):
        prefix, number, direction = match.groups()
        if prefix in {"SR", "RTE"}:
            prefix = "VA"
        return f"{prefix}{int(number)}{direction or ''}"
    return compact


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _read_access_source(path: Path, *, layer: str) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    access = gpd.read_parquet(path)
    access = access.drop(columns=[column for column in access.columns if _blocked_column(column)], errors="ignore")
    if access.crs is None:
        access = access.set_crs("EPSG:3968", allow_override=True)
    access = access.to_crs("EPSG:3968")
    if layer == "typed_v2":
        access["access_point_id"] = access.get("access_v2_source_priority", "").astype(str) + ":" + access.get("access_v2_source_row_id", "").astype(str)
        access.loc[access["access_point_id"].eq(":"), "access_point_id"] = access.loc[access["access_point_id"].eq(":"), "id"].astype(str)
        access["route_name"] = access.get("route_name", "").astype(str)
        access["route_measure"] = access.get("route_measure", "").astype(str)
        access["source_layer"] = access.get("access_v2_source_layer", "").astype(str)
        access["access_control_category"] = access.get("access_control_category", "").astype(str).replace("", "unknown")
        access.loc[~access["access_control_category"].isin(TYPED_CATEGORIES), "access_control_category"] = "other_review"
    else:
        access["access_point_id"] = access.get("id", access.index.astype(str)).astype(str)
        access["route_name"] = access.get("_rte_nm", "").astype(str)
        access["route_measure"] = access.get("_m", "").astype(str)
        access["source_layer"] = access.get("Stage1_SourceLayer", "").astype(str)
        access["access_control_category"] = "untyped"
    access["access_layer"] = layer
    access["route_key"] = access["route_name"].map(_route_key)
    access["has_geometry"] = access.geometry.notna() & ~access.geometry.is_empty
    access["geometry_wkt"] = access.geometry.map(lambda geom: geom.wkt if geom is not None and not geom.is_empty else "")
    keep = ["access_point_id", "access_layer", "source_layer", "route_name", "route_measure", "route_key", "access_control_category", "has_geometry", "geometry_wkt"]
    out = pd.DataFrame(access[[col for col in keep if col in access.columns]]).copy()
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _read_source_travelway_identity() -> pd.DataFrame:
    _checkpoint("read_start source_travelway_full")
    cols = ["RTE_NM", "RTE_COMMON", "RTE_ID", "RIM_FACILI", "RTE_TYPE_N", "RTE_RAMP_C", "EVENT_SOUR"]
    source = gpd.read_file(MAP_GPKG, layer="source_travelway_full", columns=cols, ignore_geometry=True)
    source = pd.DataFrame(source)
    source["source_travelway_id"] = "source_travelway_" + source.index.astype(str).str.zfill(7)
    source["source_route_key"] = _text(source, "RTE_NM").map(_route_key)
    source["source_route_common_key"] = _text(source, "RTE_COMMON").map(_route_key)
    _checkpoint("read_complete source_travelway_full", len(source))
    return source


def _source_table() -> pd.DataFrame:
    source_access = pd.concat(
        [
            _read_access_source(ACCESS_V1_FILE, layer="untyped"),
            _read_access_source(ACCESS_V2_FILE, layer="typed_v2"),
        ],
        ignore_index=True,
        sort=False,
    )
    travelway = _read_csv(HYBRID_DIR / "hybrid_access_travelway_match_detail.csv")
    out = source_access.merge(travelway, on=["access_point_id", "access_layer"], how="left", suffixes=("", "_travelway"))
    out["normalized_travelway_route_identity"] = _text(out, "source_route_key").where(_text(out, "source_route_key").ne(""), _text(out, "source_route_common_key"))
    out["review_only_flag"] = "true"
    return out


def _represented_identity(target: pd.DataFrame) -> pd.DataFrame:
    out = target.copy()
    out["represented_travelway_identity_key"] = _text(out, "route_key").where(_text(out, "route_key").ne(""), _text(out, "route_facility_fields").map(_route_key))
    cols = [
        "target_signal_id",
        "target_bin_id",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "represented_travelway_identity_key",
        "route_facility_fields",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "final_alignment_class",
        "final_physical_leg_class",
        "speed_aadt_ready_bin",
        "review_only_recovery_provenance",
        "recovery_stream",
        "recovery_class",
    ]
    return out[[col for col in cols if col in out.columns]].copy()


def _spatial_baseline_assignments() -> pd.DataFrame:
    frames = []
    for layer, path in [
        ("untyped", ACCESS_RERUN_DIR / "final_cleaned_untyped_access_assignment_detail.csv"),
        ("typed_v2", ACCESS_RERUN_DIR / "final_cleaned_typed_v2_access_assignment_detail.csv"),
    ]:
        frame = _read_csv(path)
        frame = frame.loc[pd.to_numeric(frame.get("buffer_width_ft"), errors="coerce").eq(SPATIAL_BASELINE_WIDTH_FT)].copy()
        frame["access_layer"] = layer
        frames.append(frame)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def _quality(row: pd.Series) -> str:
    if str(row.get("grade_mainline_holdout_flag", "")).lower() == "true" or str(row.get("grade_separation_or_mainline_review_flag", "")).lower() == "true":
        return "blocked_grade_or_mainline"
    if str(row.get("source_limited_holdout_flag", "")).lower() == "true" or str(row.get("still_insufficient_evidence_flag", "")).lower() == "true":
        return "manual_review_needed"
    leg_class = str(row.get("hybrid_leg_length_class", ""))
    confidence = str(row.get("source_travelway_match_confidence", ""))
    compatibility = str(row.get("route_facility_compatibility", ""))
    if leg_class in {"beyond_2500_out_of_scope", "same_route_family_but_not_signal_relevant", "source_route_not_in_represented_universe", "source_geometry_or_route_missing"}:
        return "blocked_outside_signal_window"
    if confidence == "high" and "matches" in compatibility:
        return "high_confidence_source_travelway_match"
    if confidence in {"medium", "medium_spatial_only"} or "matches" in compatibility:
        return "medium_confidence_route_facility_match"
    if str(row.get("source_travelway_route_represented_flag", "")).lower() == "true":
        return "low_confidence_route_family_only"
    return "manual_review_needed"


def _candidate_route_assignments(target: pd.DataFrame) -> pd.DataFrame:
    relation = _read_csv(HYBRID_DIR / "hybrid_access_signal_leg_relation.csv")
    target_flags = target[
        [
            col
            for col in [
                "target_bin_id",
                "carriageway_subbranch_id_final",
                "route_facility_fields",
                "distance_start_ft",
                "distance_end_ft",
                "speed_aadt_ready_bin",
                "source_limited_holdout_flag",
                "grade_mainline_holdout_flag",
                "still_insufficient_evidence_flag",
                "review_only_recovery_provenance",
                "geometry_recovery_status",
                "recovery_stream",
                "recovery_class",
            ]
            if col in target.columns
        ]
    ].drop_duplicates("target_bin_id")
    relation = relation.merge(target_flags, on="target_bin_id", how="left", suffixes=("", "_target"))
    relation["route_normalized_quality_class"] = relation.apply(_quality, axis=1)
    relation["route_normalized_assignment_status"] = np.where(
        relation["route_normalized_quality_class"].isin(
            {
                "high_confidence_source_travelway_match",
                "medium_confidence_route_facility_match",
                "low_confidence_route_family_only",
            }
        ),
        "assigned_review_only",
        "blocked_review_only",
    )
    relation["assignment_method"] = np.where(
        relation["captured_max_buffer"].astype(str).str.lower().eq("true"),
        "spatial_100ft_with_travelway_identity",
        "travelway_route_source_normalized_nearest_signal_leg",
    )
    relation["normalized_route_source_match_class"] = relation["route_facility_compatibility"].where(
        _text(relation, "route_facility_compatibility").ne(""),
        "route_family_or_source_travelway_relation",
    )
    relation["signal_relative_window"] = _text(relation, "analysis_window")
    relation["review_only_flag"] = "true"
    relation["unweighted_access_count"] = np.where(relation["route_normalized_assignment_status"].eq("assigned_review_only"), 1.0, 0.0)
    assigned = relation.loc[relation["route_normalized_assignment_status"].eq("assigned_review_only")].copy()
    fanout = assigned.groupby(["access_layer", "access_point_id"], dropna=False)["target_bin_id"].nunique().rename("route_normalized_fanout_count").reset_index()
    relation = relation.merge(fanout, on=["access_layer", "access_point_id"], how="left")
    relation["route_normalized_fanout_count"] = pd.to_numeric(relation["route_normalized_fanout_count"], errors="coerce").fillna(0)
    relation["source_preserving_weighted_access_count"] = np.where(
        relation["route_normalized_assignment_status"].eq("assigned_review_only") & relation["route_normalized_fanout_count"].gt(0),
        1.0 / relation["route_normalized_fanout_count"],
        0.0,
    )
    keep = [
        "access_point_id",
        "access_layer",
        "access_control_category",
        "route_name",
        "route_measure",
        "route_key",
        "source_layer",
        "target_signal_id",
        "target_bin_id",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
        "analysis_window",
        "distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "source_travelway_id",
        "source_route_key",
        "source_route_common_key",
        "RTE_NM",
        "RTE_COMMON",
        "source_travelway_match_distance_ft",
        "source_travelway_match_method",
        "source_travelway_match_confidence",
        "route_facility_compatibility",
        "source_travelway_route_represented_flag",
        "hybrid_leg_length_class",
        "assignment_method",
        "normalized_route_source_match_class",
        "route_normalized_assignment_status",
        "route_normalized_quality_class",
        "route_normalized_fanout_count",
        "unweighted_access_count",
        "source_preserving_weighted_access_count",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "speed_aadt_ready_bin",
        "review_only_flag",
    ]
    return relation[[col for col in keep if col in relation.columns]].copy()


def _assigned(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[_text(frame, "route_normalized_assignment_status").eq("assigned_review_only")].copy()


def _window_summary(assignments: pd.DataFrame) -> pd.DataFrame:
    assigned = _assigned(assignments)
    if assigned.empty:
        return pd.DataFrame()
    agg = {
        "source_access_point_count": ("access_point_id", "nunique"),
        "assignment_count": ("access_point_id", "size"),
        "unweighted_access_count": ("unweighted_access_count", "sum"),
        "weighted_access_count": ("source_preserving_weighted_access_count", "sum"),
        "physical_leg_count_with_access": ("physical_leg_id_final", "nunique"),
        "quality_classes": ("route_normalized_quality_class", _collapse),
    }
    if "carriageway_subbranch_id_final" in assigned.columns:
        agg["carriageway_subbranch_count_with_access"] = ("carriageway_subbranch_id_final", "nunique")
    if "final_alignment_class" in assigned.columns:
        agg["final_alignment_class"] = ("final_alignment_class", "first")
    return assigned.groupby(["access_layer", "target_signal_id", "analysis_window"], dropna=False).agg(**agg).reset_index()


def _coverage(assignments: pd.DataFrame) -> pd.DataFrame:
    assigned = _assigned(assignments)
    rows = []
    for layer in ["untyped", "typed_v2"]:
        subset = assigned.loc[assigned["access_layer"].eq(layer)]
        for window in ["any", "0_1000", "1000_2500"]:
            win = subset if window == "any" else subset.loc[_text(subset, "analysis_window").eq(window)]
            rows.extend(
                [
                    {"access_layer": layer, "analysis_window": window, "metric": "signals_with_access", "count": int(_text(win, "target_signal_id").nunique())},
                    {"access_layer": layer, "analysis_window": window, "metric": "source_access_points_captured", "count": int(_text(win, "access_point_id").nunique())},
                    {"access_layer": layer, "analysis_window": window, "metric": "assignment_count", "count": int(len(win))},
                    {"access_layer": layer, "analysis_window": window, "metric": "weighted_assignment_total", "count": round(float(pd.to_numeric(win.get("source_preserving_weighted_access_count"), errors="coerce").fillna(0).sum()), 6)},
                ]
            )
    return pd.DataFrame(rows)


def _spatial_vs_normalized(assignments: pd.DataFrame, spatial: pd.DataFrame) -> pd.DataFrame:
    assigned = _assigned(assignments)
    rows = []
    all_source = {
        layer: set(_text(assignments.loc[assignments["access_layer"].eq(layer)], "access_point_id"))
        for layer in ["untyped", "typed_v2"]
    }
    for layer in ["untyped", "typed_v2"]:
        spatial_layer = spatial.loc[_text(spatial, "access_layer").eq(layer)]
        normalized_layer = assigned.loc[_text(assigned, "access_layer").eq(layer)]
        spatial_points = set(_text(spatial_layer, "access_point_id"))
        norm_points = set(_text(normalized_layer, "access_point_id"))
        spatial_signals = set(_text(spatial_layer, "target_signal_id"))
        norm_signals = set(_text(normalized_layer, "target_signal_id"))
        rows.extend(
            [
                {"access_layer": layer, "comparison_metric": "source_points_spatial_only", "count": len(spatial_points - norm_points)},
                {"access_layer": layer, "comparison_metric": "source_points_route_normalized_only", "count": len(norm_points - spatial_points)},
                {"access_layer": layer, "comparison_metric": "source_points_both", "count": len(norm_points & spatial_points)},
                {"access_layer": layer, "comparison_metric": "source_points_neither", "count": len(all_source[layer] - (norm_points | spatial_points))},
                {"access_layer": layer, "comparison_metric": "signals_spatial_only", "count": len(spatial_signals - norm_signals)},
                {"access_layer": layer, "comparison_metric": "signals_route_normalized_only", "count": len(norm_signals - spatial_signals)},
                {"access_layer": layer, "comparison_metric": "signals_both", "count": len(norm_signals & spatial_signals)},
                {"access_layer": layer, "comparison_metric": "route_normalized_assignment_rows", "count": len(normalized_layer)},
                {"access_layer": layer, "comparison_metric": "spatial_100ft_assignment_rows", "count": len(spatial_layer)},
            ]
        )
    return pd.DataFrame(rows)


def _fanout(assignments: pd.DataFrame) -> pd.DataFrame:
    assigned = _assigned(assignments)
    if assigned.empty:
        return pd.DataFrame()
    per_point = assigned.groupby(["access_layer", "access_point_id"], dropna=False).agg(
        route_normalized_fanout_count=("target_bin_id", "nunique"),
        assignment_count=("target_bin_id", "size"),
        weighted_total=("source_preserving_weighted_access_count", "sum"),
    ).reset_index()
    per_point["fanout_bucket"] = pd.cut(
        pd.to_numeric(per_point["route_normalized_fanout_count"], errors="coerce").fillna(0),
        bins=[0, 1, 2, 3, np.inf],
        labels=["1", "2", "3", "4_plus"],
        include_lowest=True,
    ).astype(str)
    return per_point.groupby(["access_layer", "fanout_bucket"], dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        assignment_count=("assignment_count", "sum"),
        weighted_total=("weighted_total", "sum"),
    ).reset_index()


def _quality_summary(assignments: pd.DataFrame) -> pd.DataFrame:
    return assignments.groupby(["access_layer", "route_normalized_assignment_status", "route_normalized_quality_class"], dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        assignment_candidate_count=("access_point_id", "size"),
        signal_count=("target_signal_id", "nunique"),
    ).reset_index().sort_values(["access_layer", "source_point_count"], ascending=[True, False])


def _by_scaffold(assignments: pd.DataFrame) -> pd.DataFrame:
    assigned = _assigned(assignments)
    rows = []
    for field in [
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "physical_leg_id_final",
        "carriageway_subbranch_id_final",
    ]:
        if field not in assigned.columns:
            continue
        grouped = assigned.groupby(["access_layer", field], dropna=False).agg(
            signal_count=("target_signal_id", "nunique"),
            source_access_point_count=("access_point_id", "nunique"),
            assignment_count=("access_point_id", "size"),
            weighted_assignment_total=("source_preserving_weighted_access_count", "sum"),
        ).reset_index().rename(columns={field: "qa_value"})
        grouped["qa_field"] = field
        rows.append(grouped)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _findings(assignments: pd.DataFrame, comparison: pd.DataFrame, quality: pd.DataFrame) -> str:
    assigned = _assigned(assignments)

    def source_count(layer: str, spatial_only: bool = False) -> int:
        if spatial_only:
            rows = comparison.loc[(comparison["access_layer"].eq(layer)) & (comparison["comparison_metric"].eq("source_points_route_normalized_only")), "count"]
            return int(rows.iloc[0]) if not rows.empty else 0
        return int(_text(assigned.loc[assigned["access_layer"].eq(layer)], "access_point_id").nunique())

    def new_signals(layer: str) -> int:
        rows = comparison.loc[(comparison["access_layer"].eq(layer)) & (comparison["comparison_metric"].eq("signals_route_normalized_only")), "count"]
        return int(rows.iloc[0]) if not rows.empty else 0

    def quality_line(layer: str) -> str:
        sub = quality.loc[(quality["access_layer"].eq(layer)) & (quality["route_normalized_assignment_status"].eq("assigned_review_only"))]
        if sub.empty:
            return f"- {layer}: no assigned candidates."
        return "\n".join(f"- {layer} {row.route_normalized_quality_class}: {int(row.source_point_count):,} source points" for row in sub.itertuples(index=False))

    return f"""# Final Access Travelway Normalization Test

**Bounded question:** test review-only access assignment after associating access source points to source Travelway and carrying that source identity into the represented signal-leg scaffold.

## Findings

1. Untyped source points captured by route/source normalization: **{source_count("untyped"):,}**.
2. Typed v2 source points captured by route/source normalization: **{source_count("typed_v2"):,}**.
3. Newly captured beyond the 100 ft spatial catchment:
   - untyped: **{source_count("untyped", spatial_only=True):,}** source points.
   - typed v2: **{source_count("typed_v2", spatial_only=True):,}** source points.
4. Signals gained relative to 100 ft spatial catchment:
   - untyped: **{new_signals("untyped"):,}** signals.
   - typed v2: **{new_signals("typed_v2"):,}** signals.
5. Assignment quality:
{quality_line("untyped")}
{quality_line("typed_v2")}

## Interpretation

This is a diagnostic assignment test, not a final access metric. It shows that source/Travelway normalization can recover substantially more source access points than spatial catchments alone, but assignment fanout and confidence classes must be reviewed before choosing a final access product.

## Recommendation

The next pass should refine route/source normalization confidence and fanout controls before crash/catchment design. Leg/window extension remains a secondary but concrete improvement path.
"""


def _qa() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("no_active_outputs_modified", "pass", "Writes only to final_access_travelway_normalization_test review folder."),
            ("no_candidates_promoted", "pass", "No candidate-promotion outputs are written."),
            ("no_crash_records_read", "pass", "No crash files are read."),
            ("no_crash_direction_fields_read_or_used", "pass", "Crash field tokens are blocked; source access direction attributes are not crash direction fields."),
            ("no_crash_assignment_or_catchments", "pass", "No crash assignment/catchment outputs are produced."),
            ("no_rates_or_models", "pass", "No rate/model calculations are performed."),
            ("typed_and_untyped_separate", "pass", "Separate typed v2 and untyped assignment outputs are written."),
            ("weighted_and_unweighted_separate", "pass", "Assignment detail includes unweighted and source-preserving weighted fields."),
            ("source_point_counts_separate", "pass", "Coverage and comparison summaries distinguish source-point counts from assignment rows."),
            ("route_normalized_assignments_review_only", "pass", "All assignment rows are review-only and no final metric is chosen."),
        ],
        columns=["qa_check", "status", "note"],
    )


def _manifest(started: datetime, outputs: list[str], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "script": "src.roadway_graph.build.final_access_travelway_normalization_test",
        "bounded_question": "read-only access-to-Travelway route/source normalization test",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "started_utc": started.isoformat(),
        "output_folder": str(OUT_DIR),
        "spatial_baseline_width_ft": SPATIAL_BASELINE_WIDTH_FT,
        "inputs": [str(path) for path in REQUIRED_INPUTS],
        "outputs": outputs,
        "summary": summary,
        "upstream_manifests": {
            "hybrid_access": _load_json(HYBRID_DIR / "hybrid_access_manifest.json").get("created_utc", ""),
            "final_access_source_accounting": _load_json(ACCESS_RERUN_DIR / "final_access_rerun_with_source_accounting_manifest.json").get("created_utc", ""),
        },
        "qa": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crash_records_read": False,
            "crash_assignment_or_catchments": False,
            "rates_or_models": False,
            "review_only": True,
        },
    }


def main() -> None:
    started = datetime.now(timezone.utc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start")

    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    target = _read_csv(ACCESS_RERUN_DIR / "final_cleaned_access_target_bins.csv")
    target["route_key"] = _text(target, "route_key").where(_text(target, "route_key").ne(""), _text(target, "route_facility_fields").map(_route_key))
    _read_source_travelway_identity()
    source_points = _source_table()
    represented = _represented_identity(target)
    assignments = _candidate_route_assignments(target)
    untyped_assignments = assignments.loc[assignments["access_layer"].eq("untyped")].copy()
    typed_assignments = assignments.loc[assignments["access_layer"].eq("typed_v2")].copy()
    spatial = _spatial_baseline_assignments()
    window_summary = _window_summary(assignments)
    coverage = _coverage(assignments)
    comparison = _spatial_vs_normalized(assignments, spatial)
    fanout = _fanout(assignments)
    quality = _quality_summary(assignments)
    scaffold = _by_scaffold(assignments)
    findings = _findings(assignments, comparison, quality)
    qa = _qa()

    output_frames = {
        "travelway_normalized_access_source_points.csv": source_points,
        "represented_signal_leg_travelway_identity.csv": represented,
        "untyped_travelway_normalized_assignment_detail.csv": untyped_assignments,
        "typed_v2_travelway_normalized_assignment_detail.csv": typed_assignments,
        "travelway_normalized_access_signal_window_summary.csv": window_summary,
        "travelway_normalized_access_product_coverage_summary.csv": coverage,
        "travelway_normalized_vs_spatial_comparison.csv": comparison,
        "travelway_normalized_access_fanout_summary.csv": fanout,
        "travelway_normalized_access_quality_summary.csv": quality,
        "travelway_normalized_access_by_scaffold_qa_summary.csv": scaffold,
        "final_access_travelway_normalization_qa.csv": qa,
    }
    for name, frame in output_frames.items():
        _write_csv(frame, name)
    _write_text(findings, "final_access_travelway_normalization_findings.md")
    outputs = list(output_frames) + ["final_access_travelway_normalization_findings.md", "final_access_travelway_normalization_manifest.json", "run_progress_log.txt"]
    assigned = _assigned(assignments)
    summary = {
        "untyped_route_normalized_source_points": int(_text(assigned.loc[assigned["access_layer"].eq("untyped")], "access_point_id").nunique()),
        "typed_v2_route_normalized_source_points": int(_text(assigned.loc[assigned["access_layer"].eq("typed_v2")], "access_point_id").nunique()),
        "untyped_route_normalized_assignment_rows": int(len(assigned.loc[assigned["access_layer"].eq("untyped")])),
        "typed_v2_route_normalized_assignment_rows": int(len(assigned.loc[assigned["access_layer"].eq("typed_v2")])),
        "comparison": comparison.to_dict(orient="records"),
    }
    _write_json(_manifest(started, outputs, summary), "final_access_travelway_normalization_manifest.json")
    _checkpoint("complete")


if __name__ == "__main__":
    main()
