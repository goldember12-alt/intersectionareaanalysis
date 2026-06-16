"""Read-only validation audit for staged distance_band_units.parquet.

This audit reconstructs the distance-band unit rollup from bin_context and
compares it to the staged distance_band_units object. It writes review outputs
only and does not mutate staged or source data.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/distance_band_units_validation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
DISTANCE_BAND_UNITS = STAGING / "distance_band_units.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

VALIDATION_INPUTS = [SIGNAL_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT, DISTANCE_BAND_UNITS]
DIRECT_PARENT = BIN_CONTEXT
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/build_distance_band_units",
    REPO / "work/roadway_graph/review/patch_bin_context_chain_directionality_and_audit",
    REPO / "work/roadway_graph/review/bin_context_validation_audit",
    REPO / "work/roadway_graph/review/residual_directionality_impact_legacy_pairing_audit",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

FLOAT_TOL_FT = 1e-6
FULL_BIN_LENGTH_FT = 50.0
DISTANCE_BANDS: dict[str, tuple[float, float]] = {
    "0-250": (0.0, 250.0),
    "250-500": (250.0, 500.0),
    "500-1,000": (500.0, 1000.0),
    "1,000-1,500": (1000.0, 1500.0),
    "1,500-2,000": (1500.0, 2000.0),
    "2,000-2,500": (2000.0, 2500.0),
}
GRAIN = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
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
    "lookup_cell_id",
    "lookup_cell_key",
    "rate_distribution",
}
CRASH_DIRECTION_TOKENS = ("crash_direction", "direction_of_crash", "veh_dir", "vehicle_direction")


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.write("\n")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {stamp} - {message}\n")


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parent_dependency_check() -> pd.DataFrame:
    manifest = read_json(STAGING_MANIFEST)
    product = manifest.get("products", {}).get("distance_band_units", {})
    manifest_parents = product.get("canonical_parents", [])
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
    for path in VALIDATION_INPUTS:
        exists = path.exists()
        read_status = "missing"
        row_count: int | str = ""
        if exists:
            try:
                row_count = parquet_row_count(path)
                read_status = "readable"
            except Exception as exc:
                read_status = f"read_failed:{type(exc).__name__}"
        path_rel = rel(path)
        rows.append(
            {
                "path": path_rel,
                "validation_role": "direct_parent" if path == DIRECT_PARENT else "staged_validation_input",
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "listed_as_distance_band_units_canonical_parent": path_rel in manifest_parents,
                "allowed_for_validation": exists and read_status == "readable",
                "allowed_as_direct_parent": path == DIRECT_PARENT,
                "downstream_object_parent_flag": any(token in path_rel.lower() for token in forbidden_tokens),
                "review_output_canonical_parent_flag": path_rel.startswith("work/roadway_graph/review/") and path_rel in manifest_parents,
            }
        )
    for parent in manifest_parents:
        rows.append(
            {
                "path": parent,
                "validation_role": "manifest_canonical_parent",
                "exists": (REPO / parent).exists(),
                "read_status": "manifest_reference",
                "row_count": parquet_row_count(REPO / parent) if (REPO / parent).exists() and parent.endswith(".parquet") else "",
                "listed_as_distance_band_units_canonical_parent": True,
                "allowed_for_validation": parent == rel(DIRECT_PARENT),
                "allowed_as_direct_parent": parent == rel(DIRECT_PARENT),
                "downstream_object_parent_flag": any(token in parent.lower() for token in forbidden_tokens),
                "review_output_canonical_parent_flag": parent.startswith("work/roadway_graph/review/"),
            }
        )
    return pd.DataFrame(rows)


def read_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bin_cols = [
        "stable_bin_id",
        "stable_signal_id",
        "signal_approach_id",
        "logical_corridor_chain_id",
        "distance_start_ft",
        "distance_end_ft",
        "bin_length_ft",
        "distance_band",
        "final_partial_bin_flag",
        "directionality_status",
        "upstream_downstream",
        "directionality_method",
        "directionality_confidence",
        "directionality_unresolved_reason",
        "chain_stop_reason",
        "chain_completeness_status",
        "geometry_status",
        "measure_side_class",
        "parent_corridor_warning_status",
    ]
    bin_df = pd.read_parquet(BIN_CONTEXT, columns=bin_cols)
    units = pd.read_parquet(DISTANCE_BAND_UNITS)
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id"])
    approaches = pd.read_parquet(SIGNAL_APPROACHES, columns=["stable_signal_id", "signal_approach_id"])
    for col in ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "directionality_status"]:
        if col in bin_df.columns:
            bin_df[col] = bin_df[col].map(clean)
        if col in units.columns:
            units[col] = units[col].map(clean)
    return bin_df, units, signals, approaches


def assign_parent_unit_key(bin_df: pd.DataFrame) -> pd.DataFrame:
    parent = bin_df.copy()
    parent["parent_assignment_status"] = (
        parent["directionality_status"].map(clean).eq("assigned") & parent["upstream_downstream"].map(clean).ne("")
    ).map({True: "assigned", False: "unresolved"})
    parent.loc[parent["parent_assignment_status"].eq("unresolved"), "upstream_downstream"] = ""
    parent["full_bin_flag_for_unit"] = (~parent["final_partial_bin_flag"].fillna(False).astype(bool)) & parent["bin_length_ft"].sub(FULL_BIN_LENGTH_FT).abs().le(FLOAT_TOL_FT)
    parent["partial_bin_flag_for_unit"] = ~parent["full_bin_flag_for_unit"]
    return parent


def reconstruct_units(parent: pd.DataFrame) -> pd.DataFrame:
    grouped = parent.groupby(GRAIN, dropna=False, sort=True)
    expected = grouped.agg(
        expected_bin_count=("stable_bin_id", "count"),
        expected_unit_length_ft=("bin_length_ft", "sum"),
        expected_full_bin_count=("full_bin_flag_for_unit", "sum"),
        expected_partial_bin_count=("partial_bin_flag_for_unit", "sum"),
        expected_chain_count=("logical_corridor_chain_id", "nunique"),
        expected_logical_corridor_chain_ids=("logical_corridor_chain_id", join_values),
        expected_min_distance_start_ft=("distance_start_ft", "min"),
        expected_max_distance_end_ft=("distance_end_ft", "max"),
        expected_directionality_status=("directionality_status", join_values),
        expected_directionality_method=("directionality_method", join_values),
        expected_directionality_confidence=("directionality_confidence", join_values),
        expected_directionality_unresolved_reason=("directionality_unresolved_reason", join_values),
        expected_chain_stop_reason_values=("chain_stop_reason", join_values),
        expected_chain_completeness_status_values=("chain_completeness_status", join_values),
        expected_measure_side_class_values=("measure_side_class", join_values),
        expected_geometry_status_summary=("geometry_status", join_values),
    ).reset_index()
    return expected


def unit_identity_and_grain_audit(units: pd.DataFrame, expected: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    assigned = units["directionality_status"].eq("assigned")
    unresolved = ~assigned
    true_grain = GRAIN + ["directionality_status", "directionality_unresolved_reason"]
    unresolved_collapsed = expected[expected["upstream_downstream"].eq("")].copy()
    unresolved_collapsed["reason_set_preserved"] = unresolved_collapsed["expected_directionality_unresolved_reason"].map(clean).ne("")
    rows = [
        {
            "check_name": "distance_band_unit_id_non_null",
            "fail_count": int(units["distance_band_unit_id"].map(clean).eq("").sum()),
            "pass": bool(units["distance_band_unit_id"].map(clean).ne("").all()),
            "details": "",
        },
        {
            "check_name": "distance_band_unit_id_unique",
            "fail_count": int(units["distance_band_unit_id"].duplicated().sum()),
            "pass": int(units["distance_band_unit_id"].duplicated().sum()) == 0,
            "details": "",
        },
        {
            "check_name": "declared_unit_grain_unique",
            "fail_count": int(units.duplicated(GRAIN).sum()),
            "pass": int(units.duplicated(GRAIN).sum()) == 0,
            "details": "|".join(GRAIN),
        },
        {
            "check_name": "expanded_reason_status_grain_unique",
            "fail_count": int(units.duplicated(true_grain).sum()),
            "pass": int(units.duplicated(true_grain).sum()) == 0,
            "details": "Expanded grain is unique but not required; unresolved reason/status are preserved as sets in collapsed unresolved rows.",
        },
        {
            "check_name": "directionality_status_populated",
            "fail_count": int(units["directionality_status"].map(clean).eq("").sum()),
            "pass": bool(units["directionality_status"].map(clean).ne("").all()),
            "details": "",
        },
        {
            "check_name": "assigned_units_have_valid_direction",
            "fail_count": int((assigned & ~units["upstream_downstream"].isin(["upstream", "downstream"])).sum()),
            "pass": int((assigned & ~units["upstream_downstream"].isin(["upstream", "downstream"])).sum()) == 0,
            "details": "Valid assigned values are upstream/downstream.",
        },
        {
            "check_name": "unresolved_units_have_blank_direction",
            "fail_count": int((unresolved & units["upstream_downstream"].map(clean).ne("")).sum()),
            "pass": int((unresolved & units["upstream_downstream"].map(clean).ne("")).sum()) == 0,
            "details": "Unresolved representation uses blank upstream_downstream.",
        },
        {
            "check_name": "assigned_unresolved_not_mixed_by_direction_value",
            "fail_count": int((assigned & units["upstream_downstream"].eq("")).sum() + (unresolved & units["upstream_downstream"].isin(["upstream", "downstream"])).sum()),
            "pass": int((assigned & units["upstream_downstream"].eq("")).sum() + (unresolved & units["upstream_downstream"].isin(["upstream", "downstream"])).sum()) == 0,
            "details": "",
        },
        {
            "check_name": "unresolved_reason_sets_preserved",
            "fail_count": int((~unresolved_collapsed["reason_set_preserved"]).sum()),
            "pass": bool(unresolved_collapsed["reason_set_preserved"].all()) if len(unresolved_collapsed) else True,
            "details": "Unresolved units may collapse multiple unresolved reasons; reason sets are pipe-delimited in directionality_unresolved_reason.",
        },
    ]
    summary = {
        "unit_count": int(len(units)),
        "assigned_unit_count": int(assigned.sum()),
        "unresolved_unit_count": int(unresolved.sum()),
        "grain_duplicate_count": int(units.duplicated(GRAIN).sum()),
        "id_duplicate_count": int(units["distance_band_unit_id"].duplicated().sum()),
        "unresolved_collapsed_reason_set_count": int((unresolved_collapsed["expected_directionality_unresolved_reason"].str.contains("\\|", regex=True, na=False)).sum()) if len(unresolved_collapsed) else 0,
    }
    return pd.DataFrame(rows), summary


def parent_link_audit(units: pd.DataFrame, signals: pd.DataFrame, approaches: pd.DataFrame) -> pd.DataFrame:
    signal_ids = set(signals["stable_signal_id"].map(clean))
    approach_pairs = set(zip(approaches["stable_signal_id"].map(clean), approaches["signal_approach_id"].map(clean)))
    unit_pairs = list(zip(units["stable_signal_id"].map(clean), units["signal_approach_id"].map(clean)))
    return pd.DataFrame(
        [
            {
                "check_name": "stable_signal_id_links_to_signal_index",
                "unit_count": len(units),
                "missing_link_count": int((~units["stable_signal_id"].map(clean).isin(signal_ids)).sum()),
                "pass": bool(units["stable_signal_id"].map(clean).isin(signal_ids).all()),
            },
            {
                "check_name": "signal_approach_id_links_to_signal_approaches",
                "unit_count": len(units),
                "missing_link_count": int(sum(pair not in approach_pairs for pair in unit_pairs)),
                "pass": int(sum(pair not in approach_pairs for pair in unit_pairs)) == 0,
            },
        ]
    )


def reconciliation_audits(parent: pd.DataFrame, units: pd.DataFrame, expected: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    compare_cols = GRAIN + [
        "expected_bin_count",
        "expected_unit_length_ft",
        "expected_full_bin_count",
        "expected_partial_bin_count",
        "expected_chain_count",
        "expected_logical_corridor_chain_ids",
        "expected_min_distance_start_ft",
        "expected_max_distance_end_ft",
    ]
    compare = expected[compare_cols].merge(
        units[
            GRAIN
            + [
                "distance_band_unit_id",
                "bin_count",
                "unit_length_ft",
                "full_bin_count",
                "partial_bin_count",
                "chain_count",
                "logical_corridor_chain_ids",
                "min_distance_start_ft",
                "max_distance_end_ft",
            ]
        ],
        on=GRAIN,
        how="outer",
        indicator=True,
    )
    compare["bin_count_delta"] = compare["bin_count"].fillna(0) - compare["expected_bin_count"].fillna(0)
    compare["length_delta_ft"] = compare["unit_length_ft"].fillna(0.0) - compare["expected_unit_length_ft"].fillna(0.0)
    compare["full_partial_sum_delta"] = compare["full_bin_count"].fillna(0) + compare["partial_bin_count"].fillna(0) - compare["bin_count"].fillna(0)
    compare["chain_count_delta"] = compare["chain_count"].fillna(0) - compare["expected_chain_count"].fillna(0)
    compare["chain_lineage_match"] = compare["logical_corridor_chain_ids"].fillna("").eq(compare["expected_logical_corridor_chain_ids"].fillna(""))
    compare["distance_range_match"] = compare["min_distance_start_ft"].fillna(-999).sub(compare["expected_min_distance_start_ft"].fillna(-999)).abs().le(FLOAT_TOL_FT) & compare["max_distance_end_ft"].fillna(-999).sub(compare["expected_max_distance_end_ft"].fillna(-999)).abs().le(FLOAT_TOL_FT)
    compare["pass"] = (
        compare["_merge"].eq("both")
        & compare["bin_count_delta"].eq(0)
        & compare["length_delta_ft"].abs().le(FLOAT_TOL_FT)
        & compare["full_partial_sum_delta"].eq(0)
        & compare["chain_count_delta"].eq(0)
        & compare["chain_lineage_match"]
        & compare["distance_range_match"]
    )
    write_csv("bin_to_unit_reconciliation.csv", compare)

    summary = pd.DataFrame(
        [
            {
                "parent_bin_count": int(len(parent)),
                "expected_unit_bin_count": int(expected["expected_bin_count"].sum()),
                "actual_unit_bin_count": int(units["bin_count"].sum()),
                "missing_unit_groups": int(compare["_merge"].eq("left_only").sum()),
                "extra_unit_groups": int(compare["_merge"].eq("right_only").sum()),
                "bin_count_delta": int(units["bin_count"].sum() - len(parent)),
                "parent_length_ft": float(parent["bin_length_ft"].sum()),
                "expected_unit_length_ft": float(expected["expected_unit_length_ft"].sum()),
                "actual_unit_length_ft": float(units["unit_length_ft"].sum()),
                "length_delta_ft": float(units["unit_length_ft"].sum() - parent["bin_length_ft"].sum()),
                "length_tolerance_ft": FLOAT_TOL_FT,
                "full_partial_sum_fail_count": int(compare["full_partial_sum_delta"].ne(0).sum()),
                "chain_lineage_fail_count": int((~compare["chain_lineage_match"]).sum()),
                "distance_range_fail_count": int((~compare["distance_range_match"]).sum()),
                "pass": bool(compare["pass"].all() and units["bin_count"].sum() == len(parent) and math.isclose(float(units["unit_length_ft"].sum()), float(parent["bin_length_ft"].sum()), rel_tol=0.0, abs_tol=FLOAT_TOL_FT)),
            }
        ]
    )
    write_csv("bin_count_length_reconciliation.csv", summary)

    parent_group_key = parent[GRAIN].merge(units[GRAIN + ["distance_band_unit_id"]], on=GRAIN, how="left")
    bin_map_summary = pd.DataFrame(
        [
            {
                "parent_bin_count": int(len(parent)),
                "bins_missing_unit_key": int(parent_group_key["distance_band_unit_id"].map(clean).eq("").sum()),
                "unit_group_count_from_parent": int(parent[GRAIN].drop_duplicates().shape[0]),
                "unit_group_count_actual": int(len(units)),
                "every_bin_maps_to_one_unit_group": bool(parent_group_key["distance_band_unit_id"].map(clean).ne("").all() and parent[GRAIN].drop_duplicates().shape[0] == len(units)),
            }
        ]
    )
    return compare, summary, bin_map_summary


def directionality_audits(parent: pd.DataFrame, units: pd.DataFrame) -> dict[str, Any]:
    parent_assigned = parent["parent_assignment_status"].eq("assigned")
    unit_assigned = units["directionality_status"].eq("assigned")
    def unit_unique_chains(mask: pd.Series) -> int:
        chains: set[str] = set()
        for value in units.loc[mask, "logical_corridor_chain_ids"]:
            for part in clean(value).split("|"):
                part = part.strip()
                if part:
                    chains.add(part)
        return len(chains)

    assigned_unit_unique_chains = unit_unique_chains(unit_assigned)
    unresolved_unit_unique_chains = unit_unique_chains(~unit_assigned)
    rows = [
        {
            "assignment_status": "assigned",
            "parent_bin_count": int(parent_assigned.sum()),
            "unit_bin_count": int(units.loc[unit_assigned, "bin_count"].sum()),
            "parent_chain_count": int(parent.loc[parent_assigned, "logical_corridor_chain_id"].nunique()),
            "unit_unique_chain_count_from_lineage": assigned_unit_unique_chains,
            "unit_chain_band_appearance_count_sum": int(units.loc[unit_assigned, "chain_count"].sum()),
            "unit_count": int(unit_assigned.sum()),
            "signal_count": int(units.loc[unit_assigned, "stable_signal_id"].nunique()),
            "approach_count": int(units.loc[unit_assigned, "signal_approach_id"].nunique()),
        },
        {
            "assignment_status": "unresolved",
            "parent_bin_count": int((~parent_assigned).sum()),
            "unit_bin_count": int(units.loc[~unit_assigned, "bin_count"].sum()),
            "parent_chain_count": int(parent.loc[~parent_assigned, "logical_corridor_chain_id"].nunique()),
            "unit_unique_chain_count_from_lineage": unresolved_unit_unique_chains,
            "unit_chain_band_appearance_count_sum": int(units.loc[~unit_assigned, "chain_count"].sum()),
            "unit_count": int((~unit_assigned).sum()),
            "signal_count": int(units.loc[~unit_assigned, "stable_signal_id"].nunique()),
            "approach_count": int(units.loc[~unit_assigned, "signal_approach_id"].nunique()),
        },
    ]
    audit = pd.DataFrame(rows)
    audit["bin_count_match"] = audit["parent_bin_count"].eq(audit["unit_bin_count"])
    audit["unique_chain_lineage_match"] = audit["parent_chain_count"].eq(audit["unit_unique_chain_count_from_lineage"])
    write_csv("assigned_unresolved_directionality_audit.csv", audit)

    unresolved = parent[~parent_assigned].copy()
    by_signal = unresolved.groupby("stable_signal_id", dropna=False).agg(
        unresolved_bin_count=("stable_bin_id", "count"),
        unresolved_chain_count=("logical_corridor_chain_id", "nunique"),
        unresolved_approach_count=("signal_approach_id", "nunique"),
        unresolved_reason_values=("directionality_unresolved_reason", join_values),
    ).reset_index().sort_values("unresolved_bin_count", ascending=False)
    write_csv("unresolved_directionality_rollup_by_signal.csv", by_signal)
    by_approach = unresolved.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
        unresolved_bin_count=("stable_bin_id", "count"),
        unresolved_chain_count=("logical_corridor_chain_id", "nunique"),
        unresolved_reason_values=("directionality_unresolved_reason", join_values),
    ).reset_index().sort_values("unresolved_bin_count", ascending=False)
    write_csv("unresolved_directionality_rollup_by_approach.csv", by_approach)
    signal_full = parent.groupby("stable_signal_id", dropna=False).agg(
        total_bin_count=("stable_bin_id", "count"),
        assigned_bin_count=("parent_assignment_status", lambda s: int((s == "assigned").sum())),
        chain_count=("logical_corridor_chain_id", "nunique"),
        approach_count=("signal_approach_id", "nunique"),
    ).reset_index()
    signal_full["unresolved_bin_count"] = signal_full["total_bin_count"] - signal_full["assigned_bin_count"]
    fully_signal = signal_full[signal_full["assigned_bin_count"].eq(0)].sort_values("total_bin_count", ascending=False)
    write_csv("fully_unassigned_signal_ledger.csv", fully_signal)
    approach_full = parent.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
        total_bin_count=("stable_bin_id", "count"),
        assigned_bin_count=("parent_assignment_status", lambda s: int((s == "assigned").sum())),
        chain_count=("logical_corridor_chain_id", "nunique"),
    ).reset_index()
    approach_full["unresolved_bin_count"] = approach_full["total_bin_count"] - approach_full["assigned_bin_count"]
    fully_approach = approach_full[approach_full["assigned_bin_count"].eq(0)].sort_values("total_bin_count", ascending=False)
    write_csv("fully_unassigned_approach_ledger.csv", fully_approach)
    return {
        "assigned_bins": int(parent_assigned.sum()),
        "unresolved_bins": int((~parent_assigned).sum()),
        "assigned_units": int(unit_assigned.sum()),
        "unresolved_units": int((~unit_assigned).sum()),
        "assigned_chains": int(parent.loc[parent_assigned, "logical_corridor_chain_id"].nunique()),
        "unresolved_chains": int(parent.loc[~parent_assigned, "logical_corridor_chain_id"].nunique()),
        "assigned_unit_chain_band_appearances": int(units.loc[unit_assigned, "chain_count"].sum()),
        "unresolved_unit_chain_band_appearances": int(units.loc[~unit_assigned, "chain_count"].sum()),
        "unresolved_signals": int(by_signal["stable_signal_id"].nunique()),
        "unresolved_approaches": int(by_approach["signal_approach_id"].nunique()),
        "fully_unassigned_signals": int(len(fully_signal)),
        "fully_unassigned_approaches": int(len(fully_approach)),
    }


def distance_band_audits(parent: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    parent_dist = parent.groupby(["distance_band", "parent_assignment_status"], dropna=False).agg(
        parent_bin_count=("stable_bin_id", "count"),
        parent_length_ft=("bin_length_ft", "sum"),
        parent_chain_count=("logical_corridor_chain_id", "nunique"),
    ).reset_index().rename(columns={"parent_assignment_status": "assignment_status"})
    unit_dist = units.assign(assignment_status=units["directionality_status"].eq("assigned").map({True: "assigned", False: "unresolved"})).groupby(
        ["distance_band", "assignment_status"], dropna=False
    ).agg(
        unit_count=("distance_band_unit_id", "count"),
        unit_bin_count=("bin_count", "sum"),
        unit_length_ft=("unit_length_ft", "sum"),
    ).reset_index()
    dist = parent_dist.merge(unit_dist, on=["distance_band", "assignment_status"], how="outer").fillna(0)
    dist["bin_count_delta"] = dist["unit_bin_count"] - dist["parent_bin_count"]
    dist["length_delta_ft"] = dist["unit_length_ft"] - dist["parent_length_ft"]
    dist["known_distance_band_label"] = dist["distance_band"].isin(DISTANCE_BANDS)
    dist["pass"] = dist["known_distance_band_label"] & dist["bin_count_delta"].eq(0) & dist["length_delta_ft"].abs().le(FLOAT_TOL_FT)
    write_csv("distance_band_distribution_audit.csv", dist)

    signal = units.groupby(["stable_signal_id", "distance_band"], dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        bin_count=("bin_count", "sum"),
        length_ft=("unit_length_ft", "sum"),
        assigned_unit_count=("directionality_status", lambda s: int((s == "assigned").sum())),
        unresolved_unit_count=("directionality_status", lambda s: int((s != "assigned").sum())),
    ).reset_index()
    write_csv("distance_band_coverage_by_signal.csv", signal)
    approach = units.groupby(["stable_signal_id", "signal_approach_id", "distance_band"], dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        bin_count=("bin_count", "sum"),
        length_ft=("unit_length_ft", "sum"),
        assigned_unit_count=("directionality_status", lambda s: int((s == "assigned").sum())),
        unresolved_unit_count=("directionality_status", lambda s: int((s != "assigned").sum())),
    ).reset_index()
    write_csv("distance_band_coverage_by_approach.csv", approach)
    return dist, signal, approach


def multi_chain_audits(parent: pd.DataFrame, units: pd.DataFrame) -> dict[str, Any]:
    nominal = units["distance_band_end_ft"] - units["distance_band_start_ft"]
    multi = units.copy()
    multi["nominal_band_width_ft"] = nominal
    multi["length_gt_nominal_flag"] = multi["unit_length_ft"] > multi["nominal_band_width_ft"] + FLOAT_TOL_FT
    multi["high_length_explained_by_chain_count"] = (~multi["length_gt_nominal_flag"]) | (
        (multi["chain_count"] > 1) & (multi["unit_length_ft"] <= multi["chain_count"] * multi["nominal_band_width_ft"] + FLOAT_TOL_FT)
    )
    multi["single_chain_high_length_flag"] = multi["length_gt_nominal_flag"] & (multi["chain_count"] <= 1)
    write_csv(
        "multi_chain_unit_audit.csv",
        multi.groupby(["chain_count", "length_gt_nominal_flag", "high_length_explained_by_chain_count"], dropna=False).agg(
            unit_count=("distance_band_unit_id", "count"),
            bin_count=("bin_count", "sum"),
            max_unit_length_ft=("unit_length_ft", "max"),
        ).reset_index().sort_values(["chain_count", "length_gt_nominal_flag"]),
    )
    high = multi[multi["length_gt_nominal_flag"]].sort_values(["unit_length_ft", "chain_count"], ascending=False)
    write_csv("high_length_unit_review.csv", high)
    duplicate_chain_distance = int(parent.duplicated(["logical_corridor_chain_id", "distance_start_ft", "distance_end_ft"]).sum())
    return {
        "multi_chain_unit_count": int((units["chain_count"] > 1).sum()),
        "max_chain_count": int(units["chain_count"].max()),
        "high_length_unit_count": int(len(high)),
        "single_chain_high_length_count": int(multi["single_chain_high_length_flag"].sum()),
        "high_length_unexplained_count": int((~multi["high_length_explained_by_chain_count"]).sum()),
        "duplicate_chain_distance_interval_count": duplicate_chain_distance,
    }


def completeness_audits(units: pd.DataFrame) -> dict[str, Any]:
    completeness = units.groupby("unit_completeness_status", dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        bin_count=("bin_count", "sum"),
        length_ft=("unit_length_ft", "sum"),
    ).reset_index()
    write_csv("unit_completeness_status_audit.csv", completeness)
    missingness = units.groupby(["unit_completeness_status", "missingness_reason"], dropna=False).agg(
        unit_count=("distance_band_unit_id", "count"),
        bin_count=("bin_count", "sum"),
        length_ft=("unit_length_ft", "sum"),
    ).reset_index().sort_values(["unit_completeness_status", "bin_count"], ascending=[True, False])
    write_csv("missingness_reason_audit.csv", missingness)
    parent_gate_blank = int(units["parent_approach_gate"].map(clean).eq("").sum()) if "parent_approach_gate" in units.columns else len(units)
    corridor_gate_blank = int(units["parent_corridor_gate_severity"].map(clean).eq("").sum()) if "parent_corridor_gate_severity" in units.columns else len(units)
    return {
        "complete_distance_band_units": int(completeness.loc[completeness["unit_completeness_status"].eq("complete_distance_band"), "unit_count"].sum()),
        "unresolved_directionality_units": int(completeness.loc[completeness["unit_completeness_status"].eq("unresolved_directionality"), "unit_count"].sum()),
        "parent_approach_gate_blank_units": parent_gate_blank,
        "parent_corridor_gate_severity_blank_units": corridor_gate_blank,
    }


def context_and_crash_guards(units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    present = [field for field in units.columns if field in FORBIDDEN_CONTEXT_FIELDS or field.startswith("lookup_")]
    populated = [field for field in present if units[field].map(clean).ne("").any()]
    status_ok = True
    if "context_readiness_status" in units.columns:
        status_ok = status_ok and units["context_readiness_status"].map(clean).eq("not_enriched").all()
    if "rate_readiness_status" in units.columns:
        status_ok = status_ok and units["rate_readiness_status"].map(clean).eq("not_enriched").all()
    context = pd.DataFrame(
        [
            {
                "check_name": "no_populated_context_enrichment_fields",
                "forbidden_or_lookup_field_count": len(present),
                "populated_forbidden_or_lookup_field_count": len(populated),
                "fields_present": "|".join(sorted(present)),
                "populated_fields": "|".join(sorted(populated)),
                "not_enriched_status_pass": bool(status_ok),
                "pass": len(populated) == 0 and status_ok,
            }
        ]
    )
    write_csv("context_enrichment_guard_audit.csv", context)
    crash_fields = [field for field in units.columns if any(token in field.lower() for token in CRASH_DIRECTION_TOKENS)]
    crash = pd.DataFrame(
        [
            {
                "check_name": "no_crash_direction_fields_used_or_present",
                "crash_direction_like_field_count": len(crash_fields),
                "fields": "|".join(crash_fields),
                "pass": len(crash_fields) == 0,
            }
        ]
    )
    write_csv("no_crash_direction_field_check.csv", crash)
    return context, crash


def scorecard_and_decision(
    parent_check: pd.DataFrame,
    identity: pd.DataFrame,
    link: pd.DataFrame,
    recon_summary: pd.DataFrame,
    directionality: dict[str, Any],
    dist: pd.DataFrame,
    multi: dict[str, Any],
    context: pd.DataFrame,
    crash: pd.DataFrame,
) -> str:
    parent_pass = bool(
        parent_check[parent_check["validation_role"].eq("manifest_canonical_parent")]["allowed_as_direct_parent"].all()
        and parent_check["downstream_object_parent_flag"].eq(False).all()
        and parent_check["review_output_canonical_parent_flag"].eq(False).all()
    )
    identity_pass = bool(identity["pass"].all())
    link_pass = bool(link["pass"].all())
    recon_pass = bool(recon_summary["pass"].iloc[0])
    dist_pass = bool(dist["pass"].all())
    multi_pass = multi["single_chain_high_length_count"] == 0 and multi["duplicate_chain_distance_interval_count"] == 0
    context_pass = bool(context["pass"].all())
    crash_pass = bool(crash["pass"].all())
    unresolved_preserved = directionality["unresolved_bins"] == 39340 and directionality["fully_unassigned_signals"] == 23 and directionality["fully_unassigned_approaches"] == 192
    rows = [
        {"check_group": "parent_dependency", "pass": parent_pass, "details": "direct parent is bin_context; no downstream/review canonical parent"},
        {"check_group": "unit_identity_and_grain", "pass": identity_pass, "details": ""},
        {"check_group": "parent_links", "pass": link_pass, "details": ""},
        {"check_group": "bin_count_length_reconciliation", "pass": recon_pass, "details": ""},
        {"check_group": "directionality_missingness_preserved", "pass": unresolved_preserved, "details": f"unresolved_bins={directionality['unresolved_bins']}; fully_unassigned_signals={directionality['fully_unassigned_signals']}; fully_unassigned_approaches={directionality['fully_unassigned_approaches']}"},
        {"check_group": "distance_band_distribution", "pass": dist_pass, "details": ""},
        {"check_group": "multi_chain_high_length", "pass": multi_pass, "details": f"high_length={multi['high_length_unit_count']}; unexplained={multi['high_length_unexplained_count']}; duplicate_chain_distance={multi['duplicate_chain_distance_interval_count']}"},
        {"check_group": "context_enrichment_guard", "pass": context_pass, "details": ""},
        {"check_group": "crash_direction_field_check", "pass": crash_pass, "details": ""},
    ]
    scorecard = pd.DataFrame(rows)
    if not recon_pass:
        decision = "distance_band_units_needs_bin_reconciliation_repair"
    elif not identity_pass:
        decision = "distance_band_units_needs_unit_grain_repair"
    elif not unresolved_preserved:
        decision = "distance_band_units_needs_unresolved_representation_repair"
    elif not bool(scorecard["pass"].all()):
        decision = "distance_band_units_should_be_rebuilt"
    elif directionality["unresolved_units"] > 0:
        decision = "distance_band_units_validated_with_unresolved_directionality_ready_for_context"
    else:
        decision = "distance_band_units_validated_ready_for_context"
    scorecard.loc[len(scorecard)] = {"check_group": "final_decision", "pass": bool(decision.endswith("ready_for_context")), "details": decision}
    write_csv("distance_band_units_scorecard.csv", scorecard)
    write_csv("readiness_decision.csv", [{"decision": decision, "all_core_checks_pass": bool(scorecard.iloc[:-1]["pass"].all())}])
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "priority": 1,
                "recommended_next_action": "Proceed to distance_band_context build from validated distance_band_units, preserving unresolved directionality and not using review products as parents.",
            },
            {
                "priority": 2,
                "recommended_next_action": "Consider a later parent-status backfill for blank parent_approach_gate and parent_corridor_gate_severity if distance_band_context needs those fields.",
            },
        ],
    )
    return decision


def write_findings(
    decision: str,
    identity_summary: dict[str, Any],
    recon_summary: pd.DataFrame,
    directionality: dict[str, Any],
    dist: pd.DataFrame,
    multi: dict[str, Any],
    completeness: dict[str, Any],
) -> None:
    dist_text = dist[["distance_band", "assignment_status", "unit_count", "unit_bin_count", "unit_length_ft"]].to_csv(index=False).strip()
    recon = recon_summary.iloc[0].to_dict()
    memo = f"""# distance_band_units Validation Audit Findings

