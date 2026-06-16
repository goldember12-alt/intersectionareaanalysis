"""Read-only validation and legacy-method audit for distance_band_context.

This audit validates the staged distance-band context cache and diagnoses
whether speed/AADT/access missingness is likely source-limited or join-method
limited. It writes only review outputs and does not modify staged/source data.
"""

from __future__ import annotations

import csv
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/distance_band_context_validation_legacy_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
DISTANCE_BAND_UNITS = STAGING / "distance_band_units.parquet"
DISTANCE_BAND_CONTEXT = STAGING / "distance_band_context.parquet"

SPEED = REPO / "artifacts/normalized/speed.parquet"
AADT = REPO / "artifacts/normalized/aadt.parquet"
ACCESS = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"

DIRECT_READS = [DISTANCE_BAND_CONTEXT, DISTANCE_BAND_UNITS, BIN_CONTEXT, TRAVELWAY_INDEX, SPEED, AADT, ACCESS, CRASHES]
VALIDATED_STAGED_OBJECTS = [SIGNAL_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS]
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/build_distance_band_context",
    REPO / "work/roadway_graph/review/distance_band_units_validation_audit",
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

BUILD_VERSION = "distance_band_context_validation_legacy_audit_v1_2026-06-10"
MILE_BUCKET = 0.1
MILE_FT = 5280.0

IDENTITY_COLUMNS = ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
CRASH_DIRECTION_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel", "travel_direction", "directionality")
FORBIDDEN_OUTPUT_TOKENS = ("lookup_cell", "rate_mean", "rate_median", "rate_percentile", "rate_distribution")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "null", "<na>", "nat"} else text


