from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .crs_utils import WORKING_CRS_AUTHORITY, apply_authoritative_crs, crs_matches, crs_to_string


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/speed_context_coverage_diagnostic")

SPEED_FILE = Path("artifacts/normalized/speed.parquet")
SPEED_JOIN_DIR = OUTPUT_ROOT / "review/current/speed_context_join"
BIN_SPEED_CONTEXT_FILE = SPEED_JOIN_DIR / "directional_bin_speed_context.csv"
SPEED_CANDIDATES_FILE = SPEED_JOIN_DIR / "speed_bin_match_candidates.csv"
SPEED_AMBIGUOUS_FILE = SPEED_JOIN_DIR / "speed_bin_ambiguous_matches.csv"
SPEED_JOIN_SUMMARY_FILE = SPEED_JOIN_DIR / "speed_context_join_summary.csv"

USABLE_BINS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_scaffold_qa/directional_scaffold_prototype_usable_bins_50ft.csv"
CATCHMENT_INDEX_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_index.csv"
CATCHMENT_POLYGONS_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_polygons.geojson"
CATCHMENT_CRS_METADATA_FILE = OUTPUT_ROOT / "review/current/reference_signal_directional_bin_catchments/directional_bin_catchment_crs_metadata.json"

STAGING_SCHEMA_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_schema.csv"
STAGING_CRS_SANITY_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_crs_sanity.csv"
STAGING_FIELD_ROLES_FILE = OUTPUT_ROOT / "review/current/posted_speed_source_staging/posted_speed_field_role_candidates.csv"

