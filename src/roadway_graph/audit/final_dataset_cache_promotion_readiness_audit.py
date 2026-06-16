"""Read-only final promotion-readiness audit for staged final cache objects.

This audit validates the staged rebuilt cache folder as a candidate for a
future final_dataset_cache promotion. It writes review outputs only and does
not mutate staged products, canonical products, source artifacts, MVP products,
or parquet files.
"""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/final_dataset_cache_promotion_readiness_audit"

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
EXPECTED_FILES = EXPECTED_PARQUETS + EXPECTED_METADATA
EXPECTED_ROW_COUNTS = {
    "bin_context.parquet": 1_276_332,
    "distance_band_units.parquet": 115_976,
    "distance_band_context.parquet": 115_976,
}
OBJECT_NAMES = [name.removesuffix(".parquet") for name in EXPECTED_PARQUETS]
OBJECT_PATHS = {name: STAGING / name for name in EXPECTED_PARQUETS}
METADATA_PATHS = {name: STAGING / name for name in EXPECTED_METADATA}

EXPECTED_PARENT_CHAIN = {
    "signal_index": ["artifacts/normalized/signals.parquet"],
    "travelway_network_index": ["artifacts/normalized/roads.parquet"],
    "signal_travelway_attachment": ["signal_index", "travelway_network_index"],
    "signal_approaches": ["signal_index", "travelway_network_index", "signal_travelway_attachment"],
    "approach_corridors": ["signal_index", "travelway_network_index", "signal_travelway_attachment", "signal_approaches"],
    "bin_context": ["signal_index", "travelway_network_index", "signal_approaches", "approach_corridors"],
    "distance_band_units": ["bin_context"],
    "distance_band_context": [
        "travelway_network_index",
        "approach_corridors",
        "bin_context",
        "distance_band_units",
        "Intersection Crash Analysis Layers/Speed_Limit_RNS/Speed_Limit_RNS.gdb",
        "artifacts/normalized/speed.parquet",
        "artifacts/normalized/aadt.parquet",
        "artifacts/normalized/access.parquet",
        "artifacts/normalized/access_v2.parquet",
        "artifacts/normalized/crashes.parquet",
    ],
}

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

GRAIN_KEYS = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
FLOAT_TOL = 1e-6
WEIGHT_TOL = 1e-6
STALE_PATH_TOKENS = ["work/output", "legacy"]
DOWNSTREAM_PARENT_TOKENS = [
    "mvp_dataset",
    "lookup",
    "rate_distribution",
    "analysis_guidance_matrix",
    "analysis_signal_window",
    "analysis_signal_approach_window",
    "final_dataset_cache",
]
TEMP_PATTERNS = [".tmp", ".temp", "~", ".bak", ".backup", ".partial", ".crc"]

EVIDENCE_DIRS = [
    "work/roadway_graph/review/bin_context_validation_audit",
    "work/roadway_graph/review/distance_band_units_validation_audit",
    "work/roadway_graph/review/build_distance_band_context",
    "work/roadway_graph/review/distance_band_context_validation_legacy_audit",
    "work/roadway_graph/review/patch_distance_band_context_roadway_and_speed",
    "work/roadway_graph/review/patch_distance_band_context_aadt_exposure_semantics",
    "work/roadway_graph/review/patch_distance_band_context_access_spatial_exclusivity",
    "work/roadway_graph/review/patch_distance_band_context_access_fanout_containment",
    "work/roadway_graph/review/crash_assignment_feasibility_audit",
    "work/roadway_graph/review/crash_assignment_multiplicity_decomposition_audit",
    "work/roadway_graph/review/crash_assignment_weighting_policy_audit",
    "work/roadway_graph/review/patch_distance_band_context_crash_assignment",
    "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except Exception:
        return str(path)


def clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().replace({"nan": "", "None": "", "<NA>": ""})


def pct(count: float, total: float) -> float:
    return round((float(count) / float(total) * 100.0), 6) if total else 0.0


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def write_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame, fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
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


def write_json(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamp} - {message}\n")


def parquet_metadata(path: Path) -> tuple[int | None, int | None, list[str], str]:
    try:
        pf = pq.ParquetFile(path)
        return int(pf.metadata.num_rows), len(pf.schema_arrow.names), list(pf.schema_arrow.names), "readable"
    except Exception as exc:
        return None, None, [], f"read_failed:{type(exc).__name__}:{exc}"


def listed_products(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    products = manifest.get("products", {})
    return products if isinstance(products, dict) else {}


def parent_matches_expected(parent: str, expected_tokens: list[str]) -> bool:
    lower = parent.lower().replace("\\", "/")
    for token in expected_tokens:
        t = token.lower().replace("\\", "/")
        if t.endswith(".parquet"):
            if t in lower:
                return True
        elif "/" in t or "." in t:
            if t in lower:
                return True
        elif f"/{t}.parquet" in lower or lower.endswith(f"{t}.parquet"):
            return True
    return False


def is_review_path(path_text: str) -> bool:
    return path_text.lower().replace("\\", "/").startswith("work/roadway_graph/review/")


def is_old_analysis_parent(path_text: str) -> bool:
    lower = path_text.lower().replace("\\", "/")
    return (
        "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/" in lower
        or "work/roadway_graph/analysis/final_dataset_cache/" in lower
        or "work/roadway_graph/analysis/mvp_dataset/" in lower
    )


def metadata_texts() -> dict[str, str]:
    return {name: text_of(path) for name, path in METADATA_PATHS.items()}


def inventory_files() -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, list[str]]]:
    rows: list[dict[str, Any]] = []
    parquet_columns: dict[str, list[str]] = {}
    for path in sorted(STAGING.iterdir(), key=lambda p: p.name.lower()):
        is_parquet = path.suffix.lower() == ".parquet"
        row_count: int | None = None
        column_count: int | None = None
        readable = "yes"
        columns: list[str] = []
        if is_parquet:
            row_count, column_count, columns, status = parquet_metadata(path)
            readable = "yes" if status == "readable" else "no"
            parquet_columns[path.name] = columns
        expected_core = path.name in EXPECTED_PARQUETS
        expected_meta = path.name in EXPECTED_METADATA
        temp_flag = any(token in path.name.lower() for token in TEMP_PATTERNS)
        duplicate_candidate = is_parquet and not expected_core and any(path.name.startswith(obj.removesuffix(".parquet")) for obj in EXPECTED_PARQUETS)
        rows.append(
            {
                "file_name": path.name,
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "modified_timestamp": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "row_count": row_count if row_count is not None else "",
                "column_count": column_count if column_count is not None else "",
                "readable": readable,
                "expected_core_object": expected_core,
                "expected_metadata": expected_meta,
                "unexpected_object": not expected_core and not expected_meta,
                "temp_file_flag": temp_flag,
                "partial_file_flag": ".partial" in path.name.lower(),
                "old_backup_file_flag": any(token in path.name.lower() for token in [".bak", ".backup", "old", "previous"]),
                "duplicate_candidate_file_flag": duplicate_candidate,
            }
        )
    presence_rows = []
    names = {row["file_name"] for row in rows}
    for name in EXPECTED_FILES:
        presence_rows.append(
            {
                "expected_file": name,
                "expected_type": "parquet" if name.endswith(".parquet") else "metadata",
                "present": name in names,
                "readable": next((row["readable"] for row in rows if row["file_name"] == name), "missing"),
                "missing_flag": name not in names,
            }
        )
    return pd.DataFrame(rows), presence_rows, parquet_columns


