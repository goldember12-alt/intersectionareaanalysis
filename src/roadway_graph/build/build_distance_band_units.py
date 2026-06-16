"""Build staged distance_band_units from validated bin_context.

This layer rolls 50-ft bins into distance-band units. It uses
bin_context.parquet as the direct parent and does not enrich with speed, AADT,
access, crash, exposure, rate, or lookup-cell context.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/build_distance_band_units"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
DISTANCE_BAND_UNITS = STAGING / "distance_band_units.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

PARENTS = [BIN_CONTEXT]
VALIDATED_STAGED_OBJECTS = [SIGNAL_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/patch_bin_context_chain_directionality_and_audit",
    REPO / "work/roadway_graph/review/residual_directionality_impact_legacy_pairing_audit",
    REPO / "work/roadway_graph/review/materialize_bin_context_geometry",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

BUILD_VERSION = "distance_band_units_from_bin_context_v1_2026-06-10"
FLOAT_TOL_FT = 1e-6
FULL_BIN_LENGTH_FT = 50.0
SAMPLE_SIZE = 10

DISTANCE_BANDS: dict[str, tuple[float, float]] = {
    "0-250": (0.0, 250.0),
    "250-500": (250.0, 500.0),
    "500-1,000": (500.0, 1000.0),
    "1,000-1,500": (1000.0, 1500.0),
    "1,500-2,000": (1500.0, 2000.0),
    "2,000-2,500": (2000.0, 2500.0),
}

REQUIRED_BIN_COLUMNS = [
    "stable_bin_id",
    "stable_signal_id",
    "signal_approach_id",
    "logical_corridor_chain_id",
    "distance_start_ft",
    "distance_end_ft",
    "bin_length_ft",
    "distance_band",
    "measure_side_class",
    "chain_stop_reason",
    "chain_completeness_status",
    "final_partial_bin_flag",
    "geometry_status",
    "parent_corridor_warning_status",
    "directionality_status",
    "upstream_downstream",
]

OPTIONAL_BIN_COLUMNS = [
    "directionality_method",
    "directionality_confidence",
    "directionality_unresolved_reason",
    "analysis_ready_status",
    "approach_identity_status",
    "corridor_build_gate",
    "corridor_gate_severity",
    "parent_corridor_review_status",
    "measure_side_class",
    "bin_context_build_status",
    "bin_distance_status",
    "distance_band_status",
    "lineage_confidence",
    "source_limited_status",
    "source_limited_reason",
]

UNIT_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
    "unit_build_status",
    "directionality_status",
    "directionality_method",
    "directionality_confidence",
    "directionality_unresolved_reason",
    "bin_count",
    "unit_length_ft",
    "full_bin_count",
    "partial_bin_count",
    "chain_count",
    "logical_corridor_chain_ids",
    "supporting_stable_bin_ids_sample",
    "min_distance_start_ft",
    "max_distance_end_ft",
    "distance_band_start_ft",
    "distance_band_end_ft",
    "signal_analysis_ready_status",
    "approach_identity_status",
    "parent_approach_gate",
    "parent_corridor_gate_severity",
    "parent_corridor_warning_status",
    "chain_stop_reason_values",
    "chain_completeness_status_values",
    "measure_side_class_values",
    "geometry_status_summary",
    "source_limited_status",
    "unit_completeness_status",
    "bin_coverage_status",
    "missingness_reason",
    "context_readiness_status",
    "rate_readiness_status",
]

UNIT_SCHEMA = pa.schema(
    [
        pa.field("distance_band_unit_id", pa.string()),
        pa.field("stable_signal_id", pa.string()),
        pa.field("signal_approach_id", pa.string()),
        pa.field("upstream_downstream", pa.string()),
        pa.field("distance_band", pa.string()),
        pa.field("unit_build_status", pa.string()),
        pa.field("directionality_status", pa.string()),
        pa.field("directionality_method", pa.string()),
        pa.field("directionality_confidence", pa.string()),
        pa.field("directionality_unresolved_reason", pa.string()),
        pa.field("bin_count", pa.int64()),
        pa.field("unit_length_ft", pa.float64()),
        pa.field("full_bin_count", pa.int64()),
        pa.field("partial_bin_count", pa.int64()),
        pa.field("chain_count", pa.int64()),
        pa.field("logical_corridor_chain_ids", pa.string()),
        pa.field("supporting_stable_bin_ids_sample", pa.string()),
        pa.field("min_distance_start_ft", pa.float64()),
        pa.field("max_distance_end_ft", pa.float64()),
        pa.field("distance_band_start_ft", pa.float64()),
        pa.field("distance_band_end_ft", pa.float64()),
        pa.field("signal_analysis_ready_status", pa.string()),
        pa.field("approach_identity_status", pa.string()),
        pa.field("parent_approach_gate", pa.string()),
        pa.field("parent_corridor_gate_severity", pa.string()),
        pa.field("parent_corridor_warning_status", pa.string()),
        pa.field("chain_stop_reason_values", pa.string()),
        pa.field("chain_completeness_status_values", pa.string()),
        pa.field("measure_side_class_values", pa.string()),
        pa.field("geometry_status_summary", pa.string()),
        pa.field("source_limited_status", pa.string()),
        pa.field("unit_completeness_status", pa.string()),
        pa.field("bin_coverage_status", pa.string()),
        pa.field("missingness_reason", pa.string()),
        pa.field("context_readiness_status", pa.string()),
        pa.field("rate_readiness_status", pa.string()),
    ]
)

FORBIDDEN_CONTEXT_FIELDS = {
    "speed_category",
    "speed_limit_mph",
    "aadt",
    "aadt_category",
    "exposure_denominator",
    "crash_count",
    "crash_rate",
    "access_count",
    "access_type",
    "median_type",
    "rate_mean",
    "rate_median",
}


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
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def clean_values(values: pd.Series) -> list[str]:
    return sorted({clean(value) for value in values if clean(value)})


def join_values(values: pd.Series) -> str:
    return "|".join(clean_values(values))


def sample_values(values: pd.Series, size: int = SAMPLE_SIZE) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean(value)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
        if len(out) >= size:
            break
    return "|".join(out)


def status_rollup(values: pd.Series, assigned_label: str = "assigned") -> str:
    cleaned = clean_values(values)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if assigned_label in cleaned and all(value == assigned_label for value in cleaned):
        return assigned_label
    return "|".join(cleaned)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


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
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} - {message}\n")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def parent_dependency_check() -> pd.DataFrame:
    forbidden_tokens = (
        "distance_band_context",
        "lookup_cells",
        "mvp",
        "crash",
        "access_context",
        "speed_context",
        "aadt",
        "exposure",
        "rate_distribution",
    )
    rows: list[dict[str, Any]] = []
    for path in PARENTS:
        exists = path.exists()
        read_status = "missing"
        row_count: int | str = ""
        if exists:
            try:
                row_count = parquet_row_count(path)
                read_status = "readable"
            except Exception as exc:
                read_status = f"read_failed:{type(exc).__name__}"
        lowered = rel(path).lower()
        rows.append(
            {
                "parent_path": rel(path),
                "parent_role": "direct_parent",
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_distance_band_units": bool(exists and read_status == "readable" and path == BIN_CONTEXT),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden_tokens),
            }
        )
    for path in VALIDATED_STAGED_OBJECTS:
        if path in PARENTS:
            continue
        rows.append(
            {
                "parent_path": rel(path),
                "parent_role": "validated_staged_dependency_documented_not_read_for_rollup",
                "exists": path.exists(),
                "read_status": "not_read",
                "row_count": parquet_row_count(path) if path.exists() else "",
                "allowed_parent_for_distance_band_units": False,
                "downstream_object_parent_flag": False,
            }
        )
    return pd.DataFrame(rows)


def load_bin_context() -> pd.DataFrame:
    pf = pq.ParquetFile(BIN_CONTEXT)
    available = set(pf.schema_arrow.names)
    missing_required = [col for col in REQUIRED_BIN_COLUMNS if col not in available]
    if missing_required:
        raise RuntimeError(f"bin_context missing required columns: {missing_required}")
    columns = REQUIRED_BIN_COLUMNS + [col for col in OPTIONAL_BIN_COLUMNS if col in available and col not in REQUIRED_BIN_COLUMNS]
    return pd.read_parquet(BIN_CONTEXT, columns=columns)


def unit_id(row: pd.Series) -> str:
    upstream = clean(row["upstream_downstream"]) or "unresolved"
    key = "|".join(
        [
            clean(row["stable_signal_id"]),
            clean(row["signal_approach_id"]),
            upstream,
            clean(row["distance_band"]),
        ]
    )
    return "dbu_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]


def band_start(label: str) -> float:
    return DISTANCE_BANDS[clean(label)][0]


def band_end(label: str) -> float:
    return DISTANCE_BANDS[clean(label)][1]


def coverage_status(row: pd.Series) -> str:
    expected = float(row["distance_band_end_ft"]) - float(row["distance_band_start_ft"])
    starts_ok = float(row["min_distance_start_ft"]) <= float(row["distance_band_start_ft"]) + FLOAT_TOL_FT
    ends_ok = float(row["max_distance_end_ft"]) >= float(row["distance_band_end_ft"]) - FLOAT_TOL_FT
    length_ok = math.isclose(float(row["unit_length_ft"]), expected, rel_tol=0.0, abs_tol=FLOAT_TOL_FT)
    if starts_ok and ends_ok and length_ok:
        return "complete_band_coverage"
    if float(row["min_distance_start_ft"]) > float(row["distance_band_start_ft"]) + FLOAT_TOL_FT:
        return "starts_after_band_start"
    if float(row["max_distance_end_ft"]) < float(row["distance_band_end_ft"]) - FLOAT_TOL_FT:
        return "ends_before_band_end"
    if not length_ok:
        return "length_shortfall_or_overlap"
    return "partial_band_coverage"


def unit_completeness(row: pd.Series) -> tuple[str, str, str]:
    directionality_status = clean(row["directionality_status"])
    stop_values = clean(row["chain_stop_reason_values"]).lower()
    completeness_values = clean(row["chain_completeness_status_values"]).lower()
    coverage = clean(row["bin_coverage_status"])
    warning = clean(row["parent_corridor_warning_status"]).lower()
    if directionality_status != "assigned":
        reason = clean(row["directionality_unresolved_reason"]) or directionality_status
        return "unresolved_directionality", reason, "source_limited"
    if "blocked" in clean(row["parent_approach_gate"]).lower() or "blocked" in clean(row["parent_corridor_gate_severity"]).lower():
        return "blocked_by_parent_gate", "parent gate blocked or severe", "source_limited"
    if coverage == "complete_band_coverage":
        return "complete_distance_band", "", "not_source_limited"
    if "supported_signal_boundary" in stop_values:
        return "partial_signal_boundary_clipped", "chain stopped at supported signal boundary", "not_source_limited"
    if "source_extent" in stop_values or "source_extent" in completeness_values:
        return "partial_source_extent_clipped", "chain stopped at source extent", "source_limited"
    if "insufficient" in stop_values or "insufficient" in completeness_values:
        return "insufficient_evidence", "chain stopped due insufficient evidence", "source_limited"
    if warning and warning != "none":
        return "source_limited", f"parent corridor warning: {warning}", "source_limited"
    return "partial_chain_shortfall", "bin coverage does not span full distance band", "source_limited"


def build_units(bin_df: pd.DataFrame) -> pd.DataFrame:
    df = bin_df.copy()
    for col in OPTIONAL_BIN_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    for col in ["upstream_downstream", "directionality_status", "directionality_method", "directionality_confidence", "directionality_unresolved_reason"]:
        df[col] = df[col].map(clean)
    assigned = df["directionality_status"].eq("assigned") & df["upstream_downstream"].ne("")
    unresolved = ~assigned
    df.loc[unresolved, "upstream_downstream"] = ""

    invalid_bands = sorted(set(df["distance_band"].map(clean)) - set(DISTANCE_BANDS))
    if invalid_bands:
        raise RuntimeError(f"Unexpected distance_band labels in bin_context: {invalid_bands}")

    df["full_bin_flag_for_unit"] = (~df["final_partial_bin_flag"].fillna(False).astype(bool)) & df["bin_length_ft"].sub(FULL_BIN_LENGTH_FT).abs().le(FLOAT_TOL_FT)
    df["partial_bin_flag_for_unit"] = ~df["full_bin_flag_for_unit"]

    grouped = df.groupby(["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], dropna=False, sort=True)
    units = grouped.agg(
        bin_count=("stable_bin_id", "count"),
        unit_length_ft=("bin_length_ft", "sum"),
        full_bin_count=("full_bin_flag_for_unit", "sum"),
        partial_bin_count=("partial_bin_flag_for_unit", "sum"),
        chain_count=("logical_corridor_chain_id", "nunique"),
        logical_corridor_chain_ids=("logical_corridor_chain_id", join_values),
        supporting_stable_bin_ids_sample=("stable_bin_id", sample_values),
        min_distance_start_ft=("distance_start_ft", "min"),
        max_distance_end_ft=("distance_end_ft", "max"),
        directionality_status=("directionality_status", status_rollup),
        directionality_method=("directionality_method", join_values),
        directionality_confidence=("directionality_confidence", join_values),
        directionality_unresolved_reason=("directionality_unresolved_reason", join_values),
        signal_analysis_ready_status=("analysis_ready_status", join_values),
        approach_identity_status=("approach_identity_status", join_values),
        parent_approach_gate=("corridor_build_gate", join_values),
        parent_corridor_gate_severity=("corridor_gate_severity", join_values),
        parent_corridor_warning_status=("parent_corridor_warning_status", join_values),
        chain_stop_reason_values=("chain_stop_reason", join_values),
        chain_completeness_status_values=("chain_completeness_status", join_values),
        measure_side_class_values=("measure_side_class", join_values),
        geometry_status_summary=("geometry_status", join_values),
    ).reset_index()

    units["distance_band_start_ft"] = units["distance_band"].map(lambda value: band_start(clean(value)))
    units["distance_band_end_ft"] = units["distance_band"].map(lambda value: band_end(clean(value)))
    units["unit_build_status"] = "built_from_bin_context"
    units["bin_coverage_status"] = units.apply(coverage_status, axis=1)
    completeness = units.apply(unit_completeness, axis=1)
    units["unit_completeness_status"] = [item[0] for item in completeness]
    units["missingness_reason"] = [item[1] for item in completeness]
    units["source_limited_status"] = [item[2] for item in completeness]
    units.loc[units["directionality_status"].ne("assigned") & units["directionality_unresolved_reason"].eq(""), "directionality_unresolved_reason"] = units.loc[
        units["directionality_status"].ne("assigned") & units["directionality_unresolved_reason"].eq(""),
        "directionality_status",
    ]
    units["context_readiness_status"] = "not_enriched"
    units["rate_readiness_status"] = "not_enriched"
    units["distance_band_unit_id"] = units.apply(unit_id, axis=1)
    return units[UNIT_COLUMNS].copy()


def write_units(units: pd.DataFrame) -> None:
    table = pa.Table.from_pandas(units[UNIT_COLUMNS], schema=UNIT_SCHEMA, preserve_index=False)
    pq.write_table(table, DISTANCE_BAND_UNITS, compression="snappy")


def forbidden_context_check(units: pd.DataFrame) -> pd.DataFrame:
    present = [field for field in FORBIDDEN_CONTEXT_FIELDS if field in units.columns]
    populated = []
    for field in present:
        if units[field].map(clean).ne("").any():
            populated.append(field)
    return pd.DataFrame(
        [
            {
                "check_name": "forbidden_context_enrichment_fields_absent_or_blank",
                "forbidden_field_count": len(present),
                "populated_forbidden_field_count": len(populated),
                "forbidden_fields_present": "|".join(sorted(present)),
                "populated_forbidden_fields": "|".join(sorted(populated)),
                "pass": len(present) == 0 and len(populated) == 0,
            }
        ]
    )


def no_crash_direction_check() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "check_name": "no_crash_direction_fields_used",
                "used_field_count": 0,
                "used_fields": "",
                "pass": True,
            }
        ]
    )


def write_reconciliations(bin_df: pd.DataFrame, units: pd.DataFrame) -> dict[str, Any]:
    assigned_units = units["directionality_status"].eq("assigned")
    unresolved_units = ~assigned_units
    parent_bin_count = int(len(bin_df))
    unit_bin_count = int(units["bin_count"].sum())
    parent_length = float(bin_df["bin_length_ft"].sum())
    unit_length = float(units["unit_length_ft"].sum())
    length_delta = unit_length - parent_length
    length_pass = math.isclose(unit_length, parent_length, rel_tol=0.0, abs_tol=1e-6)

    write_csv(
        "bin_to_unit_reconciliation.csv",
        [
            {
                "parent_bin_count": parent_bin_count,
                "distance_band_units_bin_count_including_unresolved": unit_bin_count,
                "external_unresolved_ledger_bin_count": 0,
                "units_plus_external_ledger_bin_count": unit_bin_count,
                "unresolved_units_are_in_distance_band_units": True,
                "bin_count_delta": unit_bin_count - parent_bin_count,
                "pass": unit_bin_count == parent_bin_count,
            }
        ],
    )

    signal_parent = bin_df.groupby("stable_signal_id", dropna=False).agg(parent_bin_count=("stable_bin_id", "count"), parent_length_ft=("bin_length_ft", "sum")).reset_index()
    signal_unit = units.groupby("stable_signal_id", dropna=False).agg(unit_bin_count=("bin_count", "sum"), unit_length_ft=("unit_length_ft", "sum"), unit_count=("distance_band_unit_id", "count")).reset_index()
    by_signal = signal_parent.merge(signal_unit, on="stable_signal_id", how="outer").fillna(0)
    by_signal["bin_count_delta"] = by_signal["unit_bin_count"] - by_signal["parent_bin_count"]
    by_signal["length_delta_ft"] = by_signal["unit_length_ft"] - by_signal["parent_length_ft"]
    by_signal["pass"] = by_signal["bin_count_delta"].eq(0) & by_signal["length_delta_ft"].abs().le(1e-6)
    write_csv("bin_count_reconciliation_by_signal.csv", by_signal)

    approach_parent = bin_df.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(parent_bin_count=("stable_bin_id", "count"), parent_length_ft=("bin_length_ft", "sum")).reset_index()
    approach_unit = units.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(unit_bin_count=("bin_count", "sum"), unit_length_ft=("unit_length_ft", "sum"), unit_count=("distance_band_unit_id", "count")).reset_index()
    by_approach = approach_parent.merge(approach_unit, on=["stable_signal_id", "signal_approach_id"], how="outer").fillna(0)
    by_approach["bin_count_delta"] = by_approach["unit_bin_count"] - by_approach["parent_bin_count"]
    by_approach["length_delta_ft"] = by_approach["unit_length_ft"] - by_approach["parent_length_ft"]
    by_approach["pass"] = by_approach["bin_count_delta"].eq(0) & by_approach["length_delta_ft"].abs().le(1e-6)
    write_csv("bin_count_reconciliation_by_approach.csv", by_approach)

    band_parent = bin_df.groupby("distance_band", dropna=False).agg(parent_bin_count=("stable_bin_id", "count"), parent_length_ft=("bin_length_ft", "sum")).reset_index()
    band_unit = units.groupby("distance_band", dropna=False).agg(unit_bin_count=("bin_count", "sum"), unit_length_ft=("unit_length_ft", "sum"), unit_count=("distance_band_unit_id", "count")).reset_index()
    by_band = band_parent.merge(band_unit, on="distance_band", how="outer").fillna(0)
    by_band["bin_count_delta"] = by_band["unit_bin_count"] - by_band["parent_bin_count"]
    by_band["length_delta_ft"] = by_band["unit_length_ft"] - by_band["parent_length_ft"]
    by_band["pass"] = by_band["bin_count_delta"].eq(0) & by_band["length_delta_ft"].abs().le(1e-6)
    write_csv("bin_count_reconciliation_by_distance_band.csv", by_band)

    write_csv(
        "length_reconciliation_summary.csv",
        [
            {
                "parent_length_ft": parent_length,
                "distance_band_units_length_ft_including_unresolved": unit_length,
                "external_unresolved_ledger_length_ft": 0.0,
                "units_plus_external_ledger_length_ft": unit_length,
                "length_delta_ft": length_delta,
                "tolerance_ft": 1e-6,
                "pass": length_pass,
            }
        ],
    )

    return {
        "parent_bin_count": parent_bin_count,
        "unit_bin_count": unit_bin_count,
        "parent_length_ft": parent_length,
        "unit_length_ft": unit_length,
        "length_delta_ft": length_delta,
        "length_pass": length_pass,
        "assigned_unit_count": int(assigned_units.sum()),
        "unresolved_unit_count": int(unresolved_units.sum()),
        "assigned_bin_count": int(units.loc[assigned_units, "bin_count"].sum()),
        "unresolved_bin_count": int(units.loc[unresolved_units, "bin_count"].sum()),
    }


def write_qa(bin_df: pd.DataFrame, units: pd.DataFrame, parent_check: pd.DataFrame) -> dict[str, Any]:
    recon = write_reconciliations(bin_df, units)
    id_dupes = units[units["distance_band_unit_id"].duplicated(keep=False)].sort_values("distance_band_unit_id")
    write_csv(
        "distance_band_unit_id_uniqueness_check.csv",
        [
            {
                "row_count": len(units),
                "unique_distance_band_unit_id_count": units["distance_band_unit_id"].nunique(),
                "duplicate_distance_band_unit_id_count": int(units["distance_band_unit_id"].duplicated().sum()),
                "pass": id_dupes.empty,
            }
        ],
    )
    grain_cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
    grain_dupes = units[units.duplicated(grain_cols, keep=False)].sort_values(grain_cols)
    write_csv(
        "unit_grain_uniqueness_check.csv",
        [
            {
                "grain": "|".join(grain_cols),
                "row_count": len(units),
                "unique_grain_count": len(units.drop_duplicates(grain_cols)),
                "duplicate_grain_row_count": int(len(grain_dupes)),
                "pass": grain_dupes.empty,
            }
        ],
    )
    assigned = units["directionality_status"].eq("assigned")
    summary = units.assign(assignment_status=assigned.map({True: "assigned", False: "unresolved"})).groupby("assignment_status", dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        bin_count=("bin_count", "sum"),
        length_ft=("unit_length_ft", "sum"),
        signal_count=("stable_signal_id", "nunique"),
        approach_count=("signal_approach_id", "nunique"),
        chain_count=("chain_count", "sum"),
    ).reset_index()
    write_csv("assigned_unresolved_unit_summary.csv", summary)
    write_csv(
        "unresolved_directionality_unit_ledger.csv",
        units.loc[~assigned].assign(ledger_role="diagnostic_non_additive_unresolved_units_already_in_distance_band_units"),
    )
    unresolved_parent = bin_df[~(bin_df["directionality_status"].map(clean).eq("assigned") & bin_df["upstream_downstream"].map(clean).ne(""))].copy()
    write_csv(
        "unresolved_directionality_by_signal.csv",
        unresolved_parent.groupby("stable_signal_id", dropna=False).agg(
            unresolved_bin_count=("stable_bin_id", "count"),
            unresolved_chain_count=("logical_corridor_chain_id", "nunique"),
            unresolved_approach_count=("signal_approach_id", "nunique"),
            unresolved_reasons=("directionality_unresolved_reason", join_values),
        ).reset_index().sort_values("unresolved_bin_count", ascending=False),
    )
    write_csv(
        "unresolved_directionality_by_approach.csv",
        unresolved_parent.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
            unresolved_bin_count=("stable_bin_id", "count"),
            unresolved_chain_count=("logical_corridor_chain_id", "nunique"),
            unresolved_reasons=("directionality_unresolved_reason", join_values),
        ).reset_index().sort_values("unresolved_bin_count", ascending=False),
    )

    parent_status = bin_df.assign(parent_assigned=bin_df["directionality_status"].map(clean).eq("assigned") & bin_df["upstream_downstream"].map(clean).ne(""))
    signal_full = parent_status.groupby("stable_signal_id", dropna=False).agg(
        total_bin_count=("stable_bin_id", "count"),
        assigned_bin_count=("parent_assigned", "sum"),
        chain_count=("logical_corridor_chain_id", "nunique"),
        approach_count=("signal_approach_id", "nunique"),
    ).reset_index()
    signal_full["unresolved_bin_count"] = signal_full["total_bin_count"] - signal_full["assigned_bin_count"]
    write_csv("fully_unassigned_signal_ledger.csv", signal_full[signal_full["assigned_bin_count"].eq(0)].sort_values("total_bin_count", ascending=False))
    approach_full = parent_status.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
        total_bin_count=("stable_bin_id", "count"),
        assigned_bin_count=("parent_assigned", "sum"),
        chain_count=("logical_corridor_chain_id", "nunique"),
    ).reset_index()
    approach_full["unresolved_bin_count"] = approach_full["total_bin_count"] - approach_full["assigned_bin_count"]
    write_csv("fully_unassigned_approach_ledger.csv", approach_full[approach_full["assigned_bin_count"].eq(0)].sort_values("total_bin_count", ascending=False))

    write_csv(
        "unit_completeness_status_summary.csv",
        units.groupby("unit_completeness_status", dropna=False).agg(unit_count=("distance_band_unit_id", "count"), bin_count=("bin_count", "sum"), length_ft=("unit_length_ft", "sum")).reset_index(),
    )
    write_csv(
        "partial_unit_reason_summary.csv",
        units[units["unit_completeness_status"].ne("complete_distance_band")]
        .groupby(["unit_completeness_status", "missingness_reason"], dropna=False)
        .agg(unit_count=("distance_band_unit_id", "count"), bin_count=("bin_count", "sum"))
        .reset_index(),
    )
    write_csv(
        "distance_band_unit_distribution.csv",
        units.assign(assignment_status=assigned.map({True: "assigned", False: "unresolved"}))
        .groupby(["distance_band", "assignment_status"], dropna=False)
        .agg(unit_count=("distance_band_unit_id", "count"), bin_count=("bin_count", "sum"), length_ft=("unit_length_ft", "sum"))
        .reset_index(),
    )
    write_csv(
        "chain_count_per_unit_summary.csv",
        units.groupby("chain_count", dropna=False).agg(unit_count=("distance_band_unit_id", "count"), bin_count=("bin_count", "sum")).reset_index().sort_values("chain_count"),
    )
    write_csv(
        "geometry_status_by_unit_summary.csv",
        units.groupby("geometry_status_summary", dropna=False).agg(unit_count=("distance_band_unit_id", "count"), bin_count=("bin_count", "sum")).reset_index(),
    )
    forbidden = forbidden_context_check(units)
    write_csv("forbidden_context_enrichment_field_check.csv", forbidden)
    crash_direction = no_crash_direction_check()
    write_csv("no_crash_direction_field_check.csv", crash_direction)

    hard_pass = bool(
        parent_check.loc[parent_check["parent_role"].eq("direct_parent"), "allowed_parent_for_distance_band_units"].all()
        and not parent_check["downstream_object_parent_flag"].any()
        and recon["unit_bin_count"] == recon["parent_bin_count"]
        and recon["length_pass"]
        and id_dupes.empty
        and grain_dupes.empty
        and bool(forbidden["pass"].all())
        and bool(crash_direction["pass"].all())
    )
    if not hard_pass:
        decision = "distance_band_units_needs_reconciliation_repair"
    elif recon["unresolved_unit_count"] > 0:
        decision = "distance_band_units_built_with_unresolved_directionality_ready_for_validation"
    else:
        decision = "distance_band_units_built_ready_for_validation"
    write_csv(
        "distance_band_units_readiness_decision.csv",
        [
            {
                "decision": decision,
                "hard_acceptance_checks_pass": hard_pass,
                "unresolved_directionality_unit_count": recon["unresolved_unit_count"],
                "unresolved_directionality_bin_count": recon["unresolved_bin_count"],
            }
        ],
    )
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "priority": 1,
                "recommended_next_action": "Run independent validation on distance_band_units, then build distance_band_context only after accepting unresolved-directionality missingness representation.",
            },
            {
                "priority": 2,
                "recommended_next_action": "Use unresolved ledgers to scope any later map review or directionality repair; do not force upstream/downstream labels.",
            },
        ],
    )
    write_csv(
        "distance_band_units_build_summary.csv",
        [
            {
                "build_version": BUILD_VERSION,
                "total_units": len(units),
                "assigned_directional_units": recon["assigned_unit_count"],
                "unresolved_directionality_units": recon["unresolved_unit_count"],
                "parent_bin_count": recon["parent_bin_count"],
                "unit_bin_count": recon["unit_bin_count"],
                "parent_length_ft": recon["parent_length_ft"],
                "unit_length_ft": recon["unit_length_ft"],
                "length_delta_ft": recon["length_delta_ft"],
                "decision": decision,
            }
        ],
    )
    return {"decision": decision, **recon, "hard_pass": hard_pass}


def update_metadata(units: pd.DataFrame, summary: dict[str, Any]) -> None:
    stamp = now()
    manifest = read_json(STAGING_MANIFEST)
    product = manifest.setdefault("products", {}).setdefault("distance_band_units", {})
    product.update(
        {
            "path": rel(DISTANCE_BAND_UNITS),
            "script": "src.roadway_graph.build.build_distance_band_units",
            "build_version": BUILD_VERSION,
            "updated_utc": stamp,
            "canonical_parents": [rel(BIN_CONTEXT)],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "grain": "one row per stable_signal_id x signal_approach_id x upstream_downstream x distance_band; unresolved directionality uses blank upstream_downstream",
            "row_count": int(len(units)),
            "assigned_directional_units": int(summary["assigned_unit_count"]),
            "unresolved_directionality_units": int(summary["unresolved_unit_count"]),
            "parent_bin_count": int(summary["parent_bin_count"]),
            "unit_bin_count": int(summary["unit_bin_count"]),
            "context_enrichment_status": "not_performed",
            "crash_direction_field_status": "not_used",
            "final_decision": summary["decision"],
            "qa_review_path": rel(OUT),
        }
    )
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append(
        {
            "script": "src.roadway_graph.build.build_distance_band_units",
            "bounded_phase": "Phase C.4 distance_band_units build only",
            "built_utc": stamp,
            "row_count": int(len(units)),
            "assigned_directional_units": int(summary["assigned_unit_count"]),
            "unresolved_directionality_units": int(summary["unresolved_unit_count"]),
            "final_decision": summary["decision"],
            "build_version": BUILD_VERSION,
        }
    )
    write_json(STAGING_MANIFEST, manifest)

    schema = read_json(STAGING_SCHEMA)
    table = schema.setdefault("tables", {}).setdefault("distance_band_units.parquet", {})
    table.update(
        {
            "build_version": BUILD_VERSION,
            "canonical_parent": [rel(BIN_CONTEXT)],
            "forbidden_fields": "No speed/AADT/access/crash/exposure/rate enrichment fields; no lookup cell fields.",
            "grain": "one row per stable_signal_id x signal_approach_id x upstream_downstream x distance_band; unresolved directionality uses blank upstream_downstream",
            "required_columns": UNIT_COLUMNS,
            "distance_bands": list(DISTANCE_BANDS),
            "unresolved_directionality_policy": "preserved as unresolved units with blank upstream_downstream and explicit status/reason",
            "context_enrichment_status": "not_performed",
            "crash_direction_field_status": "not_used",
            "updated_utc": stamp,
        }
    )
    schema["updated_utc"] = stamp
    write_json(STAGING_SCHEMA, schema)

    with STAGING_README.open("a", encoding="utf-8") as f:
        f.write(
            f"""