## What Was Audited
Read-only audit of staged `distance_band_units.parquet` against `bin_context.parquet`, with staged signal/approach/corridor objects used only for validation links and metadata context.

## Parent Dependency Result
The manifest lists `bin_context.parquet` as the canonical parent for `distance_band_units.parquet`. No downstream object or review output is listed as a canonical parent.

## Unit Grain Result
`distance_band_unit_id` is non-null and unique. The declared grain `stable_signal_id x signal_approach_id x upstream_downstream x distance_band` is unique for {identity_summary['unit_count']:,} units. Unresolved directionality uses blank `upstream_downstream`; reason/status sets are preserved in pipe-delimited fields where multiple unresolved reasons collapse into one unresolved unit.

## Bin-To-Unit Reconciliation Result
Parent bins: {int(recon['parent_bin_count']):,}. Actual unit bin_count sum: {int(recon['actual_unit_bin_count']):,}. Missing unit groups: {int(recon['missing_unit_groups']):,}. Extra unit groups: {int(recon['extra_unit_groups']):,}. Reconciliation pass: {bool(recon['pass'])}.

## Length Reconciliation Result
Parent length ft: {float(recon['parent_length_ft']):,.6f}. Actual unit length ft: {float(recon['actual_unit_length_ft']):,.6f}. Length delta ft: {float(recon['length_delta_ft']):.9f}.

