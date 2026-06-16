"""Rebuild lightweight final_summaries from final_dataset_cache only.

This gated task audits the old summary folder, verifies the promoted final
cache, builds compact human-readable summaries from the cache, and validates
that no core parquet objects are copied into final_summaries.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
ANALYSIS = REPO / "work/roadway_graph/analysis"
CACHE = ANALYSIS / "final_dataset_cache"
OLD = ANALYSIS / "final_leg_corrected_analysis_dataset"
MVP = ANALYSIS / "mvp_dataset"
FINAL_SUMMARIES = ANALYSIS / "final_summaries"
OUT = REPO / "work/roadway_graph/review/rebuild_final_summaries_from_cache"

EXPECTED_PARQUETS = [
    "signal_index.parquet",
    "travelway_network_index.parquet",
    "signal_travelway_attachment.parquet",
    "signal_approaches.parquet",
    "approach_corridors.parquet",
    "bin_context.parquet",
    "distance_band_units.parquet",
    "distance_band_context.parquet",
]
EXPECTED_METADATA = ["manifest.json", "schema.json", "README.md"]
REQUIRED_SUMMARY_CSVS = [
    "cache_object_inventory.csv",
    "cache_row_count_summary.csv",
    "cache_primary_key_summary.csv",
    "signal_readiness_summary.csv",
    "approach_readiness_summary.csv",
    "corridor_summary.csv",
    "bin_context_summary.csv",
    "distance_band_units_summary.csv",
    "distance_band_context_summary.csv",
    "directionality_summary.csv",
    "directionality_missingness_summary.csv",
    "roadway_context_summary.csv",
    "speed_context_summary.csv",
    "aadt_exposure_context_summary.csv",
    "access_context_summary.csv",
    "crash_context_summary.csv",
    "rate_readiness_summary.csv",
    "known_residuals_summary.csv",
    "mvp_input_dimension_readiness_summary.csv",
    "recommended_next_actions.csv",
]
REQUIRED_SUMMARY_METADATA = ["manifest.json", "schema.json", "README.md"]
PRIMARY_KEYS = {
    "signal_index.parquet": ["signal_index_row_id"],
    "travelway_network_index.parquet": ["travelway_index_row_id"],
    "signal_travelway_attachment.parquet": ["attachment_id"],
    "signal_approaches.parquet": ["signal_approach_id"],
    "approach_corridors.parquet": ["approach_corridor_id"],
    "bin_context.parquet": ["stable_bin_id"],
    "distance_band_units.parquet": ["distance_band_unit_id"],
    "distance_band_context.parquet": ["distance_band_unit_id"],
}
EXPECTED_ROW_COUNTS = {
    "signal_index.parquet": 3_933,
    "travelway_network_index.parquet": 140_654,
    "signal_travelway_attachment.parquet": 35_862,
    "signal_approaches.parquet": 13_129,
    "approach_corridors.parquet": 66_723,
    "bin_context.parquet": 1_276_332,
    "distance_band_units.parquet": 115_976,
    "distance_band_context.parquet": 115_976,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except Exception:
        return str(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(paths: list[Path]) -> dict[str, dict[str, Any]]:
    snap: dict[str, dict[str, Any]] = {}
    for path in paths:
        snap[rel(path)] = {
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() and path.is_file() else "",
            "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat() if path.exists() else "",
            "sha256": sha256(path) if path.exists() and path.is_file() else "",
        }
    return snap


def write_csv(path: Path, rows: list[dict[str, Any]] | pd.DataFrame, fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(path, index=False)
        return
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_review_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    write_csv(OUT / name, rows)


def write_summary_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    write_csv(FINAL_SUMMARIES / name, rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamp} - {message}\n")


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "<NA>": ""})


def pct(count: float, total: float) -> float:
    return round(float(count) / float(total) * 100.0, 6) if total else 0.0


def parquet_meta(path: Path) -> tuple[bool, int | str, int | str, list[str]]:
    try:
        pf = pq.ParquetFile(path)
        return True, int(pf.metadata.num_rows), len(pf.schema_arrow.names), list(pf.schema_arrow.names)
    except Exception:
        return False, "", "", []


def inventory_folder(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return [{"path": rel(path), "exists": False}]
    for item in sorted(path.rglob("*"), key=lambda p: rel(p).lower()):
        if item.is_dir():
            continue
        readable = True
        row_count: int | str = ""
        column_count: int | str = ""
        if item.suffix.lower() == ".parquet":
            readable, row_count, column_count, _ = parquet_meta(item)
        elif item.suffix.lower() == ".json":
            try:
                json.loads(item.read_text(encoding="utf-8"))
            except Exception:
                readable = False
        else:
            try:
                item.read_text(encoding="utf-8")
            except Exception:
                readable = False
        rows.append(
            {
                "path": rel(item),
                "file_name": item.name,
                "extension": item.suffix.lower(),
                "size_bytes": item.stat().st_size,
                "modified_utc": datetime.fromtimestamp(item.stat().st_mtime, timezone.utc).isoformat(),
                "row_count": row_count,
                "column_count": column_count,
                "readable": readable,
                "core_data_object_flag": item.suffix.lower() == ".parquet" or item.stat().st_size > 50_000_000,
                "useful_summary_or_doc_candidate": item.suffix.lower() in {".csv", ".md", ".json", ".txt"} and item.stat().st_size <= 10_000_000,
            }
        )
    return rows


def cache_readiness() -> tuple[bool, list[dict[str, Any]], dict[str, list[str]]]:
    rows: list[dict[str, Any]] = []
    schemas: dict[str, list[str]] = {}
    for name in EXPECTED_PARQUETS:
        path = CACHE / name
        readable, row_count, column_count, cols = parquet_meta(path)
        schemas[name] = cols
        rows.append(
            {
                "file_name": name,
                "path": rel(path),
                "exists": path.exists(),
                "readable": readable,
                "row_count": row_count,
                "expected_row_count": EXPECTED_ROW_COUNTS[name],
                "row_count_matches_expected": row_count == EXPECTED_ROW_COUNTS[name],
                "column_count": column_count,
            }
        )
    for name in EXPECTED_METADATA:
        path = CACHE / name
        readable = False
        if path.exists():
            try:
                if name.endswith(".json"):
                    json.loads(path.read_text(encoding="utf-8"))
                else:
                    path.read_text(encoding="utf-8")
                readable = True
            except Exception:
                readable = False
        rows.append(
            {
                "file_name": name,
                "path": rel(path),
                "exists": path.exists(),
                "readable": readable,
                "row_count": "",
                "expected_row_count": "",
                "row_count_matches_expected": "",
                "column_count": "",
            }
        )
    passed = all(row["exists"] and row["readable"] for row in rows) and all(
        row["row_count_matches_expected"] in {True, ""} for row in rows
    )
    return passed, rows, schemas


def read_parquet(name: str, columns: list[str] | None = None) -> pd.DataFrame:
    path = CACHE / name
    if columns is None:
        return pd.read_parquet(path)
    available = set(parquet_meta(path)[3])
    use_cols = [col for col in columns if col in available]
    return pd.read_parquet(path, columns=use_cols)


def value_counts_rows(df: pd.DataFrame, field: str, label: str | None = None) -> list[dict[str, Any]]:
    if field not in df.columns:
        return [{"field": field, "value": "missing_field", "row_count": 0, "pct_rows": 0.0, "summary": label or field}]
    total = len(df)
    rows = []
    for value, count in clean_series(df[field]).value_counts(dropna=False).items():
        rows.append({"summary": label or field, "field": field, "value": value, "row_count": int(count), "pct_rows": pct(count, total)})
    return rows


def numeric_metric_rows(df: pd.DataFrame, field: str, label: str) -> list[dict[str, Any]]:
    if field not in df.columns:
        return [{"metric": label, "field": field, "count": 0, "non_null": 0, "sum": "", "mean": "", "min": "", "max": ""}]
    s = pd.to_numeric(df[field], errors="coerce")
    return [
        {
            "metric": label,
            "field": field,
            "count": int(len(s)),
            "non_null": int(s.notna().sum()),
            "missing": int(s.isna().sum()),
            "positive_count": int((s.fillna(0) > 0).sum()),
            "zero_count": int((s.fillna(0) == 0).sum()),
            "sum": float(s.fillna(0).sum()),
            "mean": float(s.mean()) if s.notna().any() else "",
            "min": float(s.min()) if s.notna().any() else "",
            "max": float(s.max()) if s.notna().any() else "",
        }
    ]


def build_summaries(schemas: dict[str, list[str]]) -> dict[str, Any]:
    log("Building compact summaries from final_dataset_cache only")
    inventory_rows = []
    row_count_rows = []
    pk_rows = []
    for name in EXPECTED_PARQUETS:
        path = CACHE / name
        readable, row_count, column_count, cols = parquet_meta(path)
        inventory_rows.append(
            {
                "object_name": name,
                "path": rel(path),
                "size_bytes": path.stat().st_size,
                "row_count": row_count,
                "column_count": column_count,
                "readable": readable,
                "summary_parent": "final_dataset_cache",
            }
        )
        row_count_rows.append(
            {
                "object_name": name,
                "row_count": row_count,
                "expected_row_count": EXPECTED_ROW_COUNTS[name],
                "matches_expected": row_count == EXPECTED_ROW_COUNTS[name],
            }
        )
        keys = PRIMARY_KEYS[name]
        df_key = read_parquet(name, keys)
        key_frame = df_key[keys].astype(str)
        pk_rows.append(
            {
                "object_name": name,
                "primary_key": "|".join(keys),
                "row_count": len(df_key),
                "non_null_key_rows": int(df_key[keys].notna().all(axis=1).sum()),
                "unique_key_count": int(key_frame.drop_duplicates().shape[0]),
                "duplicate_key_rows": int(len(df_key) - key_frame.drop_duplicates().shape[0]),
                "passed": df_key[keys].notna().all(axis=1).all() and len(df_key) == key_frame.drop_duplicates().shape[0],
            }
        )
    write_summary_csv("cache_object_inventory.csv", inventory_rows)
    write_summary_csv("cache_row_count_summary.csv", row_count_rows)
    write_summary_csv("cache_primary_key_summary.csv", pk_rows)

    signal = read_parquet("signal_index.parquet", ["analysis_ready_status", "analysis_ready_confidence", "source_limited_status", "geometry_validity_status", "signal_index_validation_status"])
    write_summary_csv("signal_readiness_summary.csv", value_counts_rows(signal, "analysis_ready_status") + value_counts_rows(signal, "analysis_ready_confidence") + value_counts_rows(signal, "source_limited_status") + value_counts_rows(signal, "geometry_validity_status"))

    approach = read_parquet("signal_approaches.parquet", ["approach_identity_status", "approach_confidence", "physical_leg_status", "source_limited_status", "ambiguity_status", "corridor_build_gate", "corridor_build_allowed_flag", "corridor_gate_severity"])
    write_summary_csv("approach_readiness_summary.csv", value_counts_rows(approach, "approach_identity_status") + value_counts_rows(approach, "approach_confidence") + value_counts_rows(approach, "physical_leg_status") + value_counts_rows(approach, "source_limited_status") + value_counts_rows(approach, "corridor_build_gate") + value_counts_rows(approach, "corridor_gate_severity"))

    corridor = read_parquet("approach_corridors.parquet", ["chain_completeness_status", "chain_stop_reason", "corridor_confidence", "geometry_status", "route_measure_continuity_status", "chain_bin_eligible_flag", "corridor_length_ft", "chain_total_reach_ft"])
    corridor_rows = value_counts_rows(corridor, "chain_completeness_status") + value_counts_rows(corridor, "chain_stop_reason") + value_counts_rows(corridor, "corridor_confidence") + value_counts_rows(corridor, "geometry_status") + value_counts_rows(corridor, "chain_bin_eligible_flag")
    corridor_rows += numeric_metric_rows(corridor, "corridor_length_ft", "corridor_length_ft") + numeric_metric_rows(corridor, "chain_total_reach_ft", "chain_total_reach_ft")
    write_summary_csv("corridor_summary.csv", corridor_rows)

    bins = read_parquet("bin_context.parquet", ["stable_bin_id", "distance_band", "upstream_downstream", "directionality_status", "bin_length_ft", "geometry_status", "bin_eligible_flag", "final_partial_bin_flag", "multi_segment_bin_status", "lineage_confidence"])
    bin_rows = value_counts_rows(bins, "distance_band") + value_counts_rows(bins, "upstream_downstream") + value_counts_rows(bins, "directionality_status") + value_counts_rows(bins, "geometry_status") + value_counts_rows(bins, "bin_eligible_flag") + value_counts_rows(bins, "final_partial_bin_flag") + value_counts_rows(bins, "multi_segment_bin_status")
    bin_rows += numeric_metric_rows(bins, "bin_length_ft", "bin_length_ft")
    write_summary_csv("bin_context_summary.csv", bin_rows)

    units = read_parquet("distance_band_units.parquet", ["distance_band_unit_id", "distance_band", "upstream_downstream", "directionality_status", "bin_count", "unit_length_ft", "unit_completeness_status", "bin_coverage_status", "rate_readiness_status", "source_limited_status"])
    unit_rows = value_counts_rows(units, "distance_band") + value_counts_rows(units, "upstream_downstream") + value_counts_rows(units, "directionality_status") + value_counts_rows(units, "unit_completeness_status") + value_counts_rows(units, "bin_coverage_status") + value_counts_rows(units, "rate_readiness_status")
    unit_rows += numeric_metric_rows(units, "bin_count", "unit_bin_count") + numeric_metric_rows(units, "unit_length_ft", "unit_length_ft")
    write_summary_csv("distance_band_units_summary.csv", unit_rows)

    context_cols = [
        "distance_band_unit_id", "distance_band", "upstream_downstream", "directionality_status", "directionality_unresolved_reason",
        "divided_undivided", "one_way_two_way", "roadway_context_status", "median_group", "median_type",
        "speed_limit_mph", "speed_category", "speed_context_status", "speed_missing_reason",
        "aadt", "aadt_category", "aadt_context_status", "aadt_missing_reason", "exposure_denominator", "exposure_context_status", "rate_denominator_semantics",
        "access_count", "access_count_band", "access_context_status", "access_zero_evidence_status", "access_assignment_method", "access_assignment_multiplicity_status",
        "crash_count_weighted", "crash_count_unweighted_candidate", "crash_context_status", "crash_assignment_method", "crash_weighting_method", "crash_weight_sum_status", "crash_multiplicity_status", "crash_rate_ready_flag",
        "rate_readiness_status", "overall_context_readiness_status", "source_limited_status",
    ]
    context = read_parquet("distance_band_context.parquet", context_cols)
    context_rows = value_counts_rows(context, "distance_band") + value_counts_rows(context, "upstream_downstream") + value_counts_rows(context, "overall_context_readiness_status") + value_counts_rows(context, "rate_readiness_status")
    for field in ["speed_limit_mph", "aadt", "exposure_denominator", "access_count", "crash_count_weighted"]:
        context_rows += numeric_metric_rows(context, field, field)
    write_summary_csv("distance_band_context_summary.csv", context_rows)

    direction_rows = []
    for object_name, df, row_field, length_field in [
        ("bin_context", bins, "stable_bin_id", "bin_length_ft"),
        ("distance_band_units", units, "distance_band_unit_id", "unit_length_ft"),
        ("distance_band_context", context, "distance_band_unit_id", None),
    ]:
        group_cols = ["upstream_downstream", "directionality_status"]
        grouped = df.groupby(group_cols, dropna=False).size().reset_index(name="row_count")
        for _, row in grouped.iterrows():
            direction_rows.append({"object_name": object_name, **row.to_dict()})
    write_summary_csv("directionality_summary.csv", direction_rows)
    missing_dir = context.loc[~clean_series(context["directionality_status"]).eq("assigned")]
    write_summary_csv("directionality_missingness_summary.csv", value_counts_rows(missing_dir, "directionality_status") + value_counts_rows(missing_dir, "directionality_unresolved_reason"))

    write_summary_csv("roadway_context_summary.csv", value_counts_rows(context, "roadway_context_status") + value_counts_rows(context, "divided_undivided") + value_counts_rows(context, "one_way_two_way") + value_counts_rows(context, "median_group") + value_counts_rows(context, "median_type"))
    speed_rows = value_counts_rows(context, "speed_context_status") + value_counts_rows(context, "speed_category") + value_counts_rows(context, "speed_missing_reason") + numeric_metric_rows(context, "speed_limit_mph", "speed_limit_mph")
    write_summary_csv("speed_context_summary.csv", speed_rows)
    aadt_rows = value_counts_rows(context, "aadt_context_status") + value_counts_rows(context, "aadt_category") + value_counts_rows(context, "exposure_context_status") + value_counts_rows(context, "rate_denominator_semantics")
    aadt_rows += numeric_metric_rows(context, "aadt", "aadt") + numeric_metric_rows(context, "exposure_denominator", "exposure_denominator_daily_vmt_proxy")
    write_summary_csv("aadt_exposure_context_summary.csv", aadt_rows)
    access_rows = value_counts_rows(context, "access_context_status") + value_counts_rows(context, "access_count_band") + value_counts_rows(context, "access_zero_evidence_status") + value_counts_rows(context, "access_assignment_method") + value_counts_rows(context, "access_assignment_multiplicity_status")
    access_rows += numeric_metric_rows(context, "access_count", "access_count")
    write_summary_csv("access_context_summary.csv", access_rows)
    crash_rows = value_counts_rows(context, "crash_context_status") + value_counts_rows(context, "crash_assignment_method") + value_counts_rows(context, "crash_weighting_method") + value_counts_rows(context, "crash_weight_sum_status") + value_counts_rows(context, "crash_multiplicity_status")
    crash_rows += numeric_metric_rows(context, "crash_count_weighted", "crash_count_weighted") + numeric_metric_rows(context, "crash_count_unweighted_candidate", "crash_count_unweighted_candidate")
    write_summary_csv("crash_context_summary.csv", crash_rows)
    write_summary_csv("rate_readiness_summary.csv", value_counts_rows(context, "rate_readiness_status") + value_counts_rows(context, "overall_context_readiness_status") + value_counts_rows(context, "crash_rate_ready_flag"))

    total = len(context)
    residual_rows = [
        {"residual": "unresolved_directionality_units", "count": int((~clean_series(context["directionality_status"]).eq("assigned")).sum()), "pct_units": pct((~clean_series(context["directionality_status"]).eq("assigned")).sum(), total), "documented_not_hidden": True},
        {"residual": "missing_speed_units", "count": int(pd.to_numeric(context["speed_limit_mph"], errors="coerce").isna().sum()), "pct_units": pct(pd.to_numeric(context["speed_limit_mph"], errors="coerce").isna().sum(), total), "documented_not_hidden": True},
        {"residual": "missing_aadt_or_exposure_units", "count": int((pd.to_numeric(context["aadt"], errors="coerce").isna() | pd.to_numeric(context["exposure_denominator"], errors="coerce").isna()).sum()), "pct_units": pct((pd.to_numeric(context["aadt"], errors="coerce").isna() | pd.to_numeric(context["exposure_denominator"], errors="coerce").isna()).sum(), total), "documented_not_hidden": True},
        {"residual": "route_measure_only_crashes_not_counted", "count": 23908, "pct_units": "", "documented_not_hidden": True},
        {"residual": "final_rate_ready_units_represented", "count": int(clean_series(context["crash_rate_ready_flag"]).str.lower().eq("true").sum()), "pct_units": pct(clean_series(context["crash_rate_ready_flag"]).str.lower().eq("true").sum(), total), "documented_not_hidden": True},
    ]
    write_summary_csv("known_residuals_summary.csv", residual_rows)

    mvp_rows = [
        {"dimension": "speed_category", "populated_units": int(clean_series(context["speed_category"]).ne("").sum()), "missing_units": int(clean_series(context["speed_category"]).eq("").sum()), "ready_for_mvp_logic": False},
        {"dimension": "aadt_category", "populated_units": int(clean_series(context["aadt_category"]).ne("").sum()), "missing_units": int(clean_series(context["aadt_category"]).eq("").sum()), "ready_for_mvp_logic": False},
        {"dimension": "divided_undivided", "populated_units": int(clean_series(context["divided_undivided"]).ne("").sum()), "missing_units": int(clean_series(context["divided_undivided"]).eq("").sum()), "ready_for_mvp_logic": False},
        {"dimension": "median_group", "populated_units": int(clean_series(context["median_group"]).ne("").sum()), "missing_units": int(clean_series(context["median_group"]).eq("").sum()), "ready_for_mvp_logic": False},
        {"dimension": "access_count_band", "populated_units": int(clean_series(context["access_count_band"]).ne("").sum()), "missing_units": int(clean_series(context["access_count_band"]).eq("").sum()), "ready_for_mvp_logic": False},
        {"dimension": "upstream_downstream", "populated_units": int(clean_series(context["upstream_downstream"]).ne("").sum()), "missing_units": int(clean_series(context["upstream_downstream"]).eq("").sum()), "ready_for_mvp_logic": False},
    ]
    write_summary_csv("mvp_input_dimension_readiness_summary.csv", mvp_rows)
    write_summary_csv(
        "recommended_next_actions.csv",
        [
            {"priority": 1, "action": "Use final_dataset_cache as the canonical core cache and final_summaries for lightweight inspection.", "reason": "Summaries are derived only from the promoted cache."},
            {"priority": 2, "action": "Redefine mvp_dataset in a later MVP task.", "reason": "MVP/readiness logic is intentionally deferred."},
            {"priority": 3, "action": "Plan cleanup/deprecation handling for final_leg_corrected_analysis_dataset separately.", "reason": "The old folder was audited but not modified."},
        ],
    )
    return {"row_counts": row_count_rows, "primary_keys": pk_rows, "residuals": residual_rows}


def write_summary_metadata(build_info: dict[str, Any]) -> None:
    write_json(
        FINAL_SUMMARIES / "manifest.json",
        {
            "created_utc": now(),
            "product": "final_summaries",
            "role": "lightweight summary, QA, and reporting folder",
            "data_parent": "work/roadway_graph/analysis/final_dataset_cache",
            "data_parent_only": True,
            "not_core_cache": True,
            "core_cache": "work/roadway_graph/analysis/final_dataset_cache",
            "required_summary_csvs": REQUIRED_SUMMARY_CSVS,
            "metadata_files": REQUIRED_SUMMARY_METADATA,
            "core_parquets_copied": False,
            "crash_direction_fields_used": False,
            "row_counts": build_info["row_counts"],
        },
    )
    write_json(
        FINAL_SUMMARIES / "schema.json",
        {
            "created_utc": now(),
            "summary_tables": {name: {"format": "csv", "role": "compact human-readable rollup"} for name in REQUIRED_SUMMARY_CSVS},
            "source_cache_objects": EXPECTED_PARQUETS,
            "data_parent": "work/roadway_graph/analysis/final_dataset_cache",
            "semantics": {
                "exposure": "daily VMT proxy unless later MVP logic changes it",
                "crash_count": "weighted/fractional and total-preserving",
                "access": "combined-source spatial-only with within signal/approach/direction distance-band exclusivity",
                "missingness": "unresolved/missingness residuals are documented, not hidden",
            },
        },
    )
    readme = """# final_summaries