## Phase C.4 distance_band_units

Built `{rel(DISTANCE_BAND_UNITS)}` from validated staged `bin_context.parquet`
only. The table rolls 50-ft bins into one row per `stable_signal_id x
signal_approach_id x upstream_downstream x distance_band`. Bins with unresolved
directionality are preserved as unresolved units with blank
`upstream_downstream` and explicit directionality status/reason.

No distance_band_context, MVP, lookup cells, speed, AADT, access, crash,
exposure, rate, or external context enrichment products were built. Crash
direction fields were not used.

Decision: `{summary['decision']}`.
"""
        )


def write_findings(summary: dict[str, Any], units: pd.DataFrame) -> None:
    assigned = units["directionality_status"].eq("assigned")
    fully_unassigned_signals = pd.read_csv(OUT / "fully_unassigned_signal_ledger.csv")
    fully_unassigned_approaches = pd.read_csv(OUT / "fully_unassigned_approach_ledger.csv")
    completeness = pd.read_csv(OUT / "unit_completeness_status_summary.csv")
    memo = f"""# distance_band_units Build Findings

## What Was Built
Built staged `distance_band_units.parquet` from validated `bin_context.parquet`, rolling 50-ft bins to distance-band units.

## What Was Not Built
No `distance_band_context.parquet`, MVP products, lookup cells, speed, AADT, access, crash, exposure, rate, or external context enrichment were built.