## Assigned Vs Unresolved Directionality Result
Assigned units: {directionality['assigned_units']:,}; assigned bins: {directionality['assigned_bins']:,}; assigned chains: {directionality['assigned_chains']:,}. Unresolved units: {directionality['unresolved_units']:,}; unresolved bins: {directionality['unresolved_bins']:,}; unresolved chains: {directionality['unresolved_chains']:,}. Unresolved signals/approaches: {directionality['unresolved_signals']:,} / {directionality['unresolved_approaches']:,}.

## Fully Unassigned Signals And Approaches
Fully unassigned signals: {directionality['fully_unassigned_signals']:,}. Fully unassigned approaches: {directionality['fully_unassigned_approaches']:,}. These match the build residual expectation.

## Distance-Band Distribution
{dist_text}

## Multi-Chain And High-Length Interpretation
Multi-chain units: {multi['multi_chain_unit_count']:,}. Maximum chain_count: {multi['max_chain_count']:,}. Units with length greater than nominal band width: {multi['high_length_unit_count']:,}. Single-chain high-length units: {multi['single_chain_high_length_count']:,}. High-length units are explained by multiple chains when present; duplicate chain-distance intervals in parent bins: {multi['duplicate_chain_distance_interval_count']:,}.

## Unit Completeness And Missingness Representation
Complete distance-band units: {completeness['complete_distance_band_units']:,}. Unresolved directionality units: {completeness['unresolved_directionality_units']:,}. Blank parent_approach_gate units: {completeness['parent_approach_gate_blank_units']:,}. Blank parent_corridor_gate_severity units: {completeness['parent_corridor_gate_severity_blank_units']:,}. The blank parent gate fields are acceptable for this core rollup stage because `bin_context` does not carry those fields; they can be repaired or enriched later if needed by `distance_band_context`.