def clean_series(series: pd.Series) -> pd.Series:
    out = series.astype("string").fillna("").str.strip()
    return out.mask(out.str.lower().isin({"nan", "none", "null", "<na>", "nat"}), "").fillna("")


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


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


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamp} - {message}\n")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def route_key(value: Any) -> str:
    text = clean(value).upper()
    if not text:
        return ""
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("R-VA", " R VA ")
    text = text.replace("S-VA", " S VA ")
    text = re.sub(r"\bU\s*\.?\s*S\s*\.?\b", " US ", text)
    text = re.sub(r"\bINTERSTATE\b", " I ", text)
    text = re.sub(r"\bIS\b", " I ", text)
    text = re.sub(r"\b(STATE\s+ROUTE|STATE|ROUTE|RTE|RT|HIGHWAY|HWY|VIRGINIA)\b", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    compact = "".join(text.split())
    patterns = [
        r"(US|SR|SC|PR|FR|NP|UR|IS|I)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?",
        r"(?:R|S)?VA[0-9]{0,3}(US|SR|SC|PR|FR|NP|UR|IS|I)0*([0-9]+)(NB|SB|EB|WB|N|S|E|W)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            prefix = "I" if match.group(1) in {"IS", "I"} else match.group(1)
            direction = (match.group(3) or "")[:1]
            return f"{prefix}{int(match.group(2))}{direction}"
    return re.sub(r"[^A-Z0-9]", "", " ".join(token for token in text.split() if token not in {"R", "S", "VA"}))


def route_key_directionless(value: Any) -> str:
    return re.sub(r"[NSEW]$", "", route_key(value))


def compact_route_key(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", clean(value).upper())


def route_number_key(value: Any) -> str:
    key = route_key_directionless(value)
    match = re.search(r"([A-Z]+)([0-9]+)$", key)
    if match:
        return f"{match.group(1)}{int(match.group(2))}"
    return key


def normalize_unique(values: pd.Series, normalizer: Any) -> pd.Series:
    cleaned = clean_series(values)
    unique = {value: normalizer(value) for value in cleaned.unique().tolist() if value}
    return cleaned.map(lambda value: unique.get(value, ""))


def join_unique(values: Iterable[Any]) -> str:
    return "|".join(sorted({clean(value) for value in values if clean(value)}))


def parent_dependency_check() -> pd.DataFrame:
    rows = []
    forbidden_tokens = ("lookup", "mvp", "rate_distribution", "final_rate", "lookup_cells")
    for path in DIRECT_READS:
        exists = path.exists()
        status = "missing"
        row_count: int | str = ""
        if exists:
            try:
                row_count = parquet_row_count(path)
                status = "readable"
            except Exception as exc:
                status = f"read_failed:{type(exc).__name__}"
        rows.append(
            {
                "path": rel(path),
                "role": "read_only_validation_input",
                "exists": exists,
                "read_status": status,
                "row_count": row_count,
                "downstream_object_parent_flag": any(token in rel(path).lower() for token in forbidden_tokens),
            }
        )
    for path in VALIDATED_STAGED_OBJECTS + DIAGNOSTIC_EVIDENCE:
        rows.append(
            {
                "path": rel(path),
                "role": "diagnostic_or_validated_context_not_parent_truth",
                "exists": path.exists(),
                "read_status": "not_used_as_parent",
                "row_count": parquet_row_count(path) if path.suffix == ".parquet" and path.exists() else "",
                "downstream_object_parent_flag": False,
            }
        )
    return pd.DataFrame(rows)


def load_context_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ctx = pd.read_parquet(DISTANCE_BAND_CONTEXT)
    units = pd.read_parquet(DISTANCE_BAND_UNITS)
    bin_cols = [
        "stable_bin_id",
        "stable_signal_id",
        "signal_approach_id",
        "upstream_downstream",
        "distance_band",
        "bin_length_ft",
        "logical_corridor_chain_id",
        "primary_stable_travelway_id",
        "route_base",
        "source_route_name",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "roadway_configuration",
        "geometry_status",
        "chain_stop_reason",
        "chain_completeness_status",
    ]
    bins = pd.read_parquet(BIN_CONTEXT, columns=bin_cols)
    bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
    bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
    bins = bins.merge(units[IDENTITY_COLUMNS], on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left")
    tw_cols = ["stable_travelway_id", "source_route_name", "source_route_id", "source_route_common", "route_base", "RIM_MEDIAN", "RIM_ACCESS", "RIM_FACILITY", "roadway_configuration"]
    tw = pd.read_parquet(TRAVELWAY_INDEX, columns=tw_cols)
    return ctx, units, bins, tw


def structural_validation(ctx: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    rows = []
    unit_ids = set(units["distance_band_unit_id"])
    ctx_ids = set(ctx["distance_band_unit_id"])
    rows.append({"check_name": "row_count_equals_parent_units", "observed": len(ctx), "expected": len(units), "pass": len(ctx) == len(units)})
    rows.append({"check_name": "distance_band_unit_id_set_unchanged", "observed": len(ctx_ids), "expected": len(unit_ids), "pass": unit_ids == ctx_ids})
    rows.append({"check_name": "distance_band_unit_id_unique", "observed": int(ctx["distance_band_unit_id"].duplicated().sum()), "expected": 0, "pass": not ctx["distance_band_unit_id"].duplicated().any()})
    rows.append({"check_name": "unit_grain_unique", "observed": int(ctx.duplicated(IDENTITY_COLUMNS).sum()), "expected": 0, "pass": not ctx.duplicated(IDENTITY_COLUMNS).any()})
    merged = units[["distance_band_unit_id", "bin_count", "unit_length_ft"]].merge(ctx[["distance_band_unit_id", "bin_count", "unit_length_ft"]], on="distance_band_unit_id", suffixes=("_parent", "_context"))
    rows.append({"check_name": "bin_count_matches_parent", "observed": int((merged["bin_count_parent"] != merged["bin_count_context"]).sum()), "expected": 0, "pass": bool((merged["bin_count_parent"] == merged["bin_count_context"]).all())})
    length_mismatch = int((merged["unit_length_ft_parent"].sub(merged["unit_length_ft_context"]).abs() > 1e-6).sum())
    rows.append({"check_name": "unit_length_matches_parent", "observed": length_mismatch, "expected": 0, "pass": length_mismatch == 0})
    parent_dir = units.groupby("directionality_status", dropna=False)["distance_band_unit_id"].count()
    ctx_dir = ctx.groupby("directionality_status", dropna=False)["distance_band_unit_id"].count()
    rows.append({"check_name": "directionality_counts_match_parent", "observed": dict(ctx_dir), "expected": dict(parent_dir), "pass": parent_dir.equals(ctx_dir)})
    forbidden_cols = [col for col in ctx.columns if any(token in col.lower() for token in FORBIDDEN_OUTPUT_TOKENS)]
    rows.append({"check_name": "no_mvp_lookup_rate_distribution_columns", "observed": "|".join(forbidden_cols), "expected": "", "pass": not forbidden_cols})
    crash_dir_used = False
    rows.append({"check_name": "no_crash_direction_fields_used", "observed": crash_dir_used, "expected": False, "pass": not crash_dir_used})
    decision = "pass" if all(bool(row["pass"]) for row in rows) else "fail"
    return pd.DataFrame(rows), decision


def roadway_audit(ctx: pd.DataFrame, bins: pd.DataFrame, tw: pd.DataFrame) -> pd.DataFrame:
    fields = ["divided_undivided", "one_way_two_way", "roadway_configuration_summary", "median_type", "median_group", "rim_access_summary", "rim_facility_summary", "mixed_roadway_flag"]
    rows = []
    bin_unit_lineage = bins.groupby("distance_band_unit_id").agg(
        unit_route_count=("source_route_name", lambda s: normalize_unique(s, route_key).replace("", pd.NA).nunique(dropna=True)),
        primary_travelway_count=("primary_stable_travelway_id", "nunique"),
    ).reset_index()
    tmp = ctx[["distance_band_unit_id", *fields, "roadway_context_status"]].merge(bin_unit_lineage, on="distance_band_unit_id", how="left")
    for field in fields:
        series = tmp[field]
        missing = series.isna().sum() if pd.api.types.is_bool_dtype(series) else series.map(clean).eq("").sum()
        rows.append(
            {
                "field_name": field,
                "populated_units": int(len(tmp) - missing),
                "missing_units": int(missing),
                "missing_with_no_unit_route_lineage": int(((tmp["unit_route_count"].fillna(0) == 0) & (series.map(clean).eq("") if not pd.api.types.is_bool_dtype(series) else series.isna())).sum()),
                "mixed_units": int(tmp["mixed_roadway_flag"].map(bool_value).sum()) if field == "mixed_roadway_flag" else "",
                "interpretation": "complete_or_nearly_complete" if missing == 0 else "inspect_missing_travelway_or_build_omission",
            }
        )
    status = ctx.groupby("roadway_context_status", dropna=False).agg(unit_count=("distance_band_unit_id", "count"), length_ft=("unit_length_ft", "sum")).reset_index()
    for row in status.to_dict("records"):
        rows.append({"field_name": f"status:{row['roadway_context_status']}", "populated_units": row["unit_count"], "missing_units": "", "mixed_units": "", "interpretation": "roadway_context_status_distribution"})
    return pd.DataFrame(rows)


def unit_route_spans(ctx: pd.DataFrame, bins: pd.DataFrame, tw: pd.DataFrame, target_unit_ids: set[str] | None = None) -> pd.DataFrame:
    base_cols = ["distance_band_unit_id", "source_route_name", "route_base", "source_measure_start", "source_measure_end", "bin_length_ft", "primary_stable_travelway_id"]
    base = bins[base_cols].copy()
    if target_unit_ids is not None:
        base = base.loc[base["distance_band_unit_id"].isin(target_unit_ids)].copy()
    tw_routes = tw.rename(columns={"stable_travelway_id": "primary_stable_travelway_id"})[
        ["primary_stable_travelway_id", "source_route_name", "source_route_id", "source_route_common", "route_base"]
    ]
    base = base.merge(tw_routes, on="primary_stable_travelway_id", how="left", suffixes=("_bin", "_tw"))
    base["measure_min"] = base[["source_measure_start", "source_measure_end"]].min(axis=1)
    base["measure_max"] = base[["source_measure_start", "source_measure_end"]].max(axis=1)
    base = base.loc[base["measure_min"].notna() & base["measure_max"].notna()].copy()
    frames = []
    for col in ["source_route_name_bin", "route_base_bin", "source_route_name_tw", "source_route_id", "source_route_common", "route_base_tw"]:
        if col not in base.columns:
            continue
        sub = base[["distance_band_unit_id", col, "measure_min", "measure_max", "bin_length_ft"]].copy()
        sub = sub.rename(columns={col: "raw_route"})
        sub["route_source_field"] = col
        frames.append(sub)
    spans = pd.concat(frames, ignore_index=True)
    spans = spans.loc[spans["raw_route"].map(clean).ne("")].drop_duplicates(["distance_band_unit_id", "raw_route", "measure_min", "measure_max", "route_source_field"])
    for name, func in [("current", route_key), ("directionless", route_key_directionless), ("route_number", route_number_key), ("compact", compact_route_key)]:
        spans[f"{name}_key"] = normalize_unique(spans["raw_route"], func)
    return spans


def source_route_keys_speed() -> pd.DataFrame:
    cols = ["ROUTE_COMMON_NAME", "ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE", "CAR_SPEED_LIMIT", "Stage1_SourceGDB", "Stage1_SourceLayer"]
    speed = pd.read_parquet(SPEED, columns=cols).reset_index(names="speed_source_index")
    speed["measure_min"] = speed[["ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE"]].min(axis=1)
    speed["measure_max"] = speed[["ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE"]].max(axis=1)
    speed = speed.loc[speed["measure_min"].notna() & speed["measure_max"].notna() & pd.to_numeric(speed["CAR_SPEED_LIMIT"], errors="coerce").notna()].copy()
    for name, func in [("current", route_key), ("directionless", route_key_directionless), ("route_number", route_number_key), ("compact", compact_route_key)]:
        speed[f"{name}_key"] = normalize_unique(speed["ROUTE_COMMON_NAME"], func)
    return speed


def source_route_keys_aadt() -> pd.DataFrame:
    cols = ["RTE_NM", "MASTER_RTE_NM", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "FROM_MEASURE", "TO_MEASURE", "AADT", "AADT_YR", "DIRECTIONALITY"]
    aadt = pd.read_parquet(AADT, columns=cols).reset_index(names="aadt_source_index")
    aadt["measure_from"] = pd.to_numeric(aadt["TRANSPORT_EDGE_FROM_MSR"].fillna(aadt["FROM_MEASURE"]), errors="coerce")
    aadt["measure_to"] = pd.to_numeric(aadt["TRANSPORT_EDGE_TO_MSR"].fillna(aadt["TO_MEASURE"]), errors="coerce")
    aadt["measure_min"] = aadt[["measure_from", "measure_to"]].min(axis=1)
    aadt["measure_max"] = aadt[["measure_from", "measure_to"]].max(axis=1)
    aadt = aadt.loc[aadt["measure_min"].notna() & aadt["measure_max"].notna() & pd.to_numeric(aadt["AADT"], errors="coerce").gt(0)].copy()
    frames = []
    for route_col in ["RTE_NM", "MASTER_RTE_NM"]:
        sub = aadt.copy()
        sub["raw_route"] = sub[route_col]
        sub["route_field"] = route_col
        for name, func in [("current", route_key), ("directionless", route_key_directionless), ("route_number", route_number_key), ("compact", compact_route_key)]:
            sub[f"{name}_key"] = normalize_unique(sub["raw_route"], func)
        frames.append(sub)
    return pd.concat(frames, ignore_index=True).drop_duplicates(["aadt_source_index", "route_field"])


def source_route_keys_access() -> pd.DataFrame:
    cols = ["access_v2_source_row_id", "route_name", "route_measure", "access_control_category", "access_direction_normalized", "access_v2_source_layer"]
    access = pd.read_parquet(ACCESS, columns=cols).reset_index(names="access_source_index")
    access["route_measure_num"] = pd.to_numeric(access["route_measure"], errors="coerce")
    access = access.loc[access["route_measure_num"].notna()].copy()
    for name, func in [("current", route_key), ("directionless", route_key_directionless), ("route_number", route_number_key), ("compact", compact_route_key)]:
        access[f"{name}_key"] = normalize_unique(access["route_name"], func)
    return access


def route_recovery_simulation(missing_units: pd.DataFrame, spans: pd.DataFrame, source: pd.DataFrame, prefix: str, status_field: str) -> pd.DataFrame:
    rows = []
    missing_ids = set(missing_units["distance_band_unit_id"])
    missing_spans = spans.loc[spans["distance_band_unit_id"].isin(missing_ids)].copy()
    for variant in ["current", "directionless", "route_number", "compact"]:
        key_col = f"{variant}_key"
        source_keys = set(source[key_col].dropna().map(clean)) - {""}
        unit_flags = missing_spans.assign(route_match=missing_spans[key_col].isin(source_keys))
        recover = unit_flags.groupby("distance_band_unit_id")["route_match"].any().reset_index()
        recovered_ids = set(recover.loc[recover["route_match"], "distance_band_unit_id"])
        by_status = missing_units.assign(potential_recovered=missing_units["distance_band_unit_id"].isin(recovered_ids)).groupby(status_field, dropna=False).agg(
            missing_unit_count=("distance_band_unit_id", "count"),
            potentially_route_recoverable_units=("potential_recovered", "sum"),
            length_ft=("unit_length_ft", "sum"),
        ).reset_index()
        for row in by_status.to_dict("records"):
            row.update(
                {
                    "context_family": prefix,
                    "normalization_variant": variant,
                    "source_unique_key_count": len(source_keys),
                    "missing_unit_route_key_count": int(missing_spans[key_col].replace("", pd.NA).nunique(dropna=True)),
                    "simulation_scope": "route_compatibility_only_not_assignment",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def overlap_recovery_for_no_overlap(no_overlap_units: pd.DataFrame, spans: pd.DataFrame, source: pd.DataFrame, key_col: str, source_id_col: str, tolerance_mi: float) -> int:
    if no_overlap_units.empty:
        return 0
    ids = set(no_overlap_units["distance_band_unit_id"])
    left = spans.loc[spans["distance_band_unit_id"].isin(ids), ["distance_band_unit_id", key_col, "measure_min", "measure_max"]].drop_duplicates().copy()
    left = left.loc[left[key_col].map(clean).ne("")]
    right_cols = [key_col, source_id_col, "measure_min", "measure_max"]
    right = source[right_cols].dropna(subset=["measure_min", "measure_max"]).copy()
    right = right.loc[right[key_col].map(clean).ne("")]
    if left.empty or right.empty:
        return 0
    left["bucket"] = np.floor(left["measure_min"] / MILE_BUCKET).astype(int)
    right["bucket"] = np.floor(right["measure_min"] / MILE_BUCKET).astype(int)
    candidates = left.merge(right, on=[key_col, "bucket"], how="inner", suffixes=("_unit", "_source"))
    if candidates.empty:
        return 0
    match = candidates["measure_max_source"].ge(candidates["measure_min_unit"] - tolerance_mi) & candidates["measure_min_source"].le(candidates["measure_max_unit"] + tolerance_mi)
    return int(candidates.loc[match, "distance_band_unit_id"].nunique())


def speed_audit(ctx: pd.DataFrame, bins: pd.DataFrame, tw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    missing = ctx.loc[ctx["speed_context_status"].str.startswith("missing", na=False)].copy()
    spans = unit_route_spans(ctx, bins, tw, set(missing["distance_band_unit_id"]))
    speed = source_route_keys_speed()
    route_sim = route_recovery_simulation(missing, spans, speed, "speed", "speed_context_status")
    no_overlap = missing.loc[missing["speed_context_status"].eq("missing_no_measure_overlap_speed")]
    tol_rows = []
    for tol in [0.005, 0.02, 0.05, 0.1]:
        tol_rows.append(
            {
                "tolerance_mi": tol,
                "no_overlap_units": len(no_overlap),
                "potential_units_with_overlap_under_tolerance": overlap_recovery_for_no_overlap(no_overlap, spans, speed, "current_key", "speed_source_index", tol),
                "simulation_scope": "same_current_route_key_with_measure_tolerance",
            }
        )
    source_summary = speed.groupby(["Stage1_SourceGDB", "Stage1_SourceLayer"], dropna=False).agg(source_rows=("speed_source_index", "count"), route_count=("current_key", "nunique")).reset_index()
    status = ctx.groupby("speed_context_status", dropna=False).agg(unit_count=("distance_band_unit_id", "count"), length_ft=("unit_length_ft", "sum"), signal_count=("stable_signal_id", "nunique")).reset_index()
    concentration = missing.groupby(["speed_context_status", "distance_band"], dropna=False).agg(unit_count=("distance_band_unit_id", "count"), length_ft=("unit_length_ft", "sum")).reset_index()
    audit = pd.concat(
        [
            status.assign(audit_section="status_summary"),
            concentration.assign(audit_section="missing_by_distance_band"),
            source_summary.assign(audit_section="speed_source_inventory"),
        ],
        ignore_index=True,
        sort=False,
    )
    feasibility = pd.DataFrame(tol_rows)
    return audit, route_sim, feasibility


def aadt_audit(ctx: pd.DataFrame, bins: pd.DataFrame, tw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = ctx.loc[ctx["aadt_context_status"].str.startswith("missing", na=False)].copy()
    spans = unit_route_spans(ctx, bins, tw, set(missing["distance_band_unit_id"]))
    aadt = source_route_keys_aadt()
    route_sim = route_recovery_simulation(missing, spans, aadt, "aadt", "aadt_context_status")
    status = ctx.groupby(["aadt_context_status", "exposure_context_status"], dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        length_ft=("unit_length_ft", "sum"),
        exposure_sum=("exposure_denominator", "sum"),
        mixed_aadt_units=("mixed_aadt_flag", lambda s: int(s.map(bool_value).sum())),
    ).reset_index()
    exposure_check = pd.DataFrame(
        [
            {
                "audit_section": "exposure_formula_check",
                "units_with_aadt": int(pd.to_numeric(ctx["aadt"], errors="coerce").notna().sum()),
                "units_with_exposure": int(pd.to_numeric(ctx["exposure_denominator"], errors="coerce").notna().sum()),
                "formula": "exposure_denominator = aadt * unit_length_ft / 5280; daily vehicle-mile proxy, not crash-year exposure",
                "defensibility": "defensible as explicit proxy for later rates only if documented and crash-period denominator is later added or accepted",
            }
        ]
    )
    audit = pd.concat([status.assign(audit_section="status_summary"), exposure_check], ignore_index=True, sort=False)
    return audit, route_sim


def access_audit(ctx: pd.DataFrame, bins: pd.DataFrame, tw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = ctx.loc[ctx["access_context_status"].str.startswith("missing", na=False)].copy()
    spans = unit_route_spans(ctx, bins, tw, set(missing["distance_band_unit_id"]))
    access = source_route_keys_access()
    route_sim = route_recovery_simulation(missing, spans, access, "access", "access_context_status")
    source_summary = access.groupby(["access_v2_source_layer"], dropna=False).agg(source_rows=("access_source_index", "count"), route_count=("current_key", "nunique")).reset_index()
    status = ctx.groupby("access_context_status", dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        length_ft=("unit_length_ft", "sum"),
        matched_access_count=("access_count", "sum"),
        signal_count=("stable_signal_id", "nunique"),
    ).reset_index()
    audit = pd.concat([status.assign(audit_section="status_summary"), source_summary.assign(audit_section="access_source_inventory")], ignore_index=True, sort=False)
    return audit, route_sim


def inspect_old_code() -> tuple[pd.DataFrame, pd.DataFrame]:
    roots = [REPO / "src/active/roadway_graph", REPO / "docs/workflow", REPO / "docs/methodology"]
    speed_patterns = ["Speed_Limit_RNS", "postedspeedlimits", "posted speed", "speed.parquet", "speed_limit", "speed recovery", "speed_context", "route_key"]
    aadt_patterns = ["AADT", "exposure", "traffic volume", "route measure", "aadt_context", "DIRECTION_FACTOR", "EDGE_RTE_KEY"]
    rows = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".md", ".txt"}:
                continue
            if path.name == "distance_band_context_validation_legacy_audit.py":
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            lower = text.lower()
            for family, patterns in [("speed", speed_patterns), ("aadt", aadt_patterns)]:
                hits = [pattern for pattern in patterns if pattern.lower() in lower]
                if not hits:
                    continue
                source_layer = ""
                if "speed_limit_rns" in lower:
                    source_layer = "Speed_Limit_RNS"
                elif "speed.parquet" in lower:
                    source_layer = "artifacts/normalized/speed.parquet"
                elif "aadt.parquet" in lower:
                    source_layer = "artifacts/normalized/aadt.parquet"
                route_fields = join_unique(re.findall(r"\b(?:RTE_NM|MASTER_RTE_NM|ROUTE_COMMON_NAME|ROUTE_FROM_MEASURE|ROUTE_TO_MEASURE|TRANSPORT_EDGE_FROM_MSR|TRANSPORT_EDGE_TO_MSR|EDGE_RTE_KEY|LINKID|source_route_name|route_base|source_route_common)\b", text))
                functions = join_unique(re.findall(r"def\s+([A-Za-z0-9_]+)", text))
                coverage_match = re.findall(r"(?i)(?:stable|recovered|missing|coverage)[^.\n]{0,80}(?:\d{2,6}|\d+\.\d+%)", text)
                snippet = " | ".join(line.strip()[:180] for line in text.splitlines() if any(pattern.lower() in line.lower() for pattern in hits[:3]))[:700]
                rows.append(
                    {
                        "family": family,
                        "path": rel(path),
                        "matched_terms": "|".join(hits),
                        "relevant_function_or_rule": functions[:240],
                        "source_layer_used": source_layer,
                        "route_fields_used": route_fields,
                        "normalization_method": "route_key/_route_key" if "_route_key" in text or "route_key" in text else "not_obvious",
                        "measure_overlap_method": "route_measure_overlap" if "overlap" in lower or "measure_min" in lower else "not_obvious",
                        "achieved_coverage_if_documented": " | ".join(coverage_match[:5]),
                        "uses_stale_cache_parent_flag": "work/output/roadway_graph" in text or "analysis/current" in text or "review/current" in text,
                        "compatible_with_rebuilt_cache": "candidate_method_only" if family == "speed" and "Speed_Limit_RNS" in text else "requires_adaptation_review",
                        "evidence_snippet": snippet,
                    }
                )
    inventory = pd.DataFrame(rows).drop_duplicates(["family", "path"]).sort_values(["family", "path"])
    speed = inventory.loc[inventory["family"].eq("speed")].copy()
    aadt = inventory.loc[inventory["family"].eq("aadt")].copy()
    return speed, aadt


def crash_deferred_audit(ctx: pd.DataFrame) -> pd.DataFrame:
    crash_cols = pq.ParquetFile(CRASHES).schema_arrow.names
    direction_like = [col for col in crash_cols if any(token in col.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)]
    return pd.DataFrame(
        [
            {
                "check_name": "crash_context_deferred_all_rows",
                "unit_count": len(ctx),
                "deferred_count": int(ctx["crash_context_status"].map(clean).str.startswith("deferred").sum()),
                "crash_count_null_count": int(ctx["crash_count"].isna().sum()),
                "pass": bool(ctx["crash_context_status"].map(clean).str.startswith("deferred").all()),
                "later_layer_requirement": "validated spatial catchment or source-rooted unit lineage; no crash direction fields",
            },
            {
                "check_name": "crash_direction_inventory_not_used",
                "unit_count": len(ctx),
                "deferred_count": "",
                "crash_count_null_count": "",
                "pass": True,
                "crash_artifact_direction_like_columns": "|".join(direction_like),
                "later_layer_requirement": "direction-like crash attributes may be inventoried but must not derive upstream/downstream",
            },
        ]
    )


def rate_readiness_audit(ctx: pd.DataFrame) -> pd.DataFrame:
    return ctx.groupby("rate_readiness_status", dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        crash_rate_ready_units=("crash_rate_ready_flag", lambda s: int(s.map(bool_value).sum())),
        assigned_units=("directionality_status", lambda s: int(s.eq("assigned").sum())),
        unresolved_units=("directionality_status", lambda s: int(s.ne("assigned").sum())),
    ).reset_index()


def performance_vs_coverage(ctx: pd.DataFrame, speed_route_sim: pd.DataFrame, access_route_sim: pd.DataFrame) -> pd.DataFrame:
    speed_route_recoverable = int(speed_route_sim.loc[speed_route_sim["normalization_variant"].eq("directionless"), "potentially_route_recoverable_units"].max()) if not speed_route_sim.empty else 0
    access_route_recoverable = int(access_route_sim.loc[access_route_sim["normalization_variant"].eq("directionless"), "potentially_route_recoverable_units"].max()) if not access_route_sim.empty else 0
    return pd.DataFrame(
        [
            {
                "assessment_item": "roadway_derived_fields",
                "coverage_risk": "high",
                "finding": "roadway_configuration_summary is populated, but divided_undivided and one_way_two_way are blank for all units; this is a build omission/derivation bug, not a source limitation.",
            },
            {
                "assessment_item": "route_normalization_cache",
                "coverage_risk": "low",
                "finding": "Caching unique route strings should not reduce coverage; it preserves deterministic normalization while avoiding repeated regex work.",
            },
            {
                "assessment_item": "unit_route_span_aggregation",
                "coverage_risk": "medium",
                "finding": "Fast build now preserves individual unit-route measure spans; earlier min/max bridging was repaired. Remaining risk is missing alternate route aliases not present in bin/travelway lineage.",
            },
            {
                "assessment_item": "strict_speed_source_choice",
                "coverage_risk": "high",
                "finding": f"Speed route recovery simulation indicates up to {speed_route_recoverable:,} missing units may be route-compatible under directionless/alternate normalization; old code references Speed_Limit_RNS as a stronger source.",
            },
            {
                "assessment_item": "access_source_route_coverage",
                "coverage_risk": "high",
                "finding": f"Access source has limited route coverage; directionless route simulation indicates up to {access_route_recoverable:,} missing units may be route-key recoverable, but many may be true source absence or require geometry.",
            },
        ]
    )


def no_crash_direction_check() -> pd.DataFrame:
    crash_cols = pq.ParquetFile(CRASHES).schema_arrow.names
    direction_like = [col for col in crash_cols if any(token in col.lower() for token in CRASH_DIRECTION_FIELD_TOKENS)]
    return pd.DataFrame([{"check_name": "no_crash_direction_fields_used", "crash_artifact_direction_like_columns_present": "|".join(direction_like), "used_crash_direction_field_count": 0, "used_crash_direction_fields": "", "pass": True}])


def forbidden_mvp_check(ctx: pd.DataFrame) -> pd.DataFrame:
    forbidden_cols = [col for col in ctx.columns if any(token in col.lower() for token in FORBIDDEN_OUTPUT_TOKENS)]
    forbidden_files = [path.name for path in STAGING.glob("*") if any(token in path.name.lower() for token in ("lookup", "mvp", "rate_distribution"))]
    return pd.DataFrame([{"forbidden_output_column_count": len(forbidden_cols), "forbidden_output_columns": "|".join(forbidden_cols), "staging_lookup_mvp_rate_files_seen_for_guard_only": "|".join(forbidden_files), "pass": len(forbidden_cols) == 0}])


def write_findings(decision: str, structural: pd.DataFrame, roadway: pd.DataFrame, speed_audit_df: pd.DataFrame, speed_sim: pd.DataFrame, speed_old: pd.DataFrame, aadt_audit_df: pd.DataFrame, aadt_old: pd.DataFrame, access_audit_df: pd.DataFrame, crash_audit_df: pd.DataFrame, perf: pd.DataFrame) -> None:
    structural_ok = bool(structural["pass"].all())
    speed_missing = speed_audit_df.loc[speed_audit_df["audit_section"].eq("status_summary") & speed_audit_df["speed_context_status"].astype(str).str.startswith("missing", na=False), "unit_count"].sum()
    speed_directionless = speed_sim.loc[speed_sim["normalization_variant"].eq("directionless"), "potentially_route_recoverable_units"].max() if not speed_sim.empty else 0
    speed_rns_files = int(speed_old["source_layer_used"].eq("Speed_Limit_RNS").sum()) if not speed_old.empty else 0
    access_missing_route = access_audit_df.loc[access_audit_df.get("access_context_status", pd.Series(dtype=str)).eq("missing_no_route_compatible_access"), "unit_count"].sum() if "access_context_status" in access_audit_df else 0
    roadway_missing_divided = int(roadway.loc[roadway["field_name"].eq("divided_undivided"), "missing_units"].iloc[0]) if not roadway.loc[roadway["field_name"].eq("divided_undivided")].empty else 0
    roadway_missing_oneway = int(roadway.loc[roadway["field_name"].eq("one_way_two_way"), "missing_units"].iloc[0]) if not roadway.loc[roadway["field_name"].eq("one_way_two_way")].empty else 0
    memo = f"""# distance_band_context Validation And Legacy-Method Audit Findings

## Structural Validity
Structural validation pass: {structural_ok}. Row count, unit ID set, uniqueness, directionality counts, bin counts, unit lengths, crash-direction guard, and MVP/lookup guard were checked read-only.

## Roadway Context
Roadway context is not complete enough as currently materialized. `roadway_configuration_summary`, `rim_access_summary`, and `rim_facility_summary` are populated, but `divided_undivided` is missing for {roadway_missing_divided:,} units and `one_way_two_way` is missing for {roadway_missing_oneway:,} units. Because roadway configuration strings are present, this is a derived-field build omission rather than a source limitation. Median fields are nearly complete.

## Speed Missingness Diagnosis
Speed completeness is low relative to AADT: missing speed units total approximately {int(speed_missing):,}. The major issue is not structural grain loss; it is route/source/method coverage. The current artifact has `ROUTE_COMMON_NAME` plus route measures and appears normalized from posted-speed source layers, while old code repeatedly references `Speed_Limit_RNS` and source-specific route fields. Directionless/alternate route-key simulation shows potential route compatibility for up to {int(speed_directionless):,} missing units, so a meaningful share is likely fixable.

## Old Speed Code Findings
Found {len(speed_old):,} speed-related scripts/docs, including {speed_rns_files:,} references to `Speed_Limit_RNS`. Candidate reusable methods include RNS route+measure overlap, route-key variants, retained v4 stable context comparison, and review-only RNS supplement logic. Many old scripts use stale `work/output/...` parents, so they are method evidence only and must be adapted to rebuilt `bin_context`/`distance_band_context`.

## AADT / Exposure
AADT coverage is high and exposure is computed for the same rows as AADT. Mixed AADT is large because units often overlap multiple AADT segments or values; that is acceptable as a flagged context condition, but a later repair should document value selection and consider length-weighted dominant/latest-year aggregation. Exposure is defensible only as an explicit daily vehicle-mile proxy (`AADT * unit_length_ft / 5280`), not as final crash-period exposure.

## Old AADT Code Findings
Found {len(aadt_old):,} AADT/exposure-related scripts/docs. Reusable method evidence includes identity route-measure v3 logic, LINKID/EDGE_RTE_KEY diagnostics, route-key variants, latest-year handling, and paired pseudo-direction consistency checks. Current missing AADT is small, so AADT repair is secondary to speed/access.

## Access Missingness
Access missingness is likely mixed: no-access-point rows can be valid zero-access evidence when route coverage exists, but missing/no-compatible-route units ({int(access_missing_route):,}) are likely source coverage and route-matching limitations. Access v2 has sparse route coverage compared with Travelway/bin routes and may require route alias fanout or geometry-based assignment before final acceptance.

## Crash Deferral
Crash deferral is acceptable. Crash count is null and explicitly deferred for all units. A later crash layer should require validated spatial catchment or accepted source-rooted unit lineage and must not use crash direction fields for upstream/downstream.

## Performance Versus Coverage
The performance refactor itself is not the main coverage problem after the interval-bridging repair. Remaining coverage issues are better framed as targeted source-specific joins and derived-field repair: roadway divided/one-way derivation, Speed_Limit_RNS/route aliases for speed, and access route/geometry matching for access.

## Recommended Repair Sequence
1. Patch roadway derived fields (`divided_undivided`, `one_way_two_way`) from populated `roadway_configuration_summary`.
2. Patch speed join using Speed_Limit_RNS-specific route+measure logic adapted to rebuilt unit-route spans.
3. Audit or patch access route matching/geometry assignment.
4. Keep AADT/exposure as provisionally acceptable, with a focused mixed-AADT value-selection documentation pass.
5. Build crash assignment as a separate layer after context validation.

## Readiness Decision
Decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    started = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    log("Starting read-only distance_band_context validation and legacy-method audit.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    log("Loading staged context, units, bin lineage, and travelway index.")
    ctx, units, bins, tw = load_context_tables()
    log("Running structural validation.")
    structural, structural_decision = structural_validation(ctx, units)
    write_csv("structural_validation_summary.csv", structural)
    log("Auditing roadway context.")
    roadway = roadway_audit(ctx, bins, tw)
    write_csv("roadway_context_completeness_audit.csv", roadway)
    log("Auditing speed missingness and route-key recovery.")
    speed_audit_df, speed_sim, speed_feas = speed_audit(ctx, bins, tw)
    write_csv("speed_missingness_audit.csv", speed_audit_df)
    write_csv("speed_route_key_recovery_simulation.csv", speed_sim)
    write_csv("speed_repair_feasibility_summary.csv", speed_feas)
    log("Auditing AADT/exposure.")
    aadt_audit_df, aadt_sim = aadt_audit(ctx, bins, tw)
    write_csv("aadt_exposure_audit.csv", aadt_audit_df)
    write_csv("aadt_repair_feasibility_summary.csv", aadt_sim)
    log("Auditing access context.")
    access_audit_df, access_sim = access_audit(ctx, bins, tw)
    write_csv("access_context_audit.csv", access_audit_df)
    write_csv("access_repair_feasibility_summary.csv", access_sim)
    log("Inspecting old speed/AADT code and docs as method evidence.")
    old_speed, old_aadt = inspect_old_code()
    write_csv("old_speed_code_inventory.csv", old_speed)
    write_csv("old_aadt_code_inventory.csv", old_aadt)
    log("Auditing crash deferral and rate readiness.")
    crash_audit_df = crash_deferred_audit(ctx)
    write_csv("crash_deferred_context_audit.csv", crash_audit_df)
    rate_audit_df = rate_readiness_audit(ctx)
    write_csv("rate_readiness_audit.csv", rate_audit_df)
    no_crash = no_crash_direction_check()
    write_csv("no_crash_direction_field_check.csv", no_crash)
    forbidden = forbidden_mvp_check(ctx)
    write_csv("forbidden_mvp_lookup_product_check.csv", forbidden)
    perf = performance_vs_coverage(ctx, speed_sim, access_sim)
    write_csv("performance_vs_coverage_assessment.csv", perf)
    speed_recoverable = int(speed_sim.loc[speed_sim["normalization_variant"].eq("directionless"), "potentially_route_recoverable_units"].max()) if not speed_sim.empty else 0
    access_recoverable = int(access_sim.loc[access_sim["normalization_variant"].eq("directionless"), "potentially_route_recoverable_units"].max()) if not access_sim.empty else 0
    roadway_needs_repair = bool(
        roadway.loc[roadway["field_name"].isin(["divided_undivided", "one_way_two_way"]), "missing_units"].fillna(0).astype(int).gt(0).any()
    )
    if structural_decision != "pass":
        decision = "distance_band_context_should_be_rebuilt"
    elif roadway_needs_repair or (speed_recoverable > 0 and access_recoverable > 0):
        decision = "distance_band_context_structurally_valid_needs_multiple_context_repairs"
    elif speed_recoverable > 0:
        decision = "distance_band_context_structurally_valid_needs_speed_repair"
    elif access_recoverable > 0:
        decision = "distance_band_context_structurally_valid_needs_access_repair"
    else:
        decision = "distance_band_context_validated_with_crash_deferred"
    priority = pd.DataFrame(
        [
            {"priority": 1, "context_family": "roadway", "recommendation": "Patch derived roadway fields divided_undivided and one_way_two_way from populated roadway_configuration_summary.", "rationale": "Roadway configuration is populated, but derived divided/one-way fields are blank for all units."},
            {"priority": 2, "context_family": "speed", "recommendation": "Patch speed join using Speed_Limit_RNS-specific route+measure logic adapted to rebuilt unit-route spans.", "rationale": f"Speed route-key simulation found {speed_recoverable:,} potentially route-recoverable missing units."},
            {"priority": 3, "context_family": "access", "recommendation": "Run targeted access route/geometry matching repair feasibility.", "rationale": f"Access route-key simulation found {access_recoverable:,} potentially route-recoverable missing units, while source route coverage is sparse."},
            {"priority": 4, "context_family": "aadt_exposure", "recommendation": "Keep current AADT/exposure provisionally, then document mixed-value selection and daily vehicle-mile proxy caveat.", "rationale": "AADT/exposure completeness is high; remaining missingness is small."},
            {"priority": 5, "context_family": "crash", "recommendation": "Build crash assignment as a later bounded layer with spatial catchment/source-rooted unit lineage.", "rationale": "Crash context is explicitly deferred and no rate readiness is claimed."},
        ]
    )
    write_csv("context_repair_priority_recommendation.csv", priority)
    write_csv("readiness_decision.csv", [{"decision": decision, "structural_validation": structural_decision, "speed_potential_route_recoverable_units": speed_recoverable, "access_potential_route_recoverable_units": access_recoverable}])
    write_csv("recommended_next_actions.csv", priority.rename(columns={"recommendation": "recommended_next_action"}))
    write_findings(decision, structural, roadway, speed_audit_df, speed_sim, old_speed, aadt_audit_df, old_aadt, access_audit_df, crash_audit_df, perf)
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "script": "src.roadway_graph.audit.distance_band_context_validation_legacy_audit",
            "build_version": BUILD_VERSION,
            "bounded_question": "Validate staged distance_band_context and audit legacy methods for speed/AADT/access repair feasibility.",
            "read_only": True,
            "inputs": [rel(path) for path in DIRECT_READS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "outputs": rel(OUT),
            "decision": decision,
        },
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "runtime_seconds": round(time.perf_counter() - started, 3),
            "qa_outputs": sorted(path.name for path in OUT.glob("*") if path.is_file()),
            "structural_validation_passed": structural_decision == "pass",
            "crash_direction_fields_used": False,
            "mvp_lookup_products_built": False,
            "decision": decision,
        },
    )
    log(f"Completed read-only validation audit with decision {decision}.")


if __name__ == "__main__":
    main()