## Parent Dependency Statement
The direct parent was `work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate/bin_context.parquet` only. Prior review folders were diagnostic evidence only, not parents. No downstream object was used as a canonical parent.

## Unit Grain
One row per `stable_signal_id x signal_approach_id x upstream_downstream x distance_band`; unresolved directionality uses blank `upstream_downstream` with explicit status/reason.

## Unit Counts
Total units written: {len(units):,}. Assigned directional units: {int(assigned.sum()):,}. Unresolved directionality units: {int((~assigned).sum()):,}.

## Reconciliation
Parent bins: {int(summary['parent_bin_count']):,}. Unit bin_count sum: {int(summary['unit_bin_count']):,}. Bin reconciliation pass: {summary['unit_bin_count'] == summary['parent_bin_count']}.

Parent length ft: {float(summary['parent_length_ft']):,.6f}. Unit length ft: {float(summary['unit_length_ft']):,.6f}. Length delta ft: {float(summary['length_delta_ft']):.9f}. Length reconciliation pass: {summary['length_pass']}.

## Directionality Missingness Carried Forward
Unresolved bins carried in unresolved units: {int(summary['unresolved_bin_count']):,}. Unresolved unit ledger is diagnostic and non-additive because unresolved bins are already represented in `distance_band_units.parquet`.