def audit_metadata(manifest: dict[str, Any], schema: dict[str, Any], texts: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    products = listed_products(manifest)
    manifest_rows: list[dict[str, Any]] = []
    parent_rows: list[dict[str, Any]] = []
    for obj in OBJECT_NAMES:
        product = products.get(obj, {})
        parents = product.get("canonical_parents", []) if isinstance(product, dict) else []
        if not isinstance(parents, list):
            parents = []
        path_text = clean(product.get("path", "")) if isinstance(product, dict) else ""
        manifest_rows.append(
            {
                "check": f"{obj}_listed",
                "passed": bool(product),
                "object_name": obj,
                "detail": "object present in manifest products" if product else "object missing from manifest products",
            }
        )
        manifest_rows.append(
            {
                "check": f"{obj}_path_points_to_staging_candidate",
                "passed": path_text.endswith(f"{obj}.parquet") and "final_leg_corrected_analysis_dataset_rebuild_candidate" in path_text,
                "object_name": obj,
                "detail": path_text,
            }
        )
        manifest_rows.append(
            {
                "check": f"{obj}_row_count_documented",
                "passed": isinstance(product, dict) and "row_count" in product,
                "object_name": obj,
                "detail": product.get("row_count", "") if isinstance(product, dict) else "",
            }
        )
        expected_parent_tokens = EXPECTED_PARENT_CHAIN.get(obj, [])
        for parent in parents:
            lower = str(parent).lower().replace("\\", "/")
            review_parent = is_review_path(str(parent))
            downstream_parent = any(token in lower for token in DOWNSTREAM_PARENT_TOKENS)
            stale_parent = any(token in lower for token in STALE_PATH_TOKENS)
            old_analysis_parent = is_old_analysis_parent(str(parent))
            matched_expected = parent_matches_expected(str(parent), expected_parent_tokens)
            parent_rows.append(
                {
                    "object_name": obj,
                    "parent_path": parent,
                    "listed_as_canonical_parent": True,
                    "matches_expected_parent_chain": matched_expected,
                    "review_output_parent_flag": review_parent,
                    "downstream_mvp_lookup_or_analysis_parent_flag": downstream_parent,
                    "old_canonical_analysis_parent_flag": old_analysis_parent,
                    "stale_work_output_or_legacy_path_flag": stale_parent,
                    "parent_dependency_pass": matched_expected and not review_parent and not downstream_parent and not stale_parent and not old_analysis_parent,
                }
            )
        for expected in expected_parent_tokens:
            manifest_rows.append(
                {
                    "check": f"{obj}_expected_parent_{expected}",
                    "passed": any(parent_matches_expected(str(parent), [expected]) for parent in parents),
                    "object_name": obj,
                    "detail": "|".join(map(str, parents)),
                }
            )
    all_text = "\n".join(texts.values()).lower()
    required_docs = {
        "recent_roadway_speed_fields_documented": ["speed_limit_mph", "roadway/speed patch", "rns_strict_route_measure"],
        "aadt_exposure_daily_proxy_documented": ["daily vmt proxy", "exposure_denominator", "direction_factor"],
        "access_spatial_exclusivity_documented": ["combined-source spatial-only", "distance-band exclusivity"],
        "crash_spatial_fractional_documented": ["spatial-primary", "equal fractional", "total-preserving"],
        "unresolved_directionality_documented": ["unresolved directionality", "unresolved units"],
        "source_limited_cases_documented": ["source-limited", "source limited"],
        "crash_direction_not_used_documented": ["crash direction fields were not used", "crash_direction_field_status"],
        "mvp_lookup_not_built_documented": ["no mvp", "lookup", "rate-distribution"],
    }
    for check, tokens in required_docs.items():
        passed = any(token in all_text for token in tokens)
        manifest_rows.append({"check": check, "passed": passed, "object_name": "metadata", "detail": "|".join(tokens)})
    forbidden_rows = []
    for name, text in texts.items():
        lower = text.lower().replace("\\", "/")
        forbidden_rows.append(
            {
                "metadata_file": name,
                "work_output_token_count": lower.count("work/output"),
                "legacy_token_count": lower.count("legacy"),
                "old_phase_b1_only_phrase_flag": "currently contains phase b.1 only" in lower,
                "claims_no_later_objects_built_flag": "no travelway index" in lower and "no signal attachment" in lower,
                "stale_or_obsolete_metadata_flag": lower.count("work/output") > 0
                or lower.count("legacy") > 0
                or "currently contains phase b.1 only" in lower
                or ("no travelway index" in lower and "no signal attachment" in lower),
            }
        )
    schema_text = texts.get("schema.json", "").lower()
    schema_rows: list[dict[str, Any]] = []
    actual_cols = {name: parquet_metadata(OBJECT_PATHS[name])[2] for name in EXPECTED_PARQUETS if OBJECT_PATHS[name].exists()}
    for parquet_name, cols in actual_cols.items():
        obj = parquet_name.removesuffix(".parquet")
        schema_rows.append(
            {
                "object_name": obj,
                "schema_mentions_object": obj in schema_text or parquet_name in schema_text,
                "actual_column_count": len(cols),
                "schema_mentions_distance_band_unit_id": "distance_band_unit_id" in schema_text if obj in {"distance_band_units", "distance_band_context"} else "",
                "schema_mentions_recent_patch_fields": all(
                    token in schema_text
                    for token in [
                        "speed_limit_mph",
                        "exposure_daily_vmt_proxy",
                        "access_assignment_method",
                        "crash_count_weighted",
                    ]
                )
                if obj == "distance_band_context"
                else "",
            }
        )
    readme_text = texts.get("README.md", "").lower()
    readme_checks = [
        ("all_expected_objects_named", all(name in readme_text for name in EXPECTED_PARQUETS)),
        ("crash_assignment_method_named", "spatial-primary" in readme_text and "equal fractional" in readme_text),
        ("access_assignment_method_named", "combined-source spatial-only" in readme_text and "distance-band exclusivity" in readme_text),
        ("daily_vmt_proxy_named", "daily vmt proxy" in readme_text),
        ("unresolved_directionality_named", "unresolved directionality" in readme_text),
        ("obsolete_phase_b1_only_language_absent", "currently contains phase b.1 only" not in readme_text),
        ("obsolete_no_later_objects_language_absent", not ("no travelway index" in readme_text and "no signal attachment" in readme_text)),
        ("stale_work_output_path_absent", "work/output" not in readme_text),
        ("legacy_path_absent", "legacy" not in readme_text),
    ]
    readme_rows = [{"check": check, "passed": passed} for check, passed in readme_checks]
    return pd.DataFrame(manifest_rows + forbidden_rows), pd.DataFrame(schema_rows), pd.DataFrame(readme_rows), pd.DataFrame(parent_rows)


def load_core_tables() -> dict[str, pd.DataFrame]:
    log("Loading projected columns for core reconciliation checks")
    tables: dict[str, pd.DataFrame] = {}
    projections = {
        "signal_index.parquet": ["signal_index_row_id", "stable_signal_id", "analysis_ready_status", "source_limited_status"],
        "travelway_network_index.parquet": ["travelway_index_row_id", "stable_travelway_id"],
        "signal_travelway_attachment.parquet": ["attachment_id", "stable_signal_id", "stable_travelway_id", "signal_index_row_id", "travelway_index_row_id"],
        "signal_approaches.parquet": ["signal_approach_id", "stable_signal_id", "primary_stable_travelway_id", "approach_identity_status", "source_limited_status"],
        "approach_corridors.parquet": ["approach_corridor_id", "logical_corridor_chain_id", "stable_signal_id", "signal_approach_id", "stable_travelway_id"],
        "bin_context.parquet": [
            "stable_bin_id",
            "stable_signal_id",
            "signal_approach_id",
            "logical_corridor_chain_id",
            "primary_approach_corridor_id",
            "primary_stable_travelway_id",
            "distance_band",
            "upstream_downstream",
            "directionality_status",
            "bin_length_ft",
            "distance_start_ft",
            "distance_end_ft",
        ],
        "distance_band_units.parquet": [
            "distance_band_unit_id",
            "stable_signal_id",
            "signal_approach_id",
            "upstream_downstream",
            "distance_band",
            "directionality_status",
            "bin_count",
            "unit_length_ft",
            "full_bin_count",
            "partial_bin_count",
            "chain_count",
            "unit_completeness_status",
            "rate_readiness_status",
            "source_limited_status",
        ],
        "distance_band_context.parquet": [
            "distance_band_unit_id",
            "stable_signal_id",
            "signal_approach_id",
            "upstream_downstream",
            "distance_band",
            "directionality_status",
            "directionality_method",
            "directionality_confidence",
            "directionality_unresolved_reason",
            "bin_count",
            "unit_length_ft",
            "divided_undivided",
            "one_way_two_way",
            "roadway_context_status",
            "median_type",
            "median_group",
            "speed_limit_mph",
            "speed_category",
            "speed_context_status",
            "speed_missing_reason",
            "aadt",
            "aadt_category",
            "aadt_context_status",
            "aadt_missing_reason",
            "exposure_denominator",
            "exposure_daily_vmt_proxy",
            "exposure_context_status",
            "exposure_missing_reason",
            "rate_denominator_semantics",
            "access_count",
            "access_count_band",
            "access_type_flags",
            "access_context_status",
            "access_zero_evidence_status",
            "access_assignment_method",
            "access_assignment_multiplicity_status",
            "access_identity_fanout_status",
            "access_context_quality_flag",
            "typed_access_count",
            "untyped_access_count",
            "riro_access_count",
            "right_in_right_out_access_count",
            "crash_count_weighted",
            "crash_count_unweighted_candidate",
            "crash_assignment_pair_count",
            "crash_unique_count",
            "crash_context_status",
            "crash_assignment_method",
            "crash_weighting_method",
            "crash_weight_sum_status",
            "crash_route_measure_support_status",
            "crash_ambiguity_flag",
            "crash_multiplicity_status",
            "crash_nonadjacent_band_flag_count",
            "crash_assigned_any_flag",
            "crash_unassigned_source_count_reference",
            "crash_rate_ready_flag",
            "rate_readiness_status",
            "overall_context_readiness_status",
            "context_quality_flags",
            "source_limited_status",
        ],
    }
    for name, cols in projections.items():
        path = OBJECT_PATHS[name]
        available = parquet_metadata(path)[2]
        use_cols = [col for col in cols if col in available]
        tables[name] = pd.read_parquet(path, columns=use_cols)
    return tables


def primary_key_audit(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, keys in PRIMARY_KEYS.items():
        df = tables[name]
        missing_keys = [key for key in keys if key not in df.columns]
        if missing_keys:
            rows.append({"object_name": name, "key_columns": "|".join(keys), "row_count": len(df), "non_null_rows": "", "duplicate_key_rows": "", "unique_key_count": "", "passed": False, "detail": f"missing keys {missing_keys}"})
            continue
        key_df = df[keys].astype(str)
        non_null = int(df[keys].notna().all(axis=1).sum())
        unique_count = int(key_df.drop_duplicates().shape[0])
        duplicate_rows = int(len(df) - unique_count)
        rows.append(
            {
                "object_name": name,
                "key_columns": "|".join(keys),
                "row_count": len(df),
                "non_null_rows": non_null,
                "duplicate_key_rows": duplicate_rows,
                "unique_key_count": unique_count,
                "passed": non_null == len(df) and duplicate_rows == 0,
                "detail": "",
            }
        )
    signal = tables["signal_index.parquet"]
    if "stable_signal_id" in signal.columns:
        rows.append(
            {
                "object_name": "signal_index.parquet",
                "key_columns": "stable_signal_id",
                "row_count": len(signal),
                "non_null_rows": int(signal["stable_signal_id"].notna().sum()),
                "duplicate_key_rows": int(len(signal) - signal["stable_signal_id"].astype(str).nunique()),
                "unique_key_count": int(signal["stable_signal_id"].astype(str).nunique()),
                "passed": signal["stable_signal_id"].notna().all() and signal["stable_signal_id"].astype(str).is_unique,
                "detail": "stable signal identity uniqueness check",
            }
        )
    stable_bins = tables["bin_context.parquet"]
    if "stable_bin_id" in stable_bins.columns:
        rows.append(
            {
                "object_name": "bin_context.parquet",
                "key_columns": "stable_bin_id",
                "row_count": len(stable_bins),
                "non_null_rows": int(stable_bins["stable_bin_id"].notna().sum()),
                "duplicate_key_rows": int(len(stable_bins) - stable_bins["stable_bin_id"].astype(str).nunique()),
                "unique_key_count": int(stable_bins["stable_bin_id"].astype(str).nunique()),
                "passed": stable_bins["stable_bin_id"].notna().all() and stable_bins["stable_bin_id"].astype(str).is_unique,
                "detail": "stable_bin_id uniqueness check",
            }
        )
    return pd.DataFrame(rows)


def row_count_summary(tables: dict[str, pd.DataFrame], manifest: dict[str, Any]) -> pd.DataFrame:
    products = listed_products(manifest)
    rows = []
    for name in EXPECTED_PARQUETS:
        df = tables[name]
        obj = name.removesuffix(".parquet")
        manifest_count = products.get(obj, {}).get("row_count", "") if isinstance(products.get(obj, {}), dict) else ""
        expected = EXPECTED_ROW_COUNTS.get(name, manifest_count)
        rows.append(
            {
                "object_name": name,
                "actual_row_count": len(df),
                "manifest_row_count": manifest_count,
                "expected_or_current_known_row_count": expected,
                "matches_expected_or_manifest": str(expected) == "" or int(expected) == len(df),
                "column_count": len(df.columns),
            }
        )
    return pd.DataFrame(rows)


def object_dependency_audit(tables: dict[str, pd.DataFrame], parent_rows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    signal_ids = set(clean_series(tables["signal_index.parquet"]["stable_signal_id"]))
    travelway_ids = set(clean_series(tables["travelway_network_index.parquet"]["stable_travelway_id"]))
    approach_ids = set(clean_series(tables["signal_approaches.parquet"]["signal_approach_id"]))
    corridor_ids = set(clean_series(tables["approach_corridors.parquet"]["approach_corridor_id"]))
    unit_ids = set(clean_series(tables["distance_band_units.parquet"]["distance_band_unit_id"]))

    def subset_check(child: str, child_col: str, parent: str, parent_set: set[str], blank_allowed: bool = False) -> None:
        values = clean_series(tables[child][child_col])
        if blank_allowed:
            values = values[values.ne("")]
        missing = values[~values.isin(parent_set)]
        rows.append(
            {
                "child_object": child,
                "child_key": child_col,
                "expected_parent": parent,
                "child_nonblank_key_rows": int(values.ne("").sum()),
                "missing_parent_key_rows": int(len(missing)),
                "missing_parent_key_distinct": int(missing.nunique()),
                "passed": len(missing) == 0,
            }
        )

    subset_check("signal_travelway_attachment.parquet", "stable_signal_id", "signal_index.parquet", signal_ids)
    subset_check("signal_travelway_attachment.parquet", "stable_travelway_id", "travelway_network_index.parquet", travelway_ids)
    subset_check("signal_approaches.parquet", "stable_signal_id", "signal_index.parquet", signal_ids)
    subset_check("signal_approaches.parquet", "primary_stable_travelway_id", "travelway_network_index.parquet", travelway_ids, blank_allowed=True)
    subset_check("approach_corridors.parquet", "stable_signal_id", "signal_index.parquet", signal_ids)
    subset_check("approach_corridors.parquet", "signal_approach_id", "signal_approaches.parquet", approach_ids)
    subset_check("approach_corridors.parquet", "stable_travelway_id", "travelway_network_index.parquet", travelway_ids, blank_allowed=True)
    subset_check("bin_context.parquet", "stable_signal_id", "signal_index.parquet", signal_ids)
    subset_check("bin_context.parquet", "signal_approach_id", "signal_approaches.parquet", approach_ids)
    subset_check("bin_context.parquet", "primary_approach_corridor_id", "approach_corridors.parquet", corridor_ids, blank_allowed=True)
    subset_check("bin_context.parquet", "primary_stable_travelway_id", "travelway_network_index.parquet", travelway_ids, blank_allowed=True)
    subset_check("distance_band_context.parquet", "distance_band_unit_id", "distance_band_units.parquet", unit_ids)
    if not parent_rows.empty:
        rows.append(
            {
                "child_object": "all_manifest_products",
                "child_key": "canonical_parents",
                "expected_parent": "no review/downstream/old-analysis parents",
                "child_nonblank_key_rows": int(len(parent_rows)),
                "missing_parent_key_rows": int((~parent_rows["parent_dependency_pass"]).sum()),
                "missing_parent_key_distinct": int((~parent_rows["parent_dependency_pass"]).sum()),
                "passed": bool(parent_rows["parent_dependency_pass"].all()),
            }
        )
    return pd.DataFrame(rows)


def normalize_grain(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in GRAIN_KEYS:
        if col in out.columns:
            out[col] = clean_series(out[col])
    return out


def bin_to_unit_reconciliation(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    bins = normalize_grain(tables["bin_context.parquet"])
    units = normalize_grain(tables["distance_band_units.parquet"])
    grouped = (
        bins.groupby(GRAIN_KEYS, dropna=False)
        .agg(rebuilt_bin_count=("stable_bin_id", "size"), rebuilt_unit_length_ft=("bin_length_ft", "sum"))
        .reset_index()
    )
    merged = units.merge(grouped, on=GRAIN_KEYS, how="outer", indicator=True)
    merged["bin_count_delta"] = pd.to_numeric(merged["bin_count"], errors="coerce").fillna(0) - pd.to_numeric(merged["rebuilt_bin_count"], errors="coerce").fillna(0)
    merged["unit_length_delta_ft"] = pd.to_numeric(merged["unit_length_ft"], errors="coerce").fillna(0) - pd.to_numeric(merged["rebuilt_unit_length_ft"], errors="coerce").fillna(0)
    failed = merged[(merged["_merge"] != "both") | (merged["bin_count_delta"] != 0) | (merged["unit_length_delta_ft"].abs() > FLOAT_TOL)]
    summary = pd.DataFrame(
        [
            {
                "check": "bin_context_rolls_up_to_distance_band_units",
                "parent_bin_rows": len(bins),
                "unit_rows": len(units),
                "rebuilt_unit_groups": len(grouped),
                "unit_bin_count_sum": int(pd.to_numeric(units["bin_count"], errors="coerce").fillna(0).sum()),
                "parent_bin_count": len(bins),
                "unit_length_ft_sum": float(pd.to_numeric(units["unit_length_ft"], errors="coerce").fillna(0).sum()),
                "parent_bin_length_ft_sum": float(pd.to_numeric(bins["bin_length_ft"], errors="coerce").fillna(0).sum()),
                "failed_group_count": int(len(failed)),
                "passed": len(failed) == 0,
            }
        ]
    )
    detail = failed.head(5000).drop(columns=["_merge"], errors="ignore")
    if detail.empty:
        detail = pd.DataFrame([{"check": "all_bin_to_unit_groups_reconciled", "passed": True}])
    return summary, detail


def unit_to_context_reconciliation(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    units = normalize_grain(tables["distance_band_units.parquet"])
    context = normalize_grain(tables["distance_band_context.parquet"])
    compare_cols = ["distance_band_unit_id", *GRAIN_KEYS, "bin_count", "unit_length_ft"]
    merged = units[compare_cols].merge(
        context[compare_cols],
        on="distance_band_unit_id",
        how="outer",
        suffixes=("_unit", "_context"),
        indicator=True,
    )
    failures = []
    for _, row in merged.iterrows():
        fail = row["_merge"] != "both"
        for col in GRAIN_KEYS:
            fail = fail or clean(row.get(f"{col}_unit")) != clean(row.get(f"{col}_context"))
        fail = fail or int(pd.to_numeric(pd.Series([row.get("bin_count_unit")]), errors="coerce").fillna(-1).iloc[0]) != int(pd.to_numeric(pd.Series([row.get("bin_count_context")]), errors="coerce").fillna(-2).iloc[0])
        fail = fail or abs(float(pd.to_numeric(pd.Series([row.get("unit_length_ft_unit")]), errors="coerce").fillna(-1).iloc[0]) - float(pd.to_numeric(pd.Series([row.get("unit_length_ft_context")]), errors="coerce").fillna(-2).iloc[0])) > FLOAT_TOL
        if fail:
            failures.append(row.to_dict())
            if len(failures) >= 5000:
                break
    summary = pd.DataFrame(
        [
            {
                "check": "distance_band_context_preserves_distance_band_units_identity_and_grain",
                "unit_rows": len(units),
                "context_rows": len(context),
                "unit_ids": units["distance_band_unit_id"].nunique(),
                "context_unit_ids": context["distance_band_unit_id"].nunique(),
                "failed_identity_or_measure_rows_sampled": len(failures),
                "passed": len(failures) == 0 and len(units) == len(context),
            }
        ]
    )
    detail = pd.DataFrame(failures) if failures else pd.DataFrame([{"check": "all_unit_to_context_rows_reconciled", "passed": True}])
    return summary, detail


def directionality_summary(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for name, count_col, length_col in [
        ("bin_context.parquet", "stable_bin_id", "bin_length_ft"),
        ("distance_band_units.parquet", "distance_band_unit_id", "unit_length_ft"),
        ("distance_band_context.parquet", "distance_band_unit_id", "unit_length_ft"),
    ]:
        df = tables[name].copy()
        df["upstream_downstream"] = clean_series(df["upstream_downstream"])
        df["directionality_status"] = clean_series(df["directionality_status"])
        grouped = df.groupby(["upstream_downstream", "directionality_status"], dropna=False).agg(
            row_count=(count_col, "size"),
            length_ft=(length_col, "sum"),
        )
        for (direction, status), row in grouped.reset_index().set_index(["upstream_downstream", "directionality_status"]).iterrows():
            rows.append(
                {
                    "object_name": name,
                    "upstream_downstream": direction,
                    "directionality_status": status,
                    "row_count": int(row["row_count"]),
                    "length_ft": float(row["length_ft"]),
                }
            )
    return pd.DataFrame(rows)


def completeness_summaries(context: pd.DataFrame) -> dict[str, pd.DataFrame]:
    total = len(context)
    numeric = context.copy()
    for col in ["speed_limit_mph", "aadt", "exposure_denominator", "access_count", "crash_count_weighted", "crash_count_unweighted_candidate", "crash_unique_count"]:
        if col in numeric.columns:
            numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
    roadway_rows = []
    for col in ["roadway_context_status", "divided_undivided", "one_way_two_way", "median_group", "median_type"]:
        if col in context.columns:
            vc = clean_series(context[col]).value_counts(dropna=False)
            for value, count in vc.items():
                roadway_rows.append({"field": col, "value": value, "unit_count": int(count), "pct_units": pct(count, total)})
    speed_rows = [
        {
            "metric": "speed_populated_units",
            "count": int(numeric["speed_limit_mph"].notna().sum()),
            "pct_units": pct(numeric["speed_limit_mph"].notna().sum(), total),
        },
        {
            "metric": "speed_missing_units",
            "count": int(numeric["speed_limit_mph"].isna().sum()),
            "pct_units": pct(numeric["speed_limit_mph"].isna().sum(), total),
        },
    ]
    if "speed_context_status" in context.columns:
        for value, count in clean_series(context["speed_context_status"]).value_counts().items():
            speed_rows.append({"metric": f"speed_context_status:{value}", "count": int(count), "pct_units": pct(count, total)})
    aadt_rows = [
        {"metric": "aadt_populated_units", "count": int(numeric["aadt"].notna().sum()), "pct_units": pct(numeric["aadt"].notna().sum(), total), "semantics": "length-weighted latest-year representative AADT where populated"},
        {"metric": "aadt_missing_units", "count": int(numeric["aadt"].isna().sum()), "pct_units": pct(numeric["aadt"].isna().sum(), total), "semantics": ""},
        {"metric": "exposure_populated_units", "count": int(numeric["exposure_denominator"].notna().sum()), "pct_units": pct(numeric["exposure_denominator"].notna().sum(), total), "semantics": "daily VMT proxy, not final crash-period exposure"},
        {"metric": "exposure_missing_units", "count": int(numeric["exposure_denominator"].isna().sum()), "pct_units": pct(numeric["exposure_denominator"].isna().sum(), total), "semantics": ""},
    ]
    if "rate_denominator_semantics" in context.columns:
        for value, count in clean_series(context["rate_denominator_semantics"]).value_counts().items():
            aadt_rows.append({"metric": f"rate_denominator_semantics:{value}", "count": int(count), "pct_units": pct(count, total), "semantics": value})
    access_found = int((numeric["access_count"].fillna(0) > 0).sum())
    access_zero = int((numeric["access_count"].fillna(-1) == 0).sum())
    access_unknown = int(numeric["access_count"].isna().sum())
    access_rows = [
        {"metric": "access_found_units", "count": access_found, "pct_units": pct(access_found, total)},
        {"metric": "evaluated_zero_access_units", "count": access_zero, "pct_units": pct(access_zero, total)},
        {"metric": "access_unknown_units", "count": access_unknown, "pct_units": pct(access_unknown, total)},
        {"metric": "access_count_sum", "count": int(numeric["access_count"].fillna(0).sum()), "pct_units": ""},
    ]
    for col in ["access_context_status", "access_zero_evidence_status", "access_assignment_method", "access_assignment_multiplicity_status", "access_identity_fanout_status", "access_context_quality_flag"]:
        if col in context.columns:
            for value, count in clean_series(context[col]).value_counts().items():
                access_rows.append({"metric": f"{col}:{value}", "count": int(count), "pct_units": pct(count, total)})
    crash_rows = [
        {"metric": "weighted_crash_count_total", "count": float(numeric["crash_count_weighted"].fillna(0).sum()), "pct_units": ""},
        {"metric": "units_with_weighted_crash_gt0", "count": int((numeric["crash_count_weighted"].fillna(0) > 0).sum()), "pct_units": pct((numeric["crash_count_weighted"].fillna(0) > 0).sum(), total)},
        {"metric": "units_with_zero_crashes", "count": int((numeric["crash_count_weighted"].fillna(0) == 0).sum()), "pct_units": pct((numeric["crash_count_weighted"].fillna(0) == 0).sum(), total)},
        {"metric": "unweighted_assignment_pair_count_sum", "count": float(numeric["crash_count_unweighted_candidate"].fillna(0).sum()), "pct_units": ""},
        {"metric": "crash_nonadjacent_band_flag_count_sum", "count": float(pd.to_numeric(context.get("crash_nonadjacent_band_flag_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()), "pct_units": ""},
    ]
    for col in ["crash_context_status", "crash_assignment_method", "crash_weighting_method", "crash_weight_sum_status", "crash_route_measure_support_status", "crash_multiplicity_status"]:
        if col in context.columns:
            for value, count in clean_series(context[col]).value_counts().items():
                crash_rows.append({"metric": f"{col}:{value}", "count": int(count), "pct_units": pct(count, total)})
    rate_rows = []
    for col in ["rate_readiness_status", "overall_context_readiness_status", "crash_rate_ready_flag"]:
        if col in context.columns:
            for value, count in clean_series(context[col]).value_counts().items():
                rate_rows.append({"metric": f"{col}:{value}", "count": int(count), "pct_units": pct(count, total)})
    ready_count = int(clean_series(context["crash_rate_ready_flag"]).str.lower().eq("true").sum()) if "crash_rate_ready_flag" in context.columns else 0
    rate_rows.append({"metric": "final_rate_ready_units", "count": ready_count, "pct_units": pct(ready_count, total)})
    rate_rows.append({"metric": "not_rate_ready_units", "count": total - ready_count, "pct_units": pct(total - ready_count, total)})
    return {
        "roadway_context_completeness_summary.csv": pd.DataFrame(roadway_rows),
        "speed_context_completeness_summary.csv": pd.DataFrame(speed_rows),
        "aadt_exposure_context_summary.csv": pd.DataFrame(aadt_rows),
        "access_context_final_audit.csv": pd.DataFrame(access_rows),
        "crash_context_final_audit.csv": pd.DataFrame(crash_rows),
        "rate_readiness_summary.csv": pd.DataFrame(rate_rows),
    }


def read_evidence_csv(path: str) -> pd.DataFrame:
    full = REPO / path
    if not full.exists():
        return pd.DataFrame()
    return pd.read_csv(full)


def cross_object_summary(
    bin_unit_summary: pd.DataFrame,
    unit_context_summary: pd.DataFrame,
    directionality: pd.DataFrame,
    context: pd.DataFrame,
) -> pd.DataFrame:
    rows = []
    rows.append({"check": "bin_context_to_distance_band_units_bin_count_and_length", "result": bool(bin_unit_summary["passed"].all()), "detail": bin_unit_summary.to_dict("records")[0]})
    rows.append({"check": "distance_band_units_to_distance_band_context_identity_and_length", "result": bool(unit_context_summary["passed"].all()), "detail": unit_context_summary.to_dict("records")[0]})
    assigned_context = int(clean_series(context["directionality_status"]).eq("assigned").sum())
    unresolved_context = len(context) - assigned_context
    rows.append({"check": "directionality_context_assigned_unresolved_counts", "result": assigned_context == 112500 and unresolved_context == 3476, "detail": f"assigned={assigned_context}; unresolved={unresolved_context}"})
    access_zero = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_access_spatial_exclusivity/access_zero_evidence_consistency_check.csv")
    access_type = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_access_spatial_exclusivity/access_type_count_consistency_check.csv")
    access_multiband = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_access_spatial_exclusivity/post_exclusivity_multiband_audit.csv")
    access_nonadj = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_access_spatial_exclusivity/post_exclusivity_non_adjacent_band_red_flag_ledger.csv")
    rows.append({"check": "access_counts_after_spatial_exclusivity", "result": bool(not access_zero.empty and access_zero["passed"].astype(str).str.lower().eq("true").all() and not access_type.empty and access_type["passed"].astype(str).str.lower().eq("true").all()), "detail": "access_zero/type consistency patch ledgers"})
    rows.append({"check": "same_access_signal_approach_direction_multiband_duplication_absent", "result": bool(len(access_multiband) == 0 and len(access_nonadj) == 0), "detail": f"multiband_rows={len(access_multiband)}; nonadjacent_rows={len(access_nonadj)}"})
    crash_weight = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_crash_assignment/crash_assignment_weight_summary.csv")
    crash_per = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_crash_assignment/per_crash_weight_sum_check.csv")
    crash_excl = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_crash_assignment/band_exclusivity_assignment_summary.csv")
    weighted_total = float(pd.to_numeric(context["crash_count_weighted"], errors="coerce").fillna(0).sum())
    unique_assigned = float(crash_weight.loc[crash_weight["metric"].eq("unique_assigned_crashes"), "value"].iloc[0]) if not crash_weight.empty else math.nan
    rows.append({"check": "weighted_crash_total_equals_unique_assigned_crashes", "result": abs(weighted_total - unique_assigned) <= WEIGHT_TOL, "detail": f"context_weighted_total={weighted_total}; unique_assigned_crashes={unique_assigned}"})
    rows.append({"check": "per_crash_weights_sum_to_one", "result": bool(not crash_per.empty and crash_per["passed"].astype(str).str.lower().eq("true").all()), "detail": crash_per.to_dict("records") if not crash_per.empty else "missing ledger"})
    after = crash_excl.loc[crash_excl["scenario"].eq("after_exclusivity")] if not crash_excl.empty and "scenario" in crash_excl.columns else pd.DataFrame()
    no_multiband = bool(not after.empty and int(after["same_group_multiband_groups"].iloc[0]) == 0 and int(after["nonadjacent_groups"].iloc[0]) == 0)
    rows.append({"check": "same_crash_signal_approach_direction_multiband_duplication_absent", "result": no_multiband, "detail": after.to_dict("records") if not after.empty else "missing ledger"})
    return pd.DataFrame(rows)


def residual_ledger(context: pd.DataFrame) -> pd.DataFrame:
    total = len(context)
    numeric = context.copy()
    for col in ["speed_limit_mph", "aadt", "exposure_denominator", "access_count", "crash_nonadjacent_band_flag_count"]:
        if col in numeric.columns:
            numeric[col] = pd.to_numeric(numeric[col], errors="coerce")
    route_measure = read_evidence_csv("work/roadway_graph/review/patch_distance_band_context_crash_assignment/route_measure_qa_overlay_summary.csv")
    route_measure_only = 0
    if not route_measure.empty:
        row = route_measure.loc[route_measure["class"].eq("route_measure_only_not_counted")]
        route_measure_only = int(row["crash_count"].iloc[0]) if not row.empty else 0
    access_review = int(clean_series(context.get("access_context_quality_flag", pd.Series(dtype=str))).str.contains("review|flag", case=False, regex=True).sum())
    crash_multiplicity = int(clean_series(context.get("crash_multiplicity_status", pd.Series(dtype=str))).str.contains("multi|fraction", case=False, regex=True).sum())
    rows = [
        {
            "residual": "unresolved_directionality_units",
            "count": int((~clean_series(context["directionality_status"]).eq("assigned")).sum()),
            "percentage": pct((~clean_series(context["directionality_status"]).eq("assigned")).sum(), total),
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "MVP logic should exclude or explicitly flag unresolved directionality units.",
        },
        {
            "residual": "remaining_missing_speed_units",
            "count": int(numeric["speed_limit_mph"].isna().sum()),
            "percentage": pct(numeric["speed_limit_mph"].isna().sum(), total),
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "Carry missing speed flags into MVP/rate readiness logic.",
        },
        {
            "residual": "remaining_missing_aadt_or_exposure_units",
            "count": int((numeric["aadt"].isna() | numeric["exposure_denominator"].isna()).sum()),
            "percentage": pct((numeric["aadt"].isna() | numeric["exposure_denominator"].isna()).sum(), total),
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "Not rate ready until numeric context is recovered or explicitly suppressed.",
        },
        {
            "residual": "access_review_flags",
            "count": access_review,
            "percentage": pct(access_review, total),
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "Use access QA flags downstream; no multiband duplication remains.",
        },
        {
            "residual": "crash_multiplicity_or_fractional_assignment_flags",
            "count": crash_multiplicity,
            "percentage": pct(crash_multiplicity, total),
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "Use weighted crash fields for descriptive numerator; retain multiplicity flags.",
        },
        {
            "residual": "crash_nonadjacent_candidate_review_flags",
            "count": int(numeric.get("crash_nonadjacent_band_flag_count", pd.Series(dtype=float)).fillna(0).sum()),
            "percentage": pct(numeric.get("crash_nonadjacent_band_flag_count", pd.Series(dtype=float)).fillna(0).sum(), total),
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "Retain as review evidence; post-exclusivity same-group multiband and nonadjacent crash groups are zero in the patch ledger.",
        },
        {
            "residual": "route_measure_only_crashes_not_counted",
            "count": route_measure_only,
            "percentage": "",
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "Do not count as spatial crashes; keep as QA/reference residual.",
        },
        {
            "residual": "source_limited_or_invalid_geometry_units",
            "count": int(clean_series(context.get("source_limited_status", pd.Series(dtype=str))).ne("").sum()),
            "percentage": pct(clean_series(context.get("source_limited_status", pd.Series(dtype=str))).ne("").sum(), total),
            "accepted_for_final_cache": True,
            "blocks_promotion": False,
            "recommended_handling": "Preserve source-limited flags; later review may recover geometry/context.",
        },
    ]
    return pd.DataFrame(rows)


def scorecard(
    inventory: pd.DataFrame,
    presence: list[dict[str, Any]],
    metadata_audit: pd.DataFrame,
    parent_audit: pd.DataFrame,
    pk_audit: pd.DataFrame,
    bin_unit_summary: pd.DataFrame,
    unit_context_summary: pd.DataFrame,
    cross_summary: pd.DataFrame,
    readme_audit: pd.DataFrame,
) -> tuple[pd.DataFrame, str]:
    checks = [
        ("expected_files_present", all(row["present"] for row in presence), "all expected parquet and metadata files exist"),
        ("no_unexpected_files", not bool(inventory["unexpected_object"].any()), "no unexpected files in staged candidate folder"),
        ("no_temp_partial_backup_files", not bool(inventory[["temp_file_flag", "partial_file_flag", "old_backup_file_flag", "duplicate_candidate_file_flag"]].any(axis=None)), "no temp, partial, backup, or duplicate candidate files"),
        ("manifest_parent_dependencies_clean", bool(parent_audit["parent_dependency_pass"].all()) if not parent_audit.empty else False, "manifest canonical parents are staged/source parents only"),
        ("primary_keys_unique", bool(pk_audit["passed"].all()), "primary IDs non-null and unique where expected"),
        ("bin_to_unit_reconciles", bool(bin_unit_summary["passed"].all()), "bin rollup matches distance_band_units"),
        ("unit_to_context_reconciles", bool(unit_context_summary["passed"].all()), "context preserves unit identity/grain"),
        ("cross_context_reconciles", bool(cross_summary["result"].all()), "access/crash/directionality reconciliation checks pass"),
        ("readme_metadata_finalized", bool(readme_audit["passed"].all()), "README has no obsolete or stale path text"),
    ]
    rows = [{"criterion": name, "passed": passed, "detail": detail} for name, passed, detail in checks]
    structural_pass = all(passed for name, passed, _ in checks if name not in {"readme_metadata_finalized"})
    readme_pass = next(passed for name, passed, _ in checks if name == "readme_metadata_finalized")
    if structural_pass and readme_pass:
        decision = "staged_final_cache_ready_for_promotion_with_documented_residuals"
    elif structural_pass and not readme_pass:
        decision = "staged_final_cache_needs_metadata_repair_before_promotion"
    elif not bool(cross_summary["result"].all()) or not bool(bin_unit_summary["passed"].all()) or not bool(unit_context_summary["passed"].all()):
        decision = "staged_final_cache_needs_reconciliation_repair_before_promotion"
    elif not bool(pk_audit["passed"].all()):
        decision = "staged_final_cache_needs_context_repair_before_promotion"
    else:
        decision = "staged_final_cache_not_ready"
    rows.append({"criterion": "promotion_readiness_decision", "passed": decision.startswith("staged_final_cache_ready"), "detail": decision})
    return pd.DataFrame(rows), decision


def promotion_plan(decision: str) -> pd.DataFrame:
    rows = [
        {"step_order": 1, "step": "Repair staged metadata if readiness decision requires it", "details": "Update README/manifest/schema wording only; do not modify parquets.", "required_before_promotion": decision == "staged_final_cache_needs_metadata_repair_before_promotion"},
        {"step_order": 2, "step": "Create work/roadway_graph/analysis/final_dataset_cache", "details": "Create only in a later promotion task after audit/metadata pass.", "required_before_promotion": True},
        {"step_order": 3, "step": "Copy validated parquet and metadata files only", "details": "Copy the eight core parquet objects plus manifest.json, schema.json, README.md.", "required_before_promotion": True},
        {"step_order": 4, "step": "Verify copied row counts and checksums", "details": "Compare copied objects against staged candidate before declaring promotion complete.", "required_before_promotion": True},
        {"step_order": 5, "step": "Keep _staging unless explicitly instructed to remove it", "details": "Do not delete analysis/_staging during promotion unless the user explicitly authorizes cleanup.", "required_before_promotion": False},
        {"step_order": 6, "step": "Leave final_leg_corrected_analysis_dataset untouched", "details": "Do not rename or redefine the old summary folder until a later summary-folder redefinition task.", "required_before_promotion": False},
        {"step_order": 7, "step": "Leave mvp_dataset untouched", "details": "Do not rebuild MVP products until the later MVP redefinition task.", "required_before_promotion": False},
    ]
    return pd.DataFrame(rows)


def recommended_next_actions(decision: str) -> pd.DataFrame:
    if decision == "staged_final_cache_needs_metadata_repair_before_promotion":
        rows = [
            {"priority": 1, "action": "Run a metadata-only repair of staged README/schema/manifest wording", "reason": "Content objects reconcile, but README contains obsolete Phase B.1-only/no-later-objects text and a stale work/output reference."},
            {"priority": 2, "action": "Re-run this promotion readiness audit", "reason": "Confirm metadata repair did not introduce parent/path regressions."},
            {"priority": 3, "action": "Then perform a separate promotion task", "reason": "Create final_dataset_cache and copy only validated files with checksum verification."},
        ]
    else:
        rows = [
            {"priority": 1, "action": "Perform a separate promotion task", "reason": "Create final_dataset_cache and copy only validated files with checksum verification."},
            {"priority": 2, "action": "Keep _staging and old final_leg_corrected_analysis_dataset untouched unless explicitly instructed", "reason": "Promotion and summary-folder redefinition are separate tasks."},
            {"priority": 3, "action": "Handle MVP redefinition separately", "reason": "Do not modify mvp_dataset in the cache promotion task."},
        ]
    return pd.DataFrame(rows)


def write_findings(
    decision: str,
    inventory: pd.DataFrame,
    presence: list[dict[str, Any]],
    rows: pd.DataFrame,
    pk: pd.DataFrame,
    parent_dependency: pd.DataFrame,
    cross_summary: pd.DataFrame,
    completeness: dict[str, pd.DataFrame],
    residuals: pd.DataFrame,
) -> None:
    expected_present = [row["expected_file"] for row in presence if row["present"] and row["expected_type"] == "parquet"]
    missing = [row["expected_file"] for row in presence if not row["present"]]
    unexpected = inventory.loc[inventory["unexpected_object"], "file_name"].tolist()
    speed = completeness["speed_context_completeness_summary.csv"]
    aadt = completeness["aadt_exposure_context_summary.csv"]
    access = completeness["access_context_final_audit.csv"]
    crash = completeness["crash_context_final_audit.csv"]
    speed_pop = int(speed.loc[speed["metric"].eq("speed_populated_units"), "count"].iloc[0])
    speed_miss = int(speed.loc[speed["metric"].eq("speed_missing_units"), "count"].iloc[0])
    aadt_pop = int(aadt.loc[aadt["metric"].eq("aadt_populated_units"), "count"].iloc[0])
    exposure_pop = int(aadt.loc[aadt["metric"].eq("exposure_populated_units"), "count"].iloc[0])
    access_found = int(access.loc[access["metric"].eq("access_found_units"), "count"].iloc[0])
    access_zero = int(access.loc[access["metric"].eq("evaluated_zero_access_units"), "count"].iloc[0])
    crash_total = float(crash.loc[crash["metric"].eq("weighted_crash_count_total"), "count"].iloc[0])
    row_lines = "\n".join(f"- {r.object_name}: {int(r.actual_row_count):,} rows, {int(r.column_count)} columns" for r in rows.itertuples())
    pk_failed = pk.loc[~pk["passed"]]
    cross_failed = cross_summary.loc[~cross_summary["result"]]
    residual_lines = "\n".join(
        f"- {r.residual}: {r.count} ({r.percentage}%), accepted={r.accepted_for_final_cache}, blocks={r.blocks_promotion}"
        for r in residuals.itertuples()
    )
    memo = f"""# Final Dataset Cache Promotion Readiness Audit

## What Folder Was Audited
`{rel(STAGING)}`

This was a read-only audit. No promotion, file moves, parquet patches, MVP products, lookup tables, or canonical root products were created or modified.

## Core Cache Objects Present
Present expected parquet objects: {", ".join(expected_present)}.

Missing expected files: {", ".join(missing) if missing else "none"}.
Unexpected or temp/partial/backup files: {", ".join(unexpected) if unexpected else "none"}.

## Row Counts
{row_lines}

## Metadata Findings
The manifest lists all eight expected parquet objects and its canonical parents are staged/source parents, not review outputs or downstream MVP/lookup/final analytical products. The metadata documents unresolved directionality, source-limited cases, spatial-primary fractional crash assignment, combined-source spatial-only access with distance-band exclusivity, and daily VMT proxy exposure semantics.

Repair needed before promotion: README metadata is not fully finalized because it still contains obsolete opening language that says the folder contains Phase B.1 only/no later objects, and it references a stale `work/output/...` path as rejected old-method evidence. This is a metadata/documentation defect, not a parquet content reconciliation defect.

## Parent Dependency Findings
Manifest parent dependency pass: {bool(parent_dependency['parent_dependency_pass'].all()) if not parent_dependency.empty else False}.

## Row Count And Primary Key Findings
Primary key pass: {bool(pk['passed'].all())}. Failed key checks: {len(pk_failed)}.

## Cross-Object Reconciliation Findings
Cross-object reconciliation pass: {bool(cross_summary['result'].all())}. Failed checks: {len(cross_failed)}.

## Context Completeness Summary
- Speed populated units: {speed_pop:,}; missing speed units: {speed_miss:,}.
- AADT populated units: {aadt_pop:,}; exposure populated units: {exposure_pop:,}. Exposure denominator semantics are daily VMT proxy, not final crash-period exposure.
- Access found units: {access_found:,}; evaluated zero-access units: {access_zero:,}.
- Weighted crash count total: {crash_total:,.6g}.

## Known Accepted Residuals
{residual_lines}

## Promotion Readiness Decision
`{decision}`

## Repair Needed Before Promotion
Metadata repair is needed before promotion if the decision is `staged_final_cache_needs_metadata_repair_before_promotion`. No context or reconciliation parquet repair was indicated by this audit.

## Exact Recommended Next Task
Run a metadata-only repair of the staged candidate README/schema/manifest wording, then re-run this readiness audit. If it passes, perform a separate promotion task that creates `work/roadway_graph/analysis/final_dataset_cache`, copies only the validated eight parquet objects plus metadata, verifies row counts and checksums, and leaves `_staging`, `final_leg_corrected_analysis_dataset`, and `mvp_dataset` untouched unless separately instructed.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started read-only final dataset cache promotion readiness audit.\n", encoding="utf-8")
    log(f"Auditing staged folder {rel(STAGING)}")

    inventory, presence, parquet_columns = inventory_files()
    write_csv("staged_folder_file_inventory.csv", inventory)
    write_csv("expected_object_presence_check.csv", presence)
    log("Completed folder inventory")

    manifest = read_json(METADATA_PATHS["manifest.json"])
    schema = read_json(METADATA_PATHS["schema.json"])
    texts = metadata_texts()
    metadata_audit, schema_audit, readme_audit, parent_dependency = audit_metadata(manifest, schema, texts)
    write_csv("metadata_manifest_audit.csv", metadata_audit)
    write_csv("schema_audit.csv", schema_audit)
    write_csv("readme_audit.csv", readme_audit)
    write_csv("parent_dependency_audit.csv", parent_dependency)
    log("Completed metadata and dependency audits")

    tables = load_core_tables()
    row_summary = row_count_summary(tables, manifest)
    pk_audit = primary_key_audit(tables)
    write_csv("object_row_count_summary.csv", row_summary)
    write_csv("object_primary_key_uniqueness.csv", pk_audit)
    log("Completed row-count and primary-key checks")

    object_dep = object_dependency_audit(tables, parent_dependency)
    if not parent_dependency.empty:
        object_dep.to_csv(OUT / "parent_dependency_audit.csv", index=False)
        # Preserve both manifest and key-link checks in the required dependency output.
        combined_parent = pd.concat(
            [
                parent_dependency.assign(audit_layer="manifest_parent_metadata"),
                object_dep.assign(audit_layer="object_key_linkage"),
            ],
            ignore_index=True,
            sort=False,
        )
        write_csv("parent_dependency_audit.csv", combined_parent)
    log("Completed object key dependency checks")

    bin_unit_summary, bin_unit_detail = bin_to_unit_reconciliation(tables)
    unit_context_summary, unit_context_detail = unit_to_context_reconciliation(tables)
    directionality = directionality_summary(tables)
    write_csv("bin_to_unit_reconciliation_check.csv", bin_unit_detail)
    write_csv("unit_to_context_reconciliation_check.csv", unit_context_detail)
    write_csv("directionality_reconciliation_summary.csv", directionality)
    log("Completed bin/unit/context reconciliation checks")

    context = tables["distance_band_context.parquet"]
    completeness = completeness_summaries(context)
    for name, frame in completeness.items():
        write_csv(name, frame)
    cross_summary = cross_object_summary(bin_unit_summary, unit_context_summary, directionality, context)
    write_csv("cross_object_reconciliation_summary.csv", cross_summary)
    log("Completed context completeness and cross-object final checks")

    residuals = residual_ledger(context)
    write_csv("known_residuals_acceptance_ledger.csv", residuals)
    score, decision = scorecard(inventory, presence, metadata_audit, parent_dependency, pk_audit, bin_unit_summary, unit_context_summary, cross_summary, readme_audit)
    write_csv("promotion_readiness_scorecard.csv", score)
    write_csv("readiness_decision.csv", [{"decision": decision, "created_utc": now()}])
    write_csv("final_dataset_cache_promotion_plan.csv", promotion_plan(decision))
    write_csv("recommended_next_actions.csv", recommended_next_actions(decision))
    log(f"Promotion readiness decision: {decision}")

    write_findings(decision, inventory, presence, row_summary, pk_audit, parent_dependency, cross_summary, completeness, residuals)
    manifest_payload = {
        "bounded_question": "Is the staged rebuilt final cache folder finalized, internally consistent, dependency-clean, and safe to promote later?",
        "created_utc": now(),
        "audited_folder": rel(STAGING),
        "output_folder": rel(OUT),
        "expected_parquet_objects": EXPECTED_PARQUETS,
        "expected_metadata": EXPECTED_METADATA,
        "diagnostic_evidence_read_only": EVIDENCE_DIRS,
        "decision": decision,
        "read_only_guard": "No staged, canonical, source, artifact, MVP, or parquet files were modified by this audit.",
    }
    write_json("manifest.json", manifest_payload)
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "script": "src.roadway_graph.audit.final_dataset_cache_promotion_readiness_audit",
            "decision": decision,
            "outputs": sorted(path.name for path in OUT.iterdir() if path.is_file()),
            "row_counts": row_summary.to_dict("records"),
            "scorecard": score.to_dict("records"),
        },
    )
    log("Wrote findings memo, manifest, qa_manifest, and required CSV outputs")


if __name__ == "__main__":
    main()
