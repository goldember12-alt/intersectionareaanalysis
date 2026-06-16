"""Build first clean MVP dataset from final_dataset_cache.

The only data parent is final_dataset_cache/distance_band_context.parquet.
Old MVP products and review outputs are audited only and are not data parents.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
ANALYSIS = REPO / "work/roadway_graph/analysis"
CACHE = ANALYSIS / "final_dataset_cache"
CONTEXT = CACHE / "distance_band_context.parquet"
FINAL_SUMMARIES = ANALYSIS / "final_summaries"
OLD_MVP = ANALYSIS / "mvp_dataset"
MVP = ANALYSIS / "mvp_dataset"
EXPORTS = MVP / "exports"
OUT = REPO / "work/roadway_graph/review/build_mvp_dataset_from_final_cache"

IDENTITY_FIELDS = ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
DIMENSIONS = [
    "speed_category",
    "aadt_category",
    "divided_undivided",
    "median_group",
    "access_count_band",
    "access_type_dominant",
    "upstream_downstream",
    "distance_band",
]
REQUIRED_CONTEXT_FIELDS = [
    *IDENTITY_FIELDS,
    "speed_category",
    "aadt_category",
    "divided_undivided",
    "median_type",
    "median_group",
    "access_count_band",
    "access_type_dominant",
    "access_type_summary",
    "directionality_status",
    "crash_count_weighted",
    "crash_count_unweighted_candidate",
    "exposure_daily_vmt_proxy",
    "exposure_denominator",
    "exposure_denominator_status",
    "rate_denominator_semantics",
    "access_context_status",
    "access_zero_evidence_status",
    "crash_context_status",
    "crash_weight_sum_status",
    "overall_context_readiness_status",
    "context_quality_flags",
]
CORE_CACHE_PARQUETS = {
    "signal_index.parquet",
    "travelway_network_index.parquet",
    "signal_travelway_attachment.parquet",
    "signal_approaches.parquet",
    "approach_corridors.parquet",
    "bin_context.parquet",
    "distance_band_units.parquet",
    "distance_band_context.parquet",
}
REVIEW_OUTPUTS = [
    "manifest.json",
    "qa_manifest.json",
    "progress_log.md",
    "findings_memo.md",
    "old_mvp_folder_inventory.csv",
    "final_dataset_cache_parent_check.csv",
    "mvp_required_field_presence_check.csv",
    "mvp_units_build_summary.csv",
    "mvp_units_readiness_summary.csv",
    "lookup_cells_build_summary.csv",
    "lookup_cell_reliability_summary.csv",
    "lookup_cell_unit_distribution_check.csv",
    "mvp_rate_semantics_check.csv",
    "crash_count_reconciliation.csv",
    "exposure_reconciliation.csv",
    "mvp_missingness_summary.csv",
    "mvp_dataset_output_inventory.csv",
    "mvp_dataset_no_core_cache_copy_check.csv",
    "untouched_analysis_folders_check.csv",
    "final_decision.csv",
    "recommended_next_actions.csv",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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


def snapshot(folder: Path) -> dict[str, dict[str, Any]]:
    snap: dict[str, dict[str, Any]] = {}
    if not folder.exists():
        return snap
    for path in sorted(folder.rglob("*"), key=lambda p: rel(p).lower()):
        if path.is_file():
            snap[rel(path)] = {
                "size_bytes": path.stat().st_size,
                "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "sha256": sha256(path),
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


def write_review(name: str, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    write_csv(OUT / name, rows)


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


def inventory_folder(folder: Path) -> list[dict[str, Any]]:
    if not folder.exists():
        return [{"path": rel(folder), "exists": False}]
    rows: list[dict[str, Any]] = []
    for path in sorted(folder.rglob("*"), key=lambda p: rel(p).lower()):
        if path.is_dir():
            continue
        readable = True
        row_count: int | str = ""
        column_count: int | str = ""
        if path.suffix.lower() == ".parquet":
            readable, row_count, column_count, _ = parquet_meta(path)
        elif path.suffix.lower() == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                readable = False
        else:
            try:
                path.read_text(encoding="utf-8")
            except Exception:
                readable = False
        size = path.stat().st_size
        lower_name = path.name.lower()
        rows.append(
            {
                "path": rel(path),
                "file_name": path.name,
                "extension": path.suffix.lower(),
                "size_bytes": size,
                "row_count": row_count,
                "column_count": column_count,
                "readable": readable,
                "core_object_flag": path.name in CORE_CACHE_PARQUETS,
                "large_export_or_stale_product_flag": size > 50_000_000 or "bin_context" in lower_name,
                "summary_or_doc_flag": path.suffix.lower() in {".csv", ".md", ".json", ".txt"} and size <= 10_000_000,
            }
        )
    return rows


def parent_check() -> tuple[bool, list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    readable, row_count, column_count, cols = parquet_meta(CONTEXT)
    rows.append(
        {
            "check": "distance_band_context_present_readable",
            "path": rel(CONTEXT),
            "passed": CONTEXT.exists() and readable,
            "row_count": row_count,
            "column_count": column_count,
        }
    )
    for name in ["manifest.json", "schema.json", "README.md"]:
        path = CACHE / name
        ok = False
        try:
            if name.endswith(".json"):
                json.loads(path.read_text(encoding="utf-8"))
            else:
                path.read_text(encoding="utf-8")
            ok = True
        except Exception:
            ok = False
        rows.append({"check": f"{name}_present_readable", "path": rel(path), "passed": path.exists() and ok})
    return all(row["passed"] for row in rows), rows, cols


def required_field_check(cols: list[str]) -> tuple[bool, list[dict[str, Any]]]:
    rows = [{"field": field, "present": field in cols, "required": True} for field in REQUIRED_CONTEXT_FIELDS]
    return all(row["present"] for row in rows), rows


def status_from_reasons(reasons: list[str]) -> str:
    return "ready_proxy_rate_unit" if not reasons else "low_confidence_or_excluded"


def reliability_from_ready(count: int) -> str:
    if count >= 30:
        return "high"
    if count >= 10:
        return "medium"
    if count > 0:
        return "low"
    return "insufficient"


def build_mvp_units(context: pd.DataFrame) -> pd.DataFrame:
    units = context[REQUIRED_CONTEXT_FIELDS].copy()
    for col in REQUIRED_CONTEXT_FIELDS:
        if col not in units.columns:
            units[col] = pd.NA
    for col in [
        "crash_count_weighted",
        "crash_count_unweighted_candidate",
        "exposure_daily_vmt_proxy",
        "exposure_denominator",
    ]:
        units[col] = pd.to_numeric(units[col], errors="coerce")
    units["directionality_missing_flag"] = ~clean_series(units["directionality_status"]).eq("assigned")
    units["speed_missing_flag"] = clean_series(units["speed_category"]).eq("")
    units["aadt_missing_flag"] = clean_series(units["aadt_category"]).eq("")
    units["exposure_missing_flag"] = units["exposure_denominator"].isna() | (units["exposure_denominator"] <= 0)
    units["crash_missing_flag"] = units["crash_count_weighted"].isna()
    units["access_context_flag"] = clean_series(units["access_context_status"])
    units["crash_context_flag"] = clean_series(units["crash_context_status"])
    units["zero_crash_valid_flag"] = units["crash_context_flag"].isin(["assigned_spatial_fractional", "no_assigned_crashes"]) & units["crash_count_weighted"].fillna(0).eq(0)
    units["zero_access_valid_flag"] = clean_series(units["access_context_status"]).eq("evaluated_zero_access")
    units["crash_rate_proxy_per_daily_vmt"] = units["crash_count_weighted"] / units["exposure_denominator"]
    units.loc[units["exposure_missing_flag"], "crash_rate_proxy_per_daily_vmt"] = pd.NA
    units["crash_rate_proxy_per_million_daily_vmt"] = units["crash_rate_proxy_per_daily_vmt"] * 1_000_000
    units["final_crash_rate"] = pd.NA
    units["rate_semantics_status"] = "proxy_daily_vmt_rate_not_final_crash_period_rate"
    units.loc[units["exposure_missing_flag"], "rate_semantics_status"] = "proxy_rate_not_computed_missing_daily_vmt_denominator"

    missing_reasons: list[str] = []
    readiness: list[str] = []
    reliability: list[str] = []
    for row in units.itertuples(index=False):
        reasons: list[str] = []
        if getattr(row, "directionality_missing_flag"):
            reasons.append("unresolved_directionality")
        if getattr(row, "speed_missing_flag"):
            reasons.append("missing_speed_category")
        if getattr(row, "aadt_missing_flag"):
            reasons.append("missing_aadt_category")
        if getattr(row, "exposure_missing_flag"):
            reasons.append("missing_or_zero_exposure_daily_vmt_proxy")
        if getattr(row, "crash_missing_flag"):
            reasons.append("missing_weighted_crash_count")
        if clean_series(pd.Series([getattr(row, "access_count_band")])).iloc[0] == "":
            reasons.append("missing_access_count_band")
        missing_reasons.append("|".join(reasons))
        status = status_from_reasons(reasons)
        readiness.append(status)
        reliability.append("unit_ready_for_proxy_lookup" if status == "ready_proxy_rate_unit" else "unit_low_confidence_or_excluded")
    units["mvp_unit_missingness_reason"] = missing_reasons
    units["mvp_unit_readiness_status"] = readiness
    units["reliability_flag"] = reliability
    units["mvp_ready_unit_flag"] = units["mvp_unit_readiness_status"].eq("ready_proxy_rate_unit")
    for dim in DIMENSIONS:
        units[f"{dim}_lookup_value"] = clean_series(units[dim]).replace({"": "__missing__"})
    return units


def lookup_id(row: pd.Series) -> str:
    text = "|".join(str(row[f"{dim}_lookup_value"]) for dim in DIMENSIONS)
    return "mvp_cell_" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def build_lookup(units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    units = units.copy()
    units["lookup_cell_id"] = units.apply(lookup_id, axis=1)
    group_cols = ["lookup_cell_id"] + [f"{dim}_lookup_value" for dim in DIMENSIONS]
    agg = (
        units.groupby(group_cols, dropna=False)
        .agg(
            unit_count=("distance_band_unit_id", "size"),
            ready_unit_count=("mvp_ready_unit_flag", "sum"),
            weighted_crash_count_sum=("crash_count_weighted", "sum"),
            unweighted_candidate_crash_count_sum=("crash_count_unweighted_candidate", "sum"),
            exposure_daily_vmt_proxy_sum=("exposure_daily_vmt_proxy", "sum"),
            zero_crash_unit_count=("crash_count_weighted", lambda s: int((s.fillna(0) == 0).sum())),
            nonzero_crash_unit_count=("crash_count_weighted", lambda s: int((s.fillna(0) > 0).sum())),
            crash_rate_proxy_mean=("crash_rate_proxy_per_million_daily_vmt", "mean"),
            crash_rate_proxy_median=("crash_rate_proxy_per_million_daily_vmt", "median"),
            crash_rate_proxy_p10=("crash_rate_proxy_per_million_daily_vmt", lambda s: s.dropna().quantile(0.10) if s.notna().any() else pd.NA),
            crash_rate_proxy_p25=("crash_rate_proxy_per_million_daily_vmt", lambda s: s.dropna().quantile(0.25) if s.notna().any() else pd.NA),
            crash_rate_proxy_p75=("crash_rate_proxy_per_million_daily_vmt", lambda s: s.dropna().quantile(0.75) if s.notna().any() else pd.NA),
            crash_rate_proxy_p90=("crash_rate_proxy_per_million_daily_vmt", lambda s: s.dropna().quantile(0.90) if s.notna().any() else pd.NA),
            min_proxy_rate=("crash_rate_proxy_per_million_daily_vmt", "min"),
            max_proxy_rate=("crash_rate_proxy_per_million_daily_vmt", "max"),
        )
        .reset_index()
    )
    agg["excluded_or_low_confidence_unit_count"] = agg["unit_count"] - agg["ready_unit_count"]
    agg["reliability_flag"] = agg["ready_unit_count"].astype(int).map(reliability_from_ready)
    missing_summary = (
        units.loc[~units["mvp_ready_unit_flag"]]
        .groupby("lookup_cell_id")["mvp_unit_missingness_reason"]
        .apply(lambda s: ";".join(sorted({part for text in s for part in str(text).split("|") if part})))
        .reset_index(name="missingness_summary")
    )
    agg = agg.merge(missing_summary, on="lookup_cell_id", how="left")
    agg["missingness_summary"] = agg["missingness_summary"].fillna("")
    agg["rate_semantics_status"] = "proxy_daily_vmt_rate_not_final_crash_period_rate"
    for dim in DIMENSIONS:
        agg[dim] = agg[f"{dim}_lookup_value"].replace({"__missing__": ""})
    ordered = [
        "lookup_cell_id",
        *DIMENSIONS,
        "unit_count",
        "ready_unit_count",
        "excluded_or_low_confidence_unit_count",
        "weighted_crash_count_sum",
        "unweighted_candidate_crash_count_sum",
        "exposure_daily_vmt_proxy_sum",
        "crash_rate_proxy_mean",
        "crash_rate_proxy_median",
        "crash_rate_proxy_p10",
        "crash_rate_proxy_p25",
        "crash_rate_proxy_p75",
        "crash_rate_proxy_p90",
        "min_proxy_rate",
        "max_proxy_rate",
        "zero_crash_unit_count",
        "nonzero_crash_unit_count",
        "reliability_flag",
        "missingness_summary",
        "rate_semantics_status",
    ]
    distribution_cols_raw = [
        "lookup_cell_id",
        *IDENTITY_FIELDS,
        *DIMENSIONS,
        "crash_count_weighted",
        "exposure_daily_vmt_proxy",
        "crash_rate_proxy_per_daily_vmt",
        "crash_rate_proxy_per_million_daily_vmt",
        "mvp_unit_readiness_status",
        "mvp_unit_missingness_reason",
        "directionality_missing_flag",
        "speed_missing_flag",
        "aadt_missing_flag",
        "exposure_missing_flag",
        "reliability_flag",
    ]
    distribution_cols = list(dict.fromkeys(distribution_cols_raw))
    return agg[ordered], units[distribution_cols]


def backup_existing_target_if_needed() -> tuple[bool, str]:
    if not MVP.exists():
        return True, ""
    backup_root = ANALYSIS / f"_superseded_mvp_dataset_{timestamp()}"
    if backup_root.exists():
        return False, rel(backup_root)
    shutil.move(str(MVP), str(backup_root))
    return True, rel(backup_root)


def build_exports(units: pd.DataFrame, lookup: pd.DataFrame) -> None:
    EXPORTS.mkdir(parents=True, exist_ok=True)
    lookup.to_csv(EXPORTS / "lookup_cells.csv", index=False)
    units["mvp_unit_readiness_status"].value_counts().rename_axis("mvp_unit_readiness_status").reset_index(name="unit_count").to_csv(EXPORTS / "mvp_unit_readiness_summary.csv", index=False)
    lookup["reliability_flag"].value_counts().rename_axis("reliability_flag").reset_index(name="lookup_cell_count").to_csv(EXPORTS / "lookup_cell_reliability_summary.csv", index=False)
    missing_rows = []
    for flag in ["directionality_missing_flag", "speed_missing_flag", "aadt_missing_flag", "exposure_missing_flag", "crash_missing_flag"]:
        missing_rows.append({"missingness_flag": flag, "unit_count": int(units[flag].sum()), "pct_units": pct(units[flag].sum(), len(units))})
    write_csv(EXPORTS / "mvp_missingness_summary.csv", missing_rows)
    lookup.sort_values(["unit_count", "weighted_crash_count_sum"], ascending=[False, False]).head(100).to_csv(EXPORTS / "top_lookup_cells_by_unit_count.csv", index=False)
    lookup.sort_values(["weighted_crash_count_sum", "unit_count"], ascending=[False, False]).head(100).to_csv(EXPORTS / "top_lookup_cells_by_weighted_crashes.csv", index=False)


def write_metadata(units: pd.DataFrame, lookup: pd.DataFrame) -> None:
    write_json(
        MVP / "manifest.json",
        {
            "created_utc": now(),
            "product": "mvp_dataset",
            "role": "first clean MVP analytical product",
            "data_parent": "work/roadway_graph/analysis/final_dataset_cache/distance_band_context.parquet",
            "metadata_parents": [
                "work/roadway_graph/analysis/final_dataset_cache/manifest.json",
                "work/roadway_graph/analysis/final_dataset_cache/schema.json",
                "work/roadway_graph/analysis/final_dataset_cache/README.md",
            ],
            "data_parent_only": True,
            "not_core_cache": True,
            "outputs": ["mvp_units.parquet", "lookup_cells.parquet", "lookup_cell_unit_distribution.parquet", "exports/"],
            "unit_count": int(len(units)),
            "lookup_cell_count": int(len(lookup)),
            "rate_semantics_status": "proxy_daily_vmt_rate_not_final_crash_period_rate",
            "crash_direction_fields_used": False,
        },
    )
    write_json(
        MVP / "schema.json",
        {
            "created_utc": now(),
            "tables": {
                "mvp_units.parquet": {"grain": "one row per distance_band_unit_id", "columns": list(units.columns)},
                "lookup_cells.parquet": {"grain": "one row per MVP lookup dimension cell", "columns": list(lookup.columns)},
                "lookup_cell_unit_distribution.parquet": {"grain": "one row per MVP unit with lookup_cell_id", "columns": []},
            },
            "rate_semantics": {
                "crash_rate_proxy_per_daily_vmt": "crash_count_weighted divided by exposure_denominator/daily VMT proxy",
                "crash_rate_proxy_per_million_daily_vmt": "proxy rate multiplied by 1,000,000",
                "final_crash_rate": "null; final crash-period exposure is not available in this MVP v1",
            },
            "reliability_thresholds": {"high": "ready_unit_count >= 30", "medium": "10-29", "low": "1-9", "insufficient": "0"},
        },
    )
    readme = """# mvp_dataset