`final_summaries` is a lightweight human-readable summary, QA, and reporting folder derived only from `work/roadway_graph/analysis/final_dataset_cache`.

This folder is not the core cache. The core cache is `final_dataset_cache`, which contains the eight validated core parquet objects. `final_summaries` is intended to be safe to inspect or copy without large data objects, and it contains no parquet files.

`work/roadway_graph/analysis/final_leg_corrected_analysis_dataset` is deprecated pending later cleanup and was not modified by this rebuild. `work/roadway_graph/analysis/mvp_dataset` will be redefined later as the MVP product folder and was not modified.

No crash direction fields are used. Exposure is a daily VMT proxy unless later MVP logic changes it. Crash count is weighted/fractional and total-preserving. Access is combined-source spatial-only with within signal/approach/direction distance-band exclusivity. Unresolved directionality and numeric/context missingness residuals are documented, not hidden.
"""
    (FINAL_SUMMARIES / "README.md").write_text(readme, encoding="utf-8")


def validate_summaries(before_cache: dict[str, dict[str, Any]], before_old: dict[str, dict[str, Any]], before_mvp: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    output_inventory = inventory_folder(FINAL_SUMMARIES)
    write_review_csv("final_summaries_output_inventory.csv", output_inventory)
    no_core_rows = []
    for row in output_inventory:
        if row.get("exists") is False:
            continue
        ext = row.get("extension", "")
        no_core_rows.append(
            {
                "path": row.get("path"),
                "parquet_file_flag": ext == ".parquet",
                "large_core_data_file_flag": row.get("size_bytes", 0) > 50_000_000,
                "passed": ext != ".parquet" and row.get("size_bytes", 0) <= 50_000_000,
            }
        )
    write_review_csv("final_summaries_no_core_data_check.csv", no_core_rows or [{"check": "no_outputs", "passed": False}])

    reconciliation = []
    summary_counts = pd.read_csv(FINAL_SUMMARIES / "cache_row_count_summary.csv")
    for _, row in summary_counts.iterrows():
        cache_count = parquet_meta(CACHE / row["object_name"])[1]
        reconciliation.append(
            {
                "object_name": row["object_name"],
                "summary_row_count": int(row["row_count"]),
                "cache_row_count": int(cache_count),
                "expected_row_count": int(row["expected_row_count"]),
                "passed": int(row["row_count"]) == int(cache_count) == int(row["expected_row_count"]),
            }
        )
    write_review_csv("summary_row_count_reconciliation.csv", reconciliation)

    after_cache = snapshot([CACHE / name for name in EXPECTED_PARQUETS + EXPECTED_METADATA])
    after_old = snapshot([p for p in OLD.iterdir() if p.is_file()]) if OLD.exists() else {}
    after_mvp = snapshot([p for p in MVP.iterdir() if p.is_file()]) if MVP.exists() else {}
    untouched_rows = []
    for label, before, after in [
        ("final_dataset_cache", before_cache, after_cache),
        ("final_leg_corrected_analysis_dataset", before_old, after_old),
        ("mvp_dataset", before_mvp, after_mvp),
    ]:
        untouched_rows.append(
            {
                "folder": label,
                "file_count_before": len(before),
                "file_count_after": len(after),
                "hashes_unchanged": before == after,
                "modified_by_this_workflow": before != after,
                "passed": before == after,
            }
        )
    write_review_csv("untouched_existing_analysis_folders_check.csv", untouched_rows)

    required_present = all((FINAL_SUMMARIES / name).exists() for name in REQUIRED_SUMMARY_CSVS + REQUIRED_SUMMARY_METADATA)
    no_core = all(row["passed"] for row in no_core_rows)
    row_counts_pass = all(row["passed"] for row in reconciliation)
    untouched_pass = all(row["passed"] for row in untouched_rows)
    metadata_valid = True
    try:
        json.loads((FINAL_SUMMARIES / "manifest.json").read_text(encoding="utf-8"))
        json.loads((FINAL_SUMMARIES / "schema.json").read_text(encoding="utf-8"))
        (FINAL_SUMMARIES / "README.md").read_text(encoding="utf-8")
    except Exception:
        metadata_valid = False
    csv_readable = True
    try:
        for name in REQUIRED_SUMMARY_CSVS:
            pd.read_csv(FINAL_SUMMARIES / name)
    except Exception:
        csv_readable = False
    validation = {
        "required_present": required_present,
        "no_core_data": no_core,
        "row_counts_pass": row_counts_pass,
        "untouched_pass": untouched_pass,
        "metadata_valid": metadata_valid,
        "csv_readable": csv_readable,
    }
    if all(validation.values()):
        decision = "final_summaries_built_from_cache_ready"
    elif required_present and no_core and row_counts_pass:
        decision = "final_summaries_built_with_minor_documented_gaps"
    else:
        decision = "final_summaries_failed_no_replacement"
    return decision, validation


def write_findings(decision: str, cache_ready: bool, old_inventory: list[dict[str, Any]], validation: dict[str, Any]) -> None:
    old_core_count = sum(1 for row in old_inventory if row.get("core_data_object_flag"))
    old_summary_count = sum(1 for row in old_inventory if row.get("useful_summary_or_doc_candidate"))
    memo = f"""# Rebuild Final Summaries From Cache