FEET_TO_METERS = 0.3048
CAR_SPEED_FIELD = "CAR_SPEED_LIMIT"
TRUCK_SPEED_FIELD = "TRUCK_SPEED_LIMIT"


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _distance_band(distance_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([distance_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    if value <= 25:
        return "0_25ft"
    if value <= 50:
        return "25_50ft"
    if value <= 100:
        return "50_100ft"
    if value <= 250:
        return "100_250ft"
    if value <= 500:
        return "250_500ft"
    return "over_500ft"


def _midpoint_band(midpoint_ft: Any) -> str:
    value = pd.to_numeric(pd.Series([midpoint_ft]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "unknown"
    lower = int(value // 250) * 250
    upper = lower + 250
    return f"{lower}_{upper}ft"


def _load_speed() -> gpd.GeoDataFrame:
    speed = gpd.read_parquet(SPEED_FILE)
    if speed.crs is None:
        raise ValueError("Speed source has no CRS; rerun posted speed staging before diagnostics.")
    speed = speed.to_crs(WORKING_CRS_AUTHORITY).reset_index(names="speed_source_index")
    speed["speed_geometry_is_null"] = speed.geometry.isna()
    speed["speed_geometry_is_valid"] = speed.geometry.notna() & speed.geometry.is_valid
    return speed


def _load_bin_context() -> pd.DataFrame:
    bin_context = _read_csv(BIN_SPEED_CONTEXT_FILE)
    usable = _read_csv(USABLE_BINS_FILE)
    enrich_columns = [
        "reference_directional_bin_id",
        "base_segment_id",
        "far_anchor_id",
        "travel_direction",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
    ]
    bin_context = bin_context.merge(usable[[c for c in enrich_columns if c in usable.columns]], on="reference_directional_bin_id", how="left")
    bin_context["bin_midpoint_ft_from_reference_signal"] = _num(bin_context, "bin_midpoint_ft_from_reference_signal")
    bin_context["missing_speed"] = bin_context["speed_context_status"].eq("no_speed_nearby")
    return bin_context


def _load_missing_catchments(missing_bins: pd.DataFrame) -> gpd.GeoDataFrame:
    catchment_index = _read_csv(CATCHMENT_INDEX_FILE)
    missing_ids = set(missing_bins["reference_directional_bin_id"].astype(str))
    missing_catchment_ids = set(
        catchment_index.loc[
            catchment_index["reference_directional_bin_id"].astype(str).isin(missing_ids) & catchment_index["catchment_status"].eq("usable"),
            "catchment_id",
        ].astype(str)
    )
    catchments = gpd.read_file(CATCHMENT_POLYGONS_FILE)
    catchments, _, _ = apply_authoritative_crs(catchments, metadata_path=CATCHMENT_CRS_METADATA_FILE)
    catchments = catchments.loc[catchments["catchment_id"].astype(str).isin(missing_catchment_ids)].copy()
    keep = ["catchment_id", "reference_directional_bin_id", "geometry"]
    return catchments[[c for c in keep if c in catchments.columns]].copy()


def _missing_nearest_speed_distance(speed: gpd.GeoDataFrame, missing_bins: pd.DataFrame) -> pd.DataFrame:
    missing_bins = missing_bins.drop(
        columns=[
            "nearest_speed_distance_ft",
            "nearest_speed_record_id",
            "nearest_speed_source_index",
            "nearest_car_speed_limit",
            "nearest_truck_speed_limit",
        ],
        errors="ignore",
    ).copy()
    missing_catchments = _load_missing_catchments(missing_bins)
    valid_speed = speed.loc[speed["speed_geometry_is_valid"]].copy()
    if missing_catchments.empty or valid_speed.empty:
        out = missing_bins.copy()
        out["nearest_speed_distance_ft"] = pd.NA
        out["nearest_speed_distance_band"] = "unknown"
        return out
    speed_keep = ["speed_source_index", CAR_SPEED_FIELD, TRUCK_SPEED_FIELD, "geometry"]
    nearest = gpd.sjoin_nearest(
        missing_catchments,
        valid_speed[[c for c in speed_keep if c in valid_speed.columns]],
        how="left",
        distance_col="nearest_speed_distance_m",
    )
    nearest = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    nearest["nearest_speed_distance_ft"] = pd.to_numeric(nearest["nearest_speed_distance_m"], errors="coerce") / FEET_TO_METERS
    nearest = nearest.sort_values(["reference_directional_bin_id", "nearest_speed_distance_ft", "speed_source_index"])
    nearest = nearest.groupby("reference_directional_bin_id", dropna=False).head(1)
    nearest = nearest[
        [
            "reference_directional_bin_id",
            "speed_source_index",
            CAR_SPEED_FIELD,
            TRUCK_SPEED_FIELD,
            "nearest_speed_distance_ft",
        ]
    ].rename(
        columns={
            "speed_source_index": "nearest_speed_source_index",
            CAR_SPEED_FIELD: "nearest_car_speed_limit",
            TRUCK_SPEED_FIELD: "nearest_truck_speed_limit",
        }
    )
    out = missing_bins.merge(nearest, on="reference_directional_bin_id", how="left")
    out["nearest_speed_distance_ft"] = pd.to_numeric(out["nearest_speed_distance_ft"], errors="coerce").round(3)
    out["nearest_speed_distance_band"] = out["nearest_speed_distance_ft"].map(_distance_band)
    return out


def _missing_by_group(missing_distance: pd.DataFrame, columns: list[str], output_count_name: str = "missing_bin_count") -> pd.DataFrame:
    if missing_distance.empty:
        return pd.DataFrame(columns=[*columns, output_count_name])
    return (
        missing_distance.groupby(columns, dropna=False)
        .agg(
            **{
                output_count_name: ("reference_directional_bin_id", "nunique"),
                "median_nearest_speed_distance_ft": ("nearest_speed_distance_ft", lambda s: round(float(pd.to_numeric(s, errors="coerce").median()), 3) if pd.to_numeric(s, errors="coerce").notna().any() else pd.NA),
                "bins_with_nearest_speed_within_100ft": ("nearest_speed_distance_ft", lambda s: int(pd.to_numeric(s, errors="coerce").le(100).sum())),
                "bins_with_nearest_speed_over_500ft": ("nearest_speed_distance_ft", lambda s: int(pd.to_numeric(s, errors="coerce").gt(500).sum())),
            }
        )
        .reset_index()
        .sort_values(output_count_name, ascending=False)
    )


def _coverage_comparison(bin_context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for status, group in bin_context.groupby("speed_context_status", dropna=False):
        rows.append(
            {
                "diagnostic_group": status,
                "bin_count": group["reference_directional_bin_id"].nunique(),
                "share_of_main_bins": round(group["reference_directional_bin_id"].nunique() / max(len(bin_context), 1), 6),
                "median_bin_midpoint_ft": round(float(pd.to_numeric(group["bin_midpoint_ft_from_reference_signal"], errors="coerce").median()), 3),
            }
        )
    return pd.DataFrame(rows).sort_values("bin_count", ascending=False)


def _ambiguous_conflict_diagnostic(candidates: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    ambiguous_bin_ids = set(bin_context.loc[bin_context["speed_context_status"].eq("ambiguous_multiple_speed_values"), "reference_directional_bin_id"].astype(str))
    work = candidates.loc[candidates["reference_directional_bin_id"].astype(str).isin(ambiguous_bin_ids)].copy()
    if work.empty:
        return pd.DataFrame()
    rows = []
    for bin_id, group in work.groupby("reference_directional_bin_id", dropna=False):
        car_values = pd.to_numeric(group[CAR_SPEED_FIELD], errors="coerce").dropna().sort_values().unique().tolist() if CAR_SPEED_FIELD in group.columns else []
        truck_values = pd.to_numeric(group[TRUCK_SPEED_FIELD], errors="coerce").dropna().sort_values().unique().tolist() if TRUCK_SPEED_FIELD in group.columns else []
        all_values = sorted(set(car_values + truck_values))
        spread = max(all_values) - min(all_values) if all_values else pd.NA
        rows.append(
            {
                "reference_directional_bin_id": bin_id,
                "candidate_record_count": group["speed_source_index"].nunique() if "speed_source_index" in group.columns else len(group),
                "distinct_car_speed_count": len(car_values),
                "distinct_car_speed_values": "|".join(_format_speed(value) for value in car_values),
                "distinct_truck_speed_count": len(truck_values),
                "distinct_truck_speed_values": "|".join(_format_speed(value) for value in truck_values),
                "speed_spread_mph": spread,
                "severe_conflict_spread_ge_15mph": bool(pd.notna(spread) and spread >= 15),
            }
        )
    out = pd.DataFrame(rows)
    enrich = bin_context[
        [
            "reference_directional_bin_id",
            "reference_signal_id",
            "roadway_representation_type",
            "signal_relative_direction",
            "distance_window",
            "far_anchor_type",
            "bin_midpoint_ft_from_reference_signal",
        ]
    ]
    out = out.merge(enrich, on="reference_directional_bin_id", how="left")
    return out.sort_values(["severe_conflict_spread_ge_15mph", "speed_spread_mph", "candidate_record_count"], ascending=[False, False, False])


def _format_speed(value: Any) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric) and float(numeric).is_integer():
        return str(int(numeric))
    return str(value)


def _paired_pseudo_direction_qa(bin_context: pd.DataFrame) -> pd.DataFrame:
    work = bin_context.loc[bin_context["roadway_representation_type"].eq("undivided_centerline_pseudo_direction")].copy()
    if work.empty:
        return pd.DataFrame()
    group_columns = ["reference_signal_id", "far_anchor_id", "base_segment_id", "bin_index_from_reference_signal"]
    rows = []
    for keys, group in work.groupby(group_columns, dropna=False):
        if group["reference_directional_bin_id"].nunique() < 2:
            continue
        statuses = sorted(group["speed_context_status"].astype(str).unique().tolist())
        methods = sorted(group["speed_context_method"].astype(str).unique().tolist())
        car_values = sorted(pd.to_numeric(group["dominant_car_speed_limit"], errors="coerce").dropna().unique().tolist())
        directions = sorted(group["signal_relative_direction"].astype(str).unique().tolist())
        missing_count = int(group["missing_speed"].sum())
        rows.append(
            {
                "reference_signal_id": keys[0],
                "far_anchor_id": keys[1],
                "base_segment_id": keys[2],
                "bin_index_from_reference_signal": keys[3],
                "paired_bin_count": group["reference_directional_bin_id"].nunique(),
                "signal_relative_directions": "|".join(directions),
                "speed_context_statuses": "|".join(statuses),
                "speed_context_methods": "|".join(methods),
                "dominant_car_speed_values": "|".join(_format_speed(value) for value in car_values),
                "missing_speed_bin_count": missing_count,
                "same_speed_context_across_pair": len(statuses) == 1 and len(car_values) <= 1,
                "missing_differs_within_pair": missing_count > 0 and missing_count < group["reference_directional_bin_id"].nunique(),
            }
        )
    return pd.DataFrame(rows)


def _summary(
    bin_context: pd.DataFrame,
    missing_distance: pd.DataFrame,
    ambiguity: pd.DataFrame,
    paired_qa: pd.DataFrame,
    speed: gpd.GeoDataFrame,
) -> pd.DataFrame:
    missing_total = int(bin_context["missing_speed"].sum())
    within_100 = int(pd.to_numeric(missing_distance["nearest_speed_distance_ft"], errors="coerce").le(100).sum()) if not missing_distance.empty else 0
    within_250 = int(pd.to_numeric(missing_distance["nearest_speed_distance_ft"], errors="coerce").le(250).sum()) if not missing_distance.empty else 0
    over_500 = int(pd.to_numeric(missing_distance["nearest_speed_distance_ft"], errors="coerce").gt(500).sum()) if not missing_distance.empty else 0
    severe = int(ambiguity["severe_conflict_spread_ge_15mph"].astype(bool).sum()) if not ambiguity.empty else 0
    paired_rows = len(paired_qa) if not paired_qa.empty else 0
    paired_inconsistent = int((~paired_qa["same_speed_context_across_pair"].astype(bool)).sum()) if not paired_qa.empty else 0
    rows = [
        {"metric": "main_context_bins", "value": "", "count": len(bin_context)},
        {"metric": "missing_speed_bins_total", "value": "", "count": missing_total},
        {"metric": "missing_speed_share", "value": round(missing_total / max(len(bin_context), 1), 6), "count": ""},
        {"metric": "missing_bins_nearest_speed_within_100ft", "value": "", "count": within_100},
        {"metric": "missing_bins_nearest_speed_within_250ft", "value": "", "count": within_250},
        {"metric": "missing_bins_nearest_speed_over_500ft", "value": "", "count": over_500},
        {"metric": "ambiguous_conflicting_speed_bins", "value": "", "count": len(ambiguity)},
        {"metric": "severe_conflict_bins_spread_ge_15mph", "value": "", "count": severe},
        {"metric": "paired_pseudo_direction_groups_checked", "value": "", "count": paired_rows},
        {"metric": "paired_pseudo_direction_groups_inconsistent", "value": "", "count": paired_inconsistent},
        {"metric": "speed_source_crs", "value": crs_to_string(speed.crs), "count": ""},
        {"metric": "speed_source_crs_matches_working_crs", "value": crs_matches(speed.crs, WORKING_CRS_AUTHORITY), "count": ""},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "speed_scaffold_assignment_access_logic_changed", "value": False, "count": ""},
    ]
    return pd.DataFrame(rows)


def _findings(
    summary: pd.DataFrame,
    missing_by_band: pd.DataFrame,
    missing_by_representation: pd.DataFrame,
    missing_by_window: pd.DataFrame,
    top_signals: pd.DataFrame,
    ambiguity: pd.DataFrame,
    paired_qa: pd.DataFrame,
    outputs: dict[str, Path],
) -> str:
    def count(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["count"]

    def value(metric: str) -> Any:
        row = summary.loc[summary["metric"].eq(metric)]
        return "" if row.empty else row.iloc[0]["value"]

    band_lines = [
        f"- {row.nearest_speed_distance_band}: {int(row.missing_bin_count)} bins"
        for row in missing_by_band.itertuples(index=False)
    ]
    rep_lines = [
        f"- {row.roadway_representation_type}: {int(row.missing_bin_count)} bins"
        for row in missing_by_representation.itertuples(index=False)
    ]
    window_lines = [
        f"- {row.distance_window}: {int(row.missing_bin_count)} bins"
        for row in missing_by_window.itertuples(index=False)
    ]
    signal_lines = [
        f"- {row.reference_signal_id}: {int(row.missing_bin_count)} bins"
        for row in top_signals.head(10).itertuples(index=False)
    ]
    severe_count = int(ambiguity["severe_conflict_spread_ge_15mph"].astype(bool).sum()) if not ambiguity.empty else 0
    paired_inconsistent = int((~paired_qa["same_speed_context_across_pair"].astype(bool)).sum()) if not paired_qa.empty else 0
    mostly_near = int(count("missing_bins_nearest_speed_within_100ft") or 0) > int(count("missing_speed_bins_total") or 0) / 2
    diagnosis = (
        "Most missing bins are near posted-speed lines, which points toward join-method geometry/tolerance issues."
        if mostly_near
        else "Most missing bins are not within 100 ft of posted-speed lines, which points toward source coverage, geometry extent, or route representation gaps."
    )
    if int(count("missing_bins_nearest_speed_within_100ft") or 0) == 0:
        near_fix = "No missing bins are within 100 ft of a posted-speed line, so a simple 100 ft nearest-line tolerance increase is not the primary fix."
    else:
        near_fix = "Review bins with nearest speed line within 100 ft but no speed context; these are the highest-yield join-method failure candidates."
    return "\n".join(
        [
            "# Speed Context Coverage Diagnostic Findings",
            "",
            "## Bounded Question",
            "",
            "Diagnose speed-context coverage gaps and conflicts without changing speed joins, roadway scaffold, catchments, crash assignment, access context, or upstream/downstream labels.",
            "",
            "## Key Findings",
            "",
            f"- missing speed bins total: {count('missing_speed_bins_total')}",
            f"- missing speed share: {value('missing_speed_share')}",
            f"- missing bins within 100 ft of a posted-speed line: {count('missing_bins_nearest_speed_within_100ft')}",
            f"- missing bins within 250 ft of a posted-speed line: {count('missing_bins_nearest_speed_within_250ft')}",
            f"- missing bins over 500 ft from a posted-speed line: {count('missing_bins_nearest_speed_over_500ft')}",
            f"- diagnostic interpretation: {diagnosis}",
            f"- ambiguous/conflicting speed bins: {count('ambiguous_conflicting_speed_bins')}",
            f"- severe conflicts with spread >= 15 mph: {severe_count}",
            f"- paired pseudo-direction groups checked: {count('paired_pseudo_direction_groups_checked')}",
            f"- paired pseudo-direction groups with inconsistent speed context: {paired_inconsistent}",
            "",
            "## Missing Speed Distance Bands",
            "",
            *band_lines,
            "",
            "## Missing By Roadway Representation",
            "",
            *rep_lines,
            "",
            "## Missing By Distance Window",
            "",
            *window_lines,
            "",
            "## Top Missing-Speed Reference Signals",
            "",
            *signal_lines,
            "",
            "## Boundary Checks",
            "",
            f"- crash direction fields read or used: {value('crash_direction_fields_read_or_used')}",
            f"- speed/scaffold/assignment/access logic changed: {value('speed_scaffold_assignment_access_logic_changed')}",
            f"- speed source CRS: {value('speed_source_crs')}",
            f"- speed source CRS matches working CRS: {value('speed_source_crs_matches_working_crs')}",
            "",
            "## Files Created",
            "",
            *[f"- `{path}`" for path in outputs.values()],
            "",
            "## Recommended Fix Options",
            "",
            f"- {near_fix}",
            "- Review the 100-250 ft and 250-500 ft missing-bin groups separately from bins over 500 ft; those groups are more plausible geometry/tolerance candidates.",
            "- Inspect severe conflicting bins before promoting a dominant-speed rule.",
            "- For undivided pseudo-direction inconsistencies, consider pairing-aware inheritance only after confirming shared geometry and source route alignment.",
            "- Keep source coverage gaps separate from join-method failures in the next speed join revision.",
            "",
        ]
    )


def build_speed_context_coverage_diagnostic(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR

    speed = _load_speed()
    bin_context = _load_bin_context()
    candidates = _read_csv(SPEED_CANDIDATES_FILE)
    _ = _read_csv(SPEED_AMBIGUOUS_FILE)
    _ = _read_csv(SPEED_JOIN_SUMMARY_FILE)
    if STAGING_SCHEMA_FILE.exists():
        _ = _read_csv(STAGING_SCHEMA_FILE)
    if STAGING_CRS_SANITY_FILE.exists():
        _ = _read_csv(STAGING_CRS_SANITY_FILE)
    if STAGING_FIELD_ROLES_FILE.exists():
        _ = _read_csv(STAGING_FIELD_ROLES_FILE)

    missing_bins = bin_context.loc[bin_context["missing_speed"]].copy()
    missing_distance = _missing_nearest_speed_distance(speed, missing_bins)
    missing_by_band = _missing_by_group(missing_distance, ["nearest_speed_distance_band"])
    band_order = ["0_25ft", "25_50ft", "50_100ft", "100_250ft", "250_500ft", "over_500ft", "unknown"]
    missing_by_band["nearest_speed_distance_band"] = pd.Categorical(missing_by_band["nearest_speed_distance_band"], categories=band_order, ordered=True)
    missing_by_band = missing_by_band.sort_values("nearest_speed_distance_band").reset_index(drop=True)
    missing_by_band["nearest_speed_distance_band"] = missing_by_band["nearest_speed_distance_band"].astype(str)
    missing_by_signal = _missing_by_group(missing_distance, ["reference_signal_id"])
    missing_by_representation = _missing_by_group(missing_distance, ["roadway_representation_type"])
    missing_by_direction = _missing_by_group(missing_distance, ["signal_relative_direction"])
    missing_by_far_anchor = _missing_by_group(missing_distance, ["far_anchor_type"])
    missing_by_window = _missing_by_group(missing_distance, ["distance_window"])
    missing_distance["bin_midpoint_250ft_band"] = missing_distance["bin_midpoint_ft_from_reference_signal"].map(_midpoint_band)
    missing_by_midpoint = _missing_by_group(missing_distance, ["bin_midpoint_250ft_band"])
    top_signals = missing_by_signal.head(25).copy()
    coverage_comparison = _coverage_comparison(bin_context)
    ambiguity = _ambiguous_conflict_diagnostic(candidates, bin_context)
    severe = ambiguity.loc[ambiguity["severe_conflict_spread_ge_15mph"].astype(bool)].copy() if not ambiguity.empty else pd.DataFrame()
    paired_qa = _paired_pseudo_direction_qa(bin_context)
    summary = _summary(bin_context, missing_distance, ambiguity, paired_qa, speed)

    outputs = {
        "summary_csv": out_dir / "speed_context_coverage_diagnostic_summary.csv",
        "missing_nearest_csv": out_dir / "speed_missing_bins_nearest_speed_distance.csv",
        "missing_by_distance_band_csv": out_dir / "speed_missing_by_distance_band.csv",
        "missing_by_reference_signal_csv": out_dir / "speed_missing_by_reference_signal.csv",
        "missing_by_roadway_representation_csv": out_dir / "speed_missing_by_roadway_representation.csv",
        "missing_by_signal_relative_direction_csv": out_dir / "speed_missing_by_signal_relative_direction.csv",
        "missing_by_far_anchor_type_csv": out_dir / "speed_missing_by_far_anchor_type.csv",
        "missing_by_context_window_csv": out_dir / "speed_missing_by_context_window.csv",
        "missing_by_bin_distance_csv": out_dir / "speed_missing_by_bin_distance_from_reference_signal.csv",
        "missing_top_reference_signals_csv": out_dir / "speed_missing_top_reference_signals.csv",
        "context_status_comparison_csv": out_dir / "speed_context_status_comparison.csv",
        "ambiguous_conflict_diagnostic_csv": out_dir / "speed_ambiguous_conflict_diagnostic.csv",
        "ambiguous_severe_conflicts_csv": out_dir / "speed_ambiguous_severe_conflicts.csv",
        "paired_pseudo_direction_consistency_qa_csv": out_dir / "speed_paired_pseudo_direction_consistency_qa.csv",
        "findings_md": out_dir / "speed_context_coverage_diagnostic_findings.md",
        "manifest_json": out_dir / "speed_context_coverage_diagnostic_manifest.json",
    }
    _write_csv(summary, outputs["summary_csv"])
    _write_csv(missing_distance, outputs["missing_nearest_csv"])
    _write_csv(missing_by_band, outputs["missing_by_distance_band_csv"])
    _write_csv(missing_by_signal, outputs["missing_by_reference_signal_csv"])
    _write_csv(missing_by_representation, outputs["missing_by_roadway_representation_csv"])
    _write_csv(missing_by_direction, outputs["missing_by_signal_relative_direction_csv"])
    _write_csv(missing_by_far_anchor, outputs["missing_by_far_anchor_type_csv"])
    _write_csv(missing_by_window, outputs["missing_by_context_window_csv"])
    _write_csv(missing_by_midpoint, outputs["missing_by_bin_distance_csv"])
    _write_csv(top_signals, outputs["missing_top_reference_signals_csv"])
    _write_csv(coverage_comparison, outputs["context_status_comparison_csv"])
    _write_csv(ambiguity, outputs["ambiguous_conflict_diagnostic_csv"])
    _write_csv(severe, outputs["ambiguous_severe_conflicts_csv"])
    _write_csv(paired_qa, outputs["paired_pseudo_direction_consistency_qa_csv"])
    _write_text(_findings(summary, missing_by_band, missing_by_representation, missing_by_window, top_signals, ambiguity, paired_qa, outputs), outputs["findings_md"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "read-only speed context coverage diagnostic",
        "crash_direction_fields_read_or_used": False,
        "speed_join_logic_changed": False,
        "scaffold_catchment_assignment_access_logic_changed": False,
        "aadt_join_implemented": False,
        "inputs": {
            "speed": str(SPEED_FILE),
            "directional_bin_speed_context": str(BIN_SPEED_CONTEXT_FILE),
            "speed_bin_match_candidates": str(SPEED_CANDIDATES_FILE),
            "speed_bin_ambiguous_matches": str(SPEED_AMBIGUOUS_FILE),
            "speed_context_join_summary": str(SPEED_JOIN_SUMMARY_FILE),
            "usable_bins": str(USABLE_BINS_FILE),
            "catchment_index": str(CATCHMENT_INDEX_FILE),
            "catchment_polygons": str(CATCHMENT_POLYGONS_FILE),
            "staging_schema": str(STAGING_SCHEMA_FILE),
            "staging_crs_sanity": str(STAGING_CRS_SANITY_FILE),
            "staging_field_roles": str(STAGING_FIELD_ROLES_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()},
        "summary": summary.to_dict(orient="records"),
        "coverage_comparison": coverage_comparison.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest_json"])
    return {key: str(path) for key, path in outputs.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose posted-speed context coverage gaps without changing joins.")
    parser.parse_args()
    outputs = build_speed_context_coverage_diagnostic()
    for key, value in outputs.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