`mvp_dataset` is the first clean MVP analytical product. It is derived only from `work/roadway_graph/analysis/final_dataset_cache/distance_band_context.parquet` plus cache metadata. It is not the canonical core cache; `final_dataset_cache` remains the core data parent.

`final_summaries` is human-readable QA/reporting and is not a data parent. The old `mvp_dataset` was audited only and was not used as a parent.

Rates in this MVP v1 are proxy rates because the cache currently carries a daily VMT proxy, not final crash-period exposure. Fields named `crash_rate_proxy_*` should not be interpreted as final crash-period crash rates. `final_crash_rate` is null.

The crash numerator uses the spatial-primary, band-exclusive, equal fractional total-preserving crash assignment carried by `distance_band_context`. Access uses combined-source spatial-only assignment with within signal/approach/direction distance-band exclusivity. No crash direction fields were used.

Use readiness and reliability flags when interpreting lookup cells. Units with unresolved directionality or missing speed/AADT/exposure are preserved but marked low confidence or excluded from ready-unit counts.
"""
    (MVP / "README.md").write_text(readme, encoding="utf-8")


def validation_and_review(context: pd.DataFrame, units: pd.DataFrame, lookup: pd.DataFrame, distribution: pd.DataFrame, before: dict[str, dict[str, dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    unit_ids_context = set(context["distance_band_unit_id"].astype(str))
    unit_ids_mvp = set(units["distance_band_unit_id"].astype(str))
    crash_context = float(pd.to_numeric(context["crash_count_weighted"], errors="coerce").fillna(0).sum())
    crash_units = float(pd.to_numeric(units["crash_count_weighted"], errors="coerce").fillna(0).sum())
    exposure_context = float(pd.to_numeric(context["exposure_denominator"], errors="coerce").fillna(0).sum())
    exposure_units = float(pd.to_numeric(units["exposure_denominator"], errors="coerce").fillna(0).sum())
    write_review(
        "crash_count_reconciliation.csv",
        [
            {
                "context_weighted_crash_sum": crash_context,
                "mvp_units_weighted_crash_sum": crash_units,
                "lookup_weighted_crash_sum": float(lookup["weighted_crash_count_sum"].sum()),
                "passed": abs(crash_context - crash_units) < 1e-9 and abs(crash_units - float(lookup["weighted_crash_count_sum"].sum())) < 1e-9,
            }
        ],
    )
    write_review(
        "exposure_reconciliation.csv",
        [
            {
                "context_exposure_denominator_sum": exposure_context,
                "mvp_units_exposure_denominator_sum": exposure_units,
                "lookup_exposure_daily_vmt_proxy_sum": float(lookup["exposure_daily_vmt_proxy_sum"].sum()),
                "passed": abs(exposure_context - exposure_units) < 1e-6,
            }
        ],
    )
    readiness = units["mvp_unit_readiness_status"].value_counts().rename_axis("mvp_unit_readiness_status").reset_index(name="unit_count")
    readiness["pct_units"] = readiness["unit_count"].map(lambda x: pct(x, len(units)))
    write_review("mvp_units_readiness_summary.csv", readiness)
    reliability = lookup["reliability_flag"].value_counts().rename_axis("reliability_flag").reset_index(name="lookup_cell_count")
    reliability["pct_cells"] = reliability["lookup_cell_count"].map(lambda x: pct(x, len(lookup)))
    write_review("lookup_cell_reliability_summary.csv", reliability)
    missing_rows = []
    for flag in ["directionality_missing_flag", "speed_missing_flag", "aadt_missing_flag", "exposure_missing_flag", "crash_missing_flag"]:
        missing_rows.append({"missingness_flag": flag, "unit_count": int(units[flag].sum()), "pct_units": pct(units[flag].sum(), len(units))})
    write_review("mvp_missingness_summary.csv", missing_rows)
    write_review(
        "mvp_units_build_summary.csv",
        [
            {
                "mvp_units_row_count": len(units),
                "context_row_count": len(context),
                "unit_id_sets_match": unit_ids_context == unit_ids_mvp,
                "grain_unique": units["distance_band_unit_id"].astype(str).is_unique,
                "all_units_preserved": len(units) == len(context) == 115_976,
            }
        ],
    )
    write_review(
        "lookup_cells_build_summary.csv",
        [
            {
                "lookup_cell_count": len(lookup),
                "lookup_cell_id_unique": lookup["lookup_cell_id"].astype(str).is_unique,
                "unit_count_sum": int(lookup["unit_count"].sum()),
                "ready_unit_count_sum": int(lookup["ready_unit_count"].sum()),
                "rate_semantics_status": "proxy_daily_vmt_rate_not_final_crash_period_rate",
            }
        ],
    )
    write_review(
        "lookup_cell_unit_distribution_check.csv",
        [
            {
                "distribution_row_count": len(distribution),
                "mvp_unit_row_count": len(units),
                "lookup_cell_ids_valid": set(distribution["lookup_cell_id"]).issubset(set(lookup["lookup_cell_id"])),
                "distance_band_unit_ids_valid": set(distribution["distance_band_unit_id"].astype(str)) == unit_ids_mvp,
                "passed": len(distribution) == len(units),
            }
        ],
    )
    write_review(
        "mvp_rate_semantics_check.csv",
        [
            {
                "rate_semantics_status": "proxy_daily_vmt_rate_not_final_crash_period_rate",
                "final_crash_rate_populated_count": int(units["final_crash_rate"].notna().sum()),
                "proxy_rate_populated_count": int(units["crash_rate_proxy_per_million_daily_vmt"].notna().sum()),
                "passed": int(units["final_crash_rate"].notna().sum()) == 0,
            }
        ],
    )
    inv = inventory_folder(MVP)
    write_review("mvp_dataset_output_inventory.csv", inv)
    no_core = []
    for row in inv:
        name = row.get("file_name", "")
        no_core.append(
            {
                "path": row.get("path", ""),
                "core_cache_parquet_copy_flag": name in CORE_CACHE_PARQUETS,
                "review_output_copy_flag": "work/roadway_graph/review/" in str(row.get("path", "")),
                "passed": name not in CORE_CACHE_PARQUETS and "work/roadway_graph/review/" not in str(row.get("path", "")),
            }
        )
    write_review("mvp_dataset_no_core_cache_copy_check.csv", no_core)
    after = {"final_dataset_cache": snapshot(CACHE), "final_summaries": snapshot(FINAL_SUMMARIES), "old_mvp": snapshot(OLD_MVP)}
    untouched = []
    for label in ["final_dataset_cache", "final_summaries", "old_mvp"]:
        unchanged = before[label] == after[label]
        untouched.append({"folder": label, "hashes_unchanged": unchanged, "modified_by_this_workflow": not unchanged, "passed": unchanged})
    write_review("untouched_analysis_folders_check.csv", untouched)
    checks = {
        "units_preserved": len(units) == len(context) == 115_976 and unit_ids_context == unit_ids_mvp,
        "unit_grain_unique": units["distance_band_unit_id"].astype(str).is_unique,
        "lookup_unique": lookup["lookup_cell_id"].astype(str).is_unique,
        "distribution_valid": len(distribution) == len(units),
        "crash_reconciles": abs(crash_context - crash_units) < 1e-9,
        "exposure_reconciles": abs(exposure_context - exposure_units) < 1e-6,
        "no_core_copies": all(row["passed"] for row in no_core),
        "untouched": all(row["passed"] for row in untouched),
    }
    decision = "mvp_dataset_built_with_proxy_rate_semantics" if all(checks.values()) else "mvp_dataset_failed_no_replacement"
    return decision, checks


def write_findings(decision: str, old_inventory: list[dict[str, Any]], units: pd.DataFrame | None, lookup: pd.DataFrame | None, checks: dict[str, Any]) -> None:
    old_large = sum(1 for row in old_inventory if row.get("large_export_or_stale_product_flag"))
    old_summary = sum(1 for row in old_inventory if row.get("summary_or_doc_flag"))
    unit_count = len(units) if units is not None else 0
    lookup_count = len(lookup) if lookup is not None else 0
    ready_count = int(units["mvp_ready_unit_flag"].sum()) if units is not None and "mvp_ready_unit_flag" in units else 0
    reliability_summary = lookup["reliability_flag"].value_counts().to_dict() if lookup is not None and "reliability_flag" in lookup else {}
    memo = f"""# Build MVP Dataset From Final Cache