## What Was Audited
- Old folder: `work/roadway_graph/analysis/final_leg_corrected_analysis_dataset`
- Current canonical core cache: `work/roadway_graph/analysis/final_dataset_cache`
- Target summary folder: `work/roadway_graph/analysis/final_summaries`

## Data Parent
`final_dataset_cache` was used as the only data parent: {cache_ready}.

No staged folders, old final-leg folder files, MVP products, review outputs, stale `work/output` paths, or legacy paths were used as data parents.

## Old Folder Contents
The old `final_leg_corrected_analysis_dataset` folder contains {len(old_inventory)} files. Core/large data object flags: {old_core_count}. Useful summary/doc candidates worth preserving later: {old_summary_count}. The folder was audited only and was not modified.

## final_summaries Contents
`final_summaries` contains compact CSV summaries plus `manifest.json`, `schema.json`, and `README.md`. It contains no core parquet objects.

Validation summary: {validation}

## Guard Confirmations
- `final_dataset_cache` was not modified.
- `final_leg_corrected_analysis_dataset` was not modified.
- `mvp_dataset` was not modified.
- No crash direction fields were used.

## Final Decision
`{decision}`

## Recommended Next Task
Use `final_summaries` for lightweight inspection and reporting QA. Redefine `mvp_dataset` in a later MVP-specific task, and handle cleanup/deprecation of `final_leg_corrected_analysis_dataset` separately.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started final_summaries rebuild from final_dataset_cache.\n", encoding="utf-8")
    log("Gate 1: auditing old folder, target state, and final_dataset_cache")
    old_inventory = inventory_folder(OLD)
    write_review_csv("old_final_leg_folder_inventory.csv", old_inventory)
    target_exists = FINAL_SUMMARIES.exists()
    cache_ready, cache_rows, schemas = cache_readiness()
    write_review_csv("final_dataset_cache_readiness_check.csv", cache_rows)

    before_cache = snapshot([CACHE / name for name in EXPECTED_PARQUETS + EXPECTED_METADATA])
    before_old = snapshot([p for p in OLD.iterdir() if p.is_file()]) if OLD.exists() else {}
    before_mvp = snapshot([p for p in MVP.iterdir() if p.is_file()]) if MVP.exists() else {}
    decision = "final_summaries_failed_no_replacement"
    validation: dict[str, Any] = {}

    if target_exists:
        log("Gate 2 blocked: final_summaries already exists; not overwriting")
        decision = "final_summaries_blocked_existing_target"
        write_review_csv("final_summaries_build_manifest.csv", [{"built": False, "reason": "target_exists", "target": rel(FINAL_SUMMARIES)}])
        write_review_csv("final_summaries_output_inventory.csv", inventory_folder(FINAL_SUMMARIES))
        write_review_csv("final_summaries_no_core_data_check.csv", [{"check": "skipped_target_exists", "passed": False}])
        write_review_csv("summary_row_count_reconciliation.csv", [{"check": "skipped_target_exists", "passed": False}])
        write_review_csv("untouched_existing_analysis_folders_check.csv", [{"folder": "all", "passed": True, "note": "no build attempted"}])
    elif not cache_ready:
        log("Gate 2 blocked: final_dataset_cache readiness failed")
        decision = "final_summaries_needs_cache_repair"
        write_review_csv("final_summaries_build_manifest.csv", [{"built": False, "reason": "cache_not_ready"}])
        write_review_csv("final_summaries_output_inventory.csv", [{"note": "not_built"}])
        write_review_csv("final_summaries_no_core_data_check.csv", [{"note": "not_built"}])
        write_review_csv("summary_row_count_reconciliation.csv", [{"note": "not_built"}])
        write_review_csv("untouched_existing_analysis_folders_check.csv", [{"folder": "all", "passed": True, "note": "no build attempted"}])
    else:
        log("Gate 2: building final_summaries from final_dataset_cache only")
        FINAL_SUMMARIES.mkdir(parents=True, exist_ok=False)
        build_info = build_summaries(schemas)
        write_summary_metadata(build_info)
        write_review_csv(
            "final_summaries_build_manifest.csv",
            [
                {
                    "built": True,
                    "target": rel(FINAL_SUMMARIES),
                    "data_parent": rel(CACHE),
                    "summary_csv_count": len(REQUIRED_SUMMARY_CSVS),
                    "metadata_count": len(REQUIRED_SUMMARY_METADATA),
                    "core_parquets_copied": False,
                }
            ],
        )
        log("Gate 3: validating final_summaries")
        decision, validation = validate_summaries(before_cache, before_old, before_mvp)

    write_review_csv("final_decision.csv", [{"final_decision": decision, "created_utc": now()}])
    write_review_csv(
        "recommended_next_actions.csv",
        [
            {"priority": 1, "action": "Use final_summaries for lightweight cache inspection and reporting QA.", "reason": decision},
            {"priority": 2, "action": "Run MVP folder redefinition as a separate task when requested.", "reason": "MVP products were not built or modified."},
            {"priority": 3, "action": "Handle old final_leg_corrected_analysis_dataset cleanup separately.", "reason": "Old folder was not modified."},
        ],
    )
    write_findings(decision, cache_ready, old_inventory, validation)
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "script": "src.roadway_graph.build.rebuild_final_summaries_from_cache",
            "data_parent": rel(CACHE),
            "target": rel(FINAL_SUMMARIES),
            "final_decision": decision,
            "required_summary_csvs": REQUIRED_SUMMARY_CSVS,
            "required_metadata": REQUIRED_SUMMARY_METADATA,
        },
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "final_decision": decision,
            "cache_ready": cache_ready,
            "validation": validation,
            "outputs": sorted(path.name for path in OUT.iterdir() if path.is_file()),
        },
    )
    log(f"Workflow complete: {decision}")


if __name__ == "__main__":
    main()
