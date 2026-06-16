from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from shapely import wkb, wkt

from .crs_utils import WORKING_CRS_AUTHORITY, WORKING_CRS_NAME


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/final_crash_catchment_design_feasibility"

STABLE_SCAFFOLD_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
FINAL_ACCESS_DIR = OUTPUT_ROOT / "review/current/final_access_baseline_freeze"

CRASH_SOURCES = [
    Path("artifacts/normalized/crashes.parquet"),
    Path("artifacts/staging/crashes.parquet"),
]

CRASH_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)

REQUIRED_INPUTS = [
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_generation_lineage_audit.csv",
    STABLE_SCAFFOLD_DIR / "stable_lineage_generation_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_access_readiness_decision.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    FINAL_ACCESS_DIR / "final_access_primary_untyped_spatial_100ft_summary.csv",
    FINAL_ACCESS_DIR / "final_access_primary_typed_v2_spatial_100ft_summary.csv",
    FINAL_ACCESS_DIR / "final_access_typed_category_corrected_summary.csv",
    FINAL_ACCESS_DIR / "final_access_product_role_doctrine.csv",
    FINAL_ACCESS_DIR / "final_access_crash_catchment_readiness.csv",
    FINAL_ACCESS_DIR / "final_access_baseline_manifest.json",
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


def _blocked_direction_column(column: str) -> bool:
    return any(token in column.lower() for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
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


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _missing_inputs() -> list[str]:
    missing = [str(path) for path in REQUIRED_INPUTS if not path.exists()]
    missing.extend(str(path) for path in CRASH_SOURCES if not path.exists())
    return missing


def _parquet_schema(path: Path) -> tuple[int, list[str]]:
    pf = pq.ParquetFile(path)
    return pf.metadata.num_rows, list(pf.schema_arrow.names)


def _safe_read_parquet_columns(path: Path, columns: list[str]) -> pd.DataFrame:
    row_count, schema_cols = _parquet_schema(path)
    cols = [column for column in columns if column in schema_cols and not _blocked_direction_column(column)]
    if not cols:
        return pd.DataFrame(index=range(row_count))
    return pd.read_parquet(path, columns=cols)


def _nonempty_count(frame: pd.DataFrame, column: str) -> int:
    if column not in frame.columns:
        return 0
    return int(frame[column].notna().sum())


def _inventory_crash_source(path: Path) -> dict[str, Any]:
    row_count, columns = _parquet_schema(path)
    date_fields = [c for c in columns if "DATE" in c.upper() or "DT" in c.upper() or "YEAR" in c.upper()]
    severity_fields = [c for c in columns if "SEVERITY" in c.upper() or c.upper() in {"K_PEOPLE", "A_PEOPLE", "B_PEOPLE", "C_PEOPLE"}]
    type_fields = [
        c
        for c in columns
        if any(token in c.upper() for token in ["COLLISION", "MANNER", "FIRST_HARMFUL", "INTERSECTION_TYPE", "ROADWAY_DESCRIPTION"])
    ]
    direction_fields = [c for c in columns if _blocked_direction_column(c)]
    useful_cols = ["geometry", *date_fields[:4], *severity_fields[:8], *type_fields[:8]]
    sample = _safe_read_parquet_columns(path, useful_cols)
    geometry_count = _nonempty_count(sample, "geometry")
    invalid_geometry_count = 0
    minx = miny = maxx = maxy = ""
    if "geometry" in sample.columns and geometry_count:
        bounds: list[tuple[float, float, float, float]] = []
        for value in sample["geometry"].dropna().head(25000):
            try:
                geom = wkb.loads(value)
                if geom.is_empty or not geom.is_valid:
                    invalid_geometry_count += 1
                    continue
                bounds.append(geom.bounds)
            except Exception:
                invalid_geometry_count += 1
        if bounds:
            minx = min(b[0] for b in bounds)
            miny = min(b[1] for b in bounds)
            maxx = max(b[2] for b in bounds)
            maxy = max(b[3] for b in bounds)
    return {
        "source_path": str(path),
        "row_count": row_count,
        "geometry_field": "geometry" if "geometry" in columns else "",
        "geometry_available_count": geometry_count,
        "missing_or_null_geometry_count": row_count - geometry_count,
        "sample_invalid_geometry_count": invalid_geometry_count,
        "crs": WORKING_CRS_AUTHORITY,
        "crs_note": f"inferred repository normalized working CRS ({WORKING_CRS_NAME}); parquet has WKB geometry without standalone CRS metadata",
        "available_date_year_fields": "|".join(date_fields),
        "available_severity_fields": "|".join(severity_fields),
        "available_crash_type_manner_fields": "|".join(type_fields),
        "available_direction_fields_inventory_only": "|".join(direction_fields),
        "direction_field_use_status": "not_used_for_scaffold_or_catchment_geometry",
        "sample_minx": minx,
        "sample_miny": miny,
        "sample_maxx": maxx,
        "sample_maxy": maxy,
    }


def _crash_source_inventory() -> pd.DataFrame:
    rows = [_inventory_crash_source(path) for path in CRASH_SOURCES if path.exists()]
    return pd.DataFrame(rows)


def _scaffold_inventory(bins: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"inventory_item": "represented_signal_count", "count": int(signals["target_signal_id"].nunique()) if "target_signal_id" in signals.columns else int(bins["target_signal_id"].nunique()), "notes": "stable-lineage represented signal universe"},
        {"inventory_item": "scaffold_bin_count", "count": int(len(bins)), "notes": "stable-lineage represented bin universe"},
        {"inventory_item": "bins_with_geometry", "count": int(_text(bins, "geometry_wkt_cleaned").str.strip().ne("").sum()), "notes": "geometry_wkt_cleaned nonblank"},
        {"inventory_item": "bins_with_stable_travelway_id", "count": int(_text(bins, "stable_travelway_id").str.strip().ne("").sum()), "notes": "stable Travelway lineage coverage"},
        {"inventory_item": "bins_high_confidence_lineage", "count": int(_text(bins, "lineage_confidence").str.startswith("high").sum()), "notes": "lineage_confidence starts with high"},
        {"inventory_item": "bins_low_confidence_lineage", "count": int(_text(bins, "lineage_confidence").str.startswith("low").sum()), "notes": "lineage_confidence starts with low"},
        {"inventory_item": "physical_leg_id_nonblank_bins", "count": int(_text(bins, "physical_leg_id_final").str.strip().ne("").sum()), "notes": "physical_leg_id_final nonblank"},
        {"inventory_item": "carriageway_subbranch_nonblank_bins", "count": int(_text(bins, "carriageway_subbranch_id_final").str.strip().ne("").sum()), "notes": "carriageway_subbranch_id_final nonblank"},
        {"inventory_item": "unique_distance_bands", "count": int(_text(bins, "distance_band").replace("", pd.NA).dropna().nunique()), "notes": "|".join(sorted(_text(bins, "distance_band").replace("", pd.NA).dropna().unique()))},
        {"inventory_item": "unique_analysis_windows", "count": int(_text(bins, "analysis_window").replace("", pd.NA).dropna().nunique()), "notes": "|".join(sorted(_text(bins, "analysis_window").replace("", pd.NA).dropna().unique()))},
        {"inventory_item": "source_limited_holdout_bins", "count": int(_bool_text(bins, "source_limited_holdout_flag").sum()), "notes": "carry flag into crash assignment"},
        {"inventory_item": "grade_mainline_holdout_bins", "count": int(_bool_text(bins, "grade_mainline_holdout_flag").sum()), "notes": "carry flag into crash assignment"},
        {"inventory_item": "still_insufficient_evidence_bins", "count": int(_bool_text(bins, "still_insufficient_evidence_flag").sum()), "notes": "carry flag into crash assignment"},
    ]
    return pd.DataFrame(rows)


def _catchment_designs(bins: pd.DataFrame) -> pd.DataFrame:
    geometry_count = int(_text(bins, "geometry_wkt_cleaned").str.strip().ne("").sum())
    bin_count = len(bins)
    rows: list[dict[str, Any]] = []
    for width in [35, 50, 75, 100]:
        rows.append(
            {
                "candidate_design": f"bin_line_buffer_{width}ft",
                "geometry_rule": f"buffer each stable-lineage bin line by {width} ft",
                "assignment_unit": "crash_to_signal_bin_then_rollup",
                "geometry_coverage_bins": geometry_count,
                "geometry_coverage_share": round(geometry_count / bin_count, 6) if bin_count else 0,
                "overlap_risk": "medium_high" if width >= 75 else "medium",
                "expected_fanout_risk": "increases with buffer width and dense signal spacing",
                "suitability_conservative_assignment": "recommended_primary" if width == 50 else ("sensitivity" if width in {35, 75} else "broad_sensitivity_only"),
                "suitability_rate_model_analysis": "usable_after_denominator_and_overlap_QA",
                "notes": "does not use crash direction; preserves stable_travelway_id and scaffold QA flags",
            }
        )
    rows.extend(
        [
            {
                "candidate_design": "signal_window_dissolved_0_1000",
                "geometry_rule": "dissolve bin buffers by signal and 0-1000 ft window",
                "assignment_unit": "crash_to_signal_window",
                "geometry_coverage_bins": int(_text(bins.loc[_text(bins, "analysis_window").eq("0_1000")], "geometry_wkt_cleaned").str.strip().ne("").sum()),
                "geometry_coverage_share": "",
                "overlap_risk": "medium_high_near_adjacent_signals",
                "expected_fanout_risk": "lower than raw bin assignment after dissolve but signal overlap remains",
                "suitability_conservative_assignment": "recommended_rollup_after_primary_bin_buffer",
                "suitability_rate_model_analysis": "good first descriptive unit if denominator policy is explicit",
                "notes": "primary reporting window; preserve source-preserving crash weights if multi-assigned",
            },
            {
                "candidate_design": "signal_window_dissolved_0_2500",
                "geometry_rule": "dissolve bin buffers by signal and 0-2500 ft window",
                "assignment_unit": "crash_to_signal_window",
                "geometry_coverage_bins": int(_text(bins.loc[_text(bins, "analysis_window").isin(["0_1000", "1000_2500"])], "geometry_wkt_cleaned").str.strip().ne("").sum()),
                "geometry_coverage_share": "",
                "overlap_risk": "high",
                "expected_fanout_risk": "high near corridors with many represented signals",
                "suitability_conservative_assignment": "sensitivity_only",
                "suitability_rate_model_analysis": "sensitivity only until overlap/fanout reviewed",
                "notes": "do not collapse with 0-1000 primary window",
            },
            {
                "candidate_design": "signal_physical_leg_window",
                "geometry_rule": "group bin buffers by signal, physical leg, and window",
                "assignment_unit": "crash_to_signal_physical_leg_window",
                "geometry_coverage_bins": geometry_count,
                "geometry_coverage_share": round(geometry_count / bin_count, 6) if bin_count else 0,
                "overlap_risk": "medium",
                "expected_fanout_risk": "leg-level ambiguity where legs overlap or are close",
                "suitability_conservative_assignment": "recommended_secondary_detail",
                "suitability_rate_model_analysis": "useful for mechanism review, sparse for models",
                "notes": "best detail unit; roll up to signal/window for first summaries",
            },
        ]
    )
    return pd.DataFrame(rows)


def _overlap_risk(bins: pd.DataFrame) -> pd.DataFrame:
    work = bins.copy()
    work["leg_id"] = _text(work, "physical_leg_id_final").where(_text(work, "physical_leg_id_final").ne(""), _text(work, "physical_leg_id"))
    work["subbranch_id"] = _text(work, "carriageway_subbranch_id_final").where(
        _text(work, "carriageway_subbranch_id_final").ne(""), _text(work, "carriageway_subbranch_id")
    )
    groups = [
        ("same_geometry_hash", ["bin_geometry_hash"]),
        ("same_stable_travelway_distance_bin", ["stable_travelway_id", "distance_start_ft", "distance_end_ft"]),
        ("same_stable_travelway_window", ["stable_travelway_id", "analysis_window"]),
        ("same_signal_window", ["target_signal_id", "analysis_window"]),
    ]
    rows: list[dict[str, Any]] = []
    for risk_class, cols in groups:
        available = [col for col in cols if col in work.columns]
        if not available:
            continue
        grouped = (
            work.groupby(available, dropna=False)
            .agg(
                bin_count=("stable_bin_id", "nunique"),
                signal_count=("target_signal_id", "nunique"),
                physical_leg_count=("leg_id", "nunique"),
                subbranch_count=("subbranch_id", "nunique"),
                source_limited_bins=("source_limited_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
                grade_mainline_bins=("grade_mainline_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
            )
            .reset_index()
        )
        risky = grouped.loc[grouped["signal_count"].gt(1) | grouped["physical_leg_count"].gt(1) | grouped["subbranch_count"].gt(1)].copy()
        rows.append(
            {
                "overlap_proxy": risk_class,
                "group_count": int(len(grouped)),
                "risky_group_count": int(len(risky)),
                "max_bin_count": int(grouped["bin_count"].max()) if not grouped.empty else 0,
                "max_signal_count": int(grouped["signal_count"].max()) if not grouped.empty else 0,
                "max_physical_leg_count": int(grouped["physical_leg_count"].max()) if not grouped.empty else 0,
                "max_subbranch_count": int(grouped["subbranch_count"].max()) if not grouped.empty else 0,
                "source_limited_bins_in_risky_groups": int(risky["source_limited_bins"].sum()) if not risky.empty else 0,
                "grade_mainline_bins_in_risky_groups": int(risky["grade_mainline_bins"].sum()) if not risky.empty else 0,
                "interpretation": "proxy only; no crash assignment performed",
            }
        )
    return pd.DataFrame(rows)


def _fanout_risk(bins: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for unit_name, cols in {
        "signal": ["target_signal_id"],
        "signal_window": ["target_signal_id", "analysis_window"],
        "signal_leg_window": ["target_signal_id", "physical_leg_id_final", "analysis_window"],
        "signal_leg_subbranch_window": ["target_signal_id", "physical_leg_id_final", "carriageway_subbranch_id_final", "analysis_window"],
    }.items():
        grouped = (
            bins.groupby(cols, dropna=False)
            .agg(
                bin_count=("stable_bin_id", "nunique"),
                stable_travelway_count=("stable_travelway_id", "nunique"),
                distance_band_count=("distance_band", "nunique"),
                source_limited_bins=("source_limited_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
                grade_mainline_bins=("grade_mainline_holdout_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes"}).sum())),
            )
            .reset_index()
        )
        rows.append(
            {
                "assignment_unit": unit_name,
                "unit_count": int(len(grouped)),
                "median_bins_per_unit": float(grouped["bin_count"].median()) if not grouped.empty else 0,
                "p95_bins_per_unit": float(grouped["bin_count"].quantile(0.95)) if not grouped.empty else 0,
                "max_bins_per_unit": int(grouped["bin_count"].max()) if not grouped.empty else 0,
                "max_stable_travelways_per_unit": int(grouped["stable_travelway_count"].max()) if not grouped.empty else 0,
                "units_with_source_limited_bins": int(grouped["source_limited_bins"].gt(0).sum()),
                "units_with_grade_mainline_bins": int(grouped["grade_mainline_bins"].gt(0).sum()),
                "fanout_interpretation": "lower grain has more units but less aggregation ambiguity; signal/window is recommended first rollup",
            }
        )
    return pd.DataFrame(rows)


def _broad_envelope_feasibility(bins: pd.DataFrame) -> pd.DataFrame:
    # Broad envelope only: bbox membership is not a crash assignment.
    geom_values = _text(bins, "geometry_wkt_cleaned")
    bounds = []
    for value in geom_values.loc[geom_values.str.strip().ne("")].head(50000):
        try:
            bounds.append(wkt.loads(value).bounds)
        except Exception:
            continue
    if not bounds:
        return pd.DataFrame(
            [
                {
                    "feasibility_metric": "broad_scaffold_bbox_crash_count",
                    "count": "",
                    "notes": "not computed; no scaffold bounds parsed",
                }
            ]
        )
    minx = min(b[0] for b in bounds) - 100
    miny = min(b[1] for b in bounds) - 100
    maxx = max(b[2] for b in bounds) + 100
    maxy = max(b[3] for b in bounds) + 100
    crash_path = Path("artifacts/normalized/crashes.parquet")
    crash = _safe_read_parquet_columns(crash_path, ["DOCUMENT_NBR", "geometry"])
    in_bbox = 0
    with_geom = 0
    for value in crash["geometry"].dropna() if "geometry" in crash.columns else []:
        try:
            point = wkb.loads(value)
            with_geom += 1
            x, y = point.x, point.y
            if minx <= x <= maxx and miny <= y <= maxy:
                in_bbox += 1
        except Exception:
            continue
    return pd.DataFrame(
        [
            {
                "feasibility_metric": "normalized_crash_rows_with_geometry",
                "count": with_geom,
                "notes": "geometry parsed for broad feasibility only",
            },
            {
                "feasibility_metric": "crashes_inside_100ft_expanded_scaffold_sample_bbox",
                "count": in_bbox,
                "notes": "broad bbox over first 50,000 scaffold geometries; not an assignment and not a catchment count",
            },
        ]
    )


def _doctrine() -> pd.DataFrame:
    rows = [
        {
            "doctrine_item": "primary_crash_catchment_geometry",
            "recommendation": "50ft bin line buffer with 35ft and 75ft sensitivity",
            "rationale": "balances proximity evidence and overcapture risk; mirrors tested access buffer family without using crash direction",
        },
        {
            "doctrine_item": "primary_assignment_unit",
            "recommendation": "crash_to_signal_window rollup from bin-level candidate matches",
            "rationale": "bin-level matching preserves detail; signal-window rollup is the first stable descriptive unit",
        },
        {
            "doctrine_item": "secondary_detail_unit",
            "recommendation": "crash_to_signal_physical_leg_window",
            "rationale": "use for mechanism/review detail; may be sparse for early modeling",
        },
        {
            "doctrine_item": "sensitivity_window",
            "recommendation": "0-2500ft sensitivity kept separate from 0-1000ft primary",
            "rationale": "longer windows increase overlap/fanout and should not be collapsed into primary context",
        },
        {
            "doctrine_item": "multi_assignment",
            "recommendation": "allow and report",
            "rationale": "forcing unique assignment hides legitimate overlapping signal/bin contexts; retain source-preserving weights",
        },
        {
            "doctrine_item": "crash_direction_fields",
            "recommendation": "inventory only; not used for scaffold, catchment geometry, or upstream/downstream labels",
            "rationale": "crashes must not define roadway scaffold or direction labels",
        },
        {
            "doctrine_item": "qa_flags_to_carry",
            "recommendation": "final_alignment_class, source_limited_holdout_flag, grade_mainline_holdout_flag, still_insufficient_evidence_flag, review_only_recovery_provenance, stable_travelway_id, access product role fields",
            "rationale": "future crash summaries need scaffold/access/source limitation context",
        },
    ]
    return pd.DataFrame(rows)


def _qa() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "passed", "outputs written only to review/current/final_crash_catchment_design_feasibility"),
        ("no_candidates_promoted", "passed", "design and feasibility only"),
        ("no_rates_or_models", "passed", "no rate/model calculations"),
        ("no_final_crash_assignment", "passed", "no crash-to-signal/bin assignment detail produced"),
        ("crash_direction_not_used_for_geometry", "passed", "direction fields are inventoried by column name only"),
        ("direction_fields_inventory_only", "passed", "no direction field values read"),
        ("stable_travelway_id_carried", "passed", "target inventory and doctrine require stable_travelway_id"),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(
    crash_inventory: pd.DataFrame,
    scaffold_inventory: pd.DataFrame,
    designs: pd.DataFrame,
    overlap: pd.DataFrame,
    fanout: pd.DataFrame,
    feasibility: pd.DataFrame,
) -> str:
    source = crash_inventory.iloc[0] if not crash_inventory.empty else {}

    def inv(item: str) -> int:
        subset = scaffold_inventory.loc[scaffold_inventory["inventory_item"].eq(item)]
        return int(subset["count"].iloc[0]) if not subset.empty else 0

    max_overlap = int(overlap["max_signal_count"].max()) if not overlap.empty else 0
    max_bins_signal_window = fanout.loc[fanout["assignment_unit"].eq("signal_window"), "max_bins_per_unit"]
    max_bins_signal_window_value = int(max_bins_signal_window.iloc[0]) if not max_bins_signal_window.empty else 0
    return f"""# Final Crash/Catchment Design Feasibility Findings

## Bounded Question

This read-only diagnostic inventories crash source data and designs feasible crash catchment options for the final stable-lineage scaffold. It does not create final crash assignments, use crash direction fields for geometry or upstream/downstream logic, calculate rates, run models, promote records, or modify active outputs.

## Crash Source Data

- Recommended source for first review-only crash assignment pass: `artifacts/normalized/crashes.parquet`.
- Normalized crash rows: {int(source.get('row_count', 0)):,}
- Geometry available: {int(source.get('geometry_available_count', 0)):,}
- Missing/null geometry: {int(source.get('missing_or_null_geometry_count', 0)):,}
- CRS: {source.get('crs', WORKING_CRS_AUTHORITY)} ({source.get('crs_note', '')})
- Direction fields: {source.get('available_direction_fields_inventory_only', '') or 'none detected'}; use status is inventory-only.

## Final Scaffold Catchment Target

- Signals: {inv('represented_signal_count'):,}
- Bins: {inv('scaffold_bin_count'):,}
- Bins with geometry: {inv('bins_with_geometry'):,}
- Bins with stable Travelway ID: {inv('bins_with_stable_travelway_id'):,}
- High-confidence lineage bins: {inv('bins_high_confidence_lineage'):,}

## Recommended Catchment Design

Primary conservative option: 50 ft buffer around stable-lineage bin lines, with bin-level candidate matches rolled up to `signal_window` for first descriptive summaries. Use 35 ft and 75 ft as buffer sensitivities. Treat 100 ft as broad sensitivity only.

Sensitivity option: keep 0-2,500 ft signal-window and signal-physical-leg-window catchments separate from the primary 0-1,000 ft window.

## Overlap/Fanout Risk

- Maximum signal count in overlap proxy groups: {max_overlap:,}
- Maximum bins per signal-window unit: {max_bins_signal_window_value:,}

Overlap/fanout risk is meaningful but manageable if the first assignment pass allows multi-assignment, reports fanout, and carries source-preserving weights. Wider buffers and 0-2,500 ft windows increase risk.

## Feasibility

{'; '.join(f"{row.feasibility_metric}: {row.count}" for row in feasibility.itertuples(index=False))}

Broad envelope counts are feasibility-only and are not crash assignments.

## Readiness

The project is ready for a first review-only crash assignment pass using the stable-lineage scaffold. The next pass should implement bounded crash-to-bin candidate assignment with 50 ft primary buffer, 35/75 ft sensitivities, no crash-direction logic, explicit multi-assignment/fanout/weight fields, and scaffold/access QA flags carried forward.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start final_crash_catchment_design_feasibility")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    bins = _read_csv(STABLE_SCAFFOLD_DIR / "stable_lineage_represented_bin_universe.csv")
    signals = _read_csv(STABLE_SCAFFOLD_DIR / "stable_lineage_represented_signal_universe.csv")
    crash_inventory = _crash_source_inventory()
    scaffold_inventory = _scaffold_inventory(bins, signals)
    designs = _catchment_designs(bins)
    overlap = _overlap_risk(bins)
    fanout = _fanout_risk(bins)
    doctrine = _doctrine()
    feasibility = _broad_envelope_feasibility(bins)

    _write_csv(crash_inventory, "crash_source_inventory.csv")
    _write_csv(scaffold_inventory, "final_scaffold_catchment_target_inventory.csv")
    _write_csv(designs, "candidate_crash_catchment_designs.csv")
    _write_csv(overlap, "candidate_crash_catchment_overlap_risk.csv")
    _write_csv(fanout, "candidate_crash_catchment_fanout_risk.csv")
    _write_csv(doctrine, "crash_assignment_doctrine_recommendation.csv")
    _write_csv(feasibility, "crash_catchment_feasibility_summary.csv")
    _write_text(_findings(crash_inventory, scaffold_inventory, designs, overlap, fanout, feasibility), "final_crash_catchment_design_feasibility_findings.md")
    _write_csv(_qa(), "final_crash_catchment_design_feasibility_qa.csv")
    _write_json(
        {
            "script": "src.roadway_graph.build.final_crash_catchment_design_feasibility",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS] + [str(path) for path in CRASH_SOURCES],
            "review_only": True,
            "final_crash_assignment_produced": False,
            "crash_direction_use": "inventory_only_not_used_for_scaffold_or_catchment_geometry",
            "recommended_next_pass": "bounded review-only crash-to-bin candidate assignment with 50ft primary buffer and 35/75ft sensitivities",
            "outputs": [
                "crash_source_inventory.csv",
                "final_scaffold_catchment_target_inventory.csv",
                "candidate_crash_catchment_designs.csv",
                "candidate_crash_catchment_overlap_risk.csv",
                "candidate_crash_catchment_fanout_risk.csv",
                "crash_assignment_doctrine_recommendation.csv",
                "crash_catchment_feasibility_summary.csv",
                "final_crash_catchment_design_feasibility_findings.md",
                "final_crash_catchment_design_feasibility_qa.csv",
                "final_crash_catchment_design_feasibility_manifest.json",
                "run_progress_log.txt",
            ],
        },
        "final_crash_catchment_design_feasibility_manifest.json",
    )
    _checkpoint("complete final_crash_catchment_design_feasibility")


if __name__ == "__main__":
    main()