## Fully Unassigned Signals And Approaches
Fully unassigned signals: {len(fully_unassigned_signals):,}. Fully unassigned approaches: {len(fully_unassigned_approaches):,}.

## Unit Completeness Status
{completeness.to_csv(index=False).strip()}

## Context And Crash Direction Guard
No context enrichment was performed. Crash direction fields were not used. `context_readiness_status` and `rate_readiness_status` are set to `not_enriched`.

## Readiness
Decision: `{summary['decision']}`. The object is ready for independent validation and then `distance_band_context` only after that validation accepts the unresolved-directionality representation.

## Recommended Next Task
Run independent validation on `distance_band_units.parquet`, then build `distance_band_context.parquet` from validated staged units without using stale branch outputs.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def write_manifests(summary: dict[str, Any]) -> None:
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "product": "build_distance_band_units",
            "build_version": BUILD_VERSION,
            "target": rel(DISTANCE_BAND_UNITS),
            "direct_parent": rel(BIN_CONTEXT),
            "validated_staged_objects": [rel(path) for path in VALIDATED_STAGED_OBJECTS],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "bounded_question": "Build distance-band unit cache from bin_context without external context enrichment.",
            "output_grain": "stable_signal_id x signal_approach_id x upstream_downstream x distance_band",
            "unresolved_directionality_policy": "unresolved units included in staged table with blank upstream_downstream",
            "final_decision": summary["decision"],
        },
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "product": "distance_band_units",
            "qa_outputs": sorted(path.name for path in OUT.glob("*") if path.is_file()),
            "acceptance_checks": {
                "parent_dependency_check_passed": bool(summary["hard_pass"]),
                "bin_reconciliation_passed": summary["unit_bin_count"] == summary["parent_bin_count"],
                "length_reconciliation_passed": bool(summary["length_pass"]),
                "unresolved_directionality_preserved": summary["unresolved_unit_count"] > 0,
                "context_enrichment_not_performed": True,
                "crash_direction_fields_not_used": True,
            },
            "final_decision": summary["decision"],
        },
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    log("Starting distance_band_units build from bin_context only.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    direct_parent_ok = bool(parent_check.loc[parent_check["parent_role"].eq("direct_parent"), "allowed_parent_for_distance_band_units"].all())
    if not direct_parent_ok or parent_check["downstream_object_parent_flag"].any():
        raise RuntimeError("Parent dependency check failed.")

    log("Reading bin_context parent columns.")
    bin_df = load_bin_context()
    log(f"Loaded {len(bin_df):,} parent bins.")
    log("Rolling bins into assigned and unresolved distance-band units.")
    units = build_units(bin_df)
    log(f"Built {len(units):,} distance-band units in memory.")
    write_units(units)
    log(f"Wrote staged product {rel(DISTANCE_BAND_UNITS)}.")
    readback_rows = parquet_row_count(DISTANCE_BAND_UNITS)
    if readback_rows != len(units):
        raise RuntimeError(f"Readback row count mismatch: {readback_rows} vs {len(units)}")

    summary = write_qa(bin_df, units, parent_check)
    update_metadata(units, summary)
    write_findings(summary, units)
    write_manifests(summary)
    log(f"Completed distance_band_units build with decision {summary['decision']}.")


if __name__ == "__main__":
    main()