## Old MVP Folder
The old `mvp_dataset` folder was audited only and not modified. It contains {len(old_inventory)} files, including {old_large} large/stale export-style products and {old_summary} smaller summary/doc candidates.

## New mvp_dataset
`mvp_dataset` contains `mvp_units.parquet`, `lookup_cells.parquet`, `lookup_cell_unit_distribution.parquet`, metadata, and compact CSV exports. No core cache parquets were copied.

## Parent Data
The only data parent was `work/roadway_graph/analysis/final_dataset_cache/distance_band_context.parquet`. Cache metadata was read for documentation. `final_summaries`, old MVP products, review outputs, stale work/output paths, legacy paths, and crash direction fields were not used.

## Counts
- MVP unit count: {unit_count}
- Lookup cell count: {lookup_count}
- Ready proxy-rate units: {ready_count}
- Reliability summary: {reliability_summary}

## Rate Semantics
Decision: proxy daily VMT rate semantics. `final_crash_rate` is null because final crash-period exposure is not available in the cache.

## Reconciliation
Validation checks: {checks}

## Final Decision
`{decision}`

## Recommended Next Task
Review MVP lookup behavior and reliability thresholds with users, then decide whether additional suppression, fallback hierarchy, or final crash-period exposure logic is needed before using this as guidance.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started MVP dataset build from final cache.\n", encoding="utf-8")
    decision = "mvp_dataset_failed_no_replacement"
    old_inventory = inventory_folder(OLD_MVP)
    write_review("old_mvp_folder_inventory.csv", old_inventory)
    before = {"final_dataset_cache": snapshot(CACHE), "final_summaries": snapshot(FINAL_SUMMARIES), "old_mvp": snapshot(OLD_MVP)}

    log("Gate 1: auditing old MVP folder, target state, and final_dataset_cache")
    target_ready, backup_path = backup_existing_target_if_needed()
    if not target_ready:
        decision = "mvp_dataset_blocked_by_existing_target"
        write_review("final_dataset_cache_parent_check.csv", [{"check": "skipped_existing_target_backup_failed", "passed": False, "backup_path": backup_path}])
        write_review("mvp_required_field_presence_check.csv", [{"check": "skipped_existing_target_backup_failed", "passed": False}])
        for name in REVIEW_OUTPUTS:
            if not (OUT / name).exists() and name not in {"manifest.json", "qa_manifest.json", "progress_log.md", "findings_memo.md", "final_decision.csv", "recommended_next_actions.csv"}:
                write_review(name, [{"note": "skipped_existing_target_backup_failed"}])
        write_findings(decision, old_inventory, None, None, {"target_backup_failed": backup_path})
    else:
        if backup_path:
            log(f"Existing mvp_dataset moved to backup {backup_path}")
        parent_ok, parent_rows, cols = parent_check()
        write_review("final_dataset_cache_parent_check.csv", parent_rows)
        fields_ok, field_rows = required_field_check(cols)
        write_review("mvp_required_field_presence_check.csv", field_rows)
        if not parent_ok or not fields_ok:
            decision = "mvp_dataset_needs_context_repair"
            for name in REVIEW_OUTPUTS:
                if not (OUT / name).exists() and name not in {"manifest.json", "qa_manifest.json", "progress_log.md", "findings_memo.md", "final_decision.csv", "recommended_next_actions.csv"}:
                    write_review(name, [{"note": "not_built_context_or_field_gate_failed"}])
            write_findings(decision, old_inventory, None, None, {"parent_ok": parent_ok, "fields_ok": fields_ok})
        else:
            log("Gate 2: building MVP units")
            MVP.mkdir(parents=True, exist_ok=False)
            EXPORTS.mkdir(parents=True, exist_ok=True)
            context = pd.read_parquet(CONTEXT, columns=REQUIRED_CONTEXT_FIELDS)
            units = build_mvp_units(context)
            units.to_parquet(MVP / "mvp_units.parquet", index=False)
            log("Gate 3: building lookup cells")
            lookup, distribution = build_lookup(units)
            lookup.to_parquet(MVP / "lookup_cells.parquet", index=False)
            log("Gate 4: building lookup unit distribution")
            distribution.to_parquet(MVP / "lookup_cell_unit_distribution.parquet", index=False)
            log("Gate 5: writing compact exports")
            build_exports(units, lookup)
            log("Gate 6: writing metadata and validation outputs")
            write_metadata(units, lookup)
            decision, checks = validation_and_review(context, units, lookup, distribution, before)
            write_findings(decision, old_inventory, units, lookup, checks)

    write_review("final_decision.csv", [{"final_decision": decision, "created_utc": now()}])
    recs = [
        {"priority": 1, "action": "Review MVP proxy-rate lookup cells and reliability thresholds.", "reason": decision},
        {"priority": 2, "action": "Decide whether to add suppression/fallback hierarchy before public guidance use.", "reason": "Sparse cells are explicitly flagged."},
        {"priority": 3, "action": "Do not interpret proxy rates as final crash-period rates.", "reason": "Exposure is daily VMT proxy."},
    ]
    write_review("recommended_next_actions.csv", recs)
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "script": "src.roadway_graph.build.build_mvp_dataset_from_final_cache",
            "data_parent": rel(CONTEXT),
            "target": rel(MVP),
            "final_decision": decision,
        },
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "final_decision": decision,
            "outputs": sorted(path.name for path in OUT.iterdir() if path.is_file()),
        },
    )
    log(f"Workflow complete: {decision}")


if __name__ == "__main__":
    main()