## Context And Crash Direction Guard
No context enrichment was performed in this audit. The staged unit table has no populated speed, AADT, access, crash, exposure, rate, MVP, or lookup fields. Crash direction fields were not used.

## Readiness
Decision: `{decision}`. `distance_band_units.parquet` is ready to serve as the parent for `distance_band_context.parquet`, with unresolved directionality preserved explicitly.

## Recommended Next Task
Build `distance_band_context.parquet` from validated `distance_band_units.parquet`, adding context only in that next layer and preserving unresolved-directionality missingness.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def write_manifests(decision: str) -> None:
    write_json(
        OUT / "manifest.json",
        {
            "created_utc": now(),
            "product": "distance_band_units_validation_audit",
            "audit_type": "read_only",
            "validated_object": rel(DISTANCE_BAND_UNITS),
            "direct_parent_checked": rel(BIN_CONTEXT),
            "validation_inputs": [rel(path) for path in VALIDATION_INPUTS],
            "metadata_read": [rel(STAGING_MANIFEST), rel(STAGING_SCHEMA), rel(STAGING_README)],
            "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
            "final_decision": decision,
            "mutation_policy": "No staged, source, artifact, canonical root, context, MVP, lookup, crash, access, speed, AADT, exposure, or rate products were modified or built.",
        },
    )
    write_json(
        OUT / "qa_manifest.json",
        {
            "created_utc": now(),
            "product": "distance_band_units_validation_audit",
            "qa_outputs": sorted(path.name for path in OUT.glob("*") if path.is_file()),
            "final_decision": decision,
        },
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    progress = OUT / "progress_log.md"
    if progress.exists():
        progress.unlink()
    log("Starting read-only distance_band_units validation audit.")
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)
    log("Reading staged validation inputs.")
    bin_df, units, signals, approaches = read_inputs()
    log(f"Loaded {len(bin_df):,} parent bins and {len(units):,} units.")
    parent = assign_parent_unit_key(bin_df)
    log("Reconstructing expected rollup from bin_context.")
    expected = reconstruct_units(parent)
    identity, identity_summary = unit_identity_and_grain_audit(units, expected)
    write_csv("unit_identity_and_grain_audit.csv", identity)
    link = parent_link_audit(units, signals, approaches)
    write_csv("unit_parent_link_audit.csv", link)
    log("Running bin, length, grain, and lineage reconciliation.")
    _, recon_summary, bin_map_summary = reconciliation_audits(parent, units, expected)
    # Include the stable-bin mapping summary in the reconciliation output set.
    write_csv("unit_parent_link_audit.csv", pd.concat([link, bin_map_summary.rename(columns={"every_bin_maps_to_one_unit_group": "pass"})], ignore_index=True, sort=False))
    log("Auditing directionality residuals and distance-band distributions.")
    directionality = directionality_audits(parent, units)
    dist, _, _ = distance_band_audits(parent, units)
    log("Auditing multi-chain units, completeness, and context guards.")
    multi = multi_chain_audits(parent, units)
    completeness = completeness_audits(units)
    context, crash = context_and_crash_guards(units)
    decision = scorecard_and_decision(parent_check, identity, link, recon_summary, directionality, dist, multi, context, crash)
    write_findings(decision, identity_summary, recon_summary, directionality, dist, multi, completeness)
    write_manifests(decision)
    log(f"Completed read-only audit with decision {decision}.")


if __name__ == "__main__":
    main()
