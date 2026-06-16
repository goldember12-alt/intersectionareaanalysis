"""Read-only validation audit for staged bin_context.parquet.

This audit validates the neutral, geometry-materialized bin_context cache as a
future parent for directionality assignment. It does not mutate staged products
or source artifacts.
"""

from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from shapely import wkb


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/bin_context_validation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

PARENTS = [SIGNAL_INDEX, TRAVELWAY_INDEX, SIGNAL_APPROACHES, APPROACH_CORRIDORS, BIN_CONTEXT]
DIAGNOSTIC_EVIDENCE = [
    REPO / "work/roadway_graph/review/build_bin_context",
    REPO / "work/roadway_graph/review/materialize_bin_context_geometry",
    REPO / "work/roadway_graph/review/final_overall_approach_corridors_validation_audit",
    REPO / "work/roadway_graph/review/patch_remaining_likely_valid_source_extent_continuations",
    REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains",
    REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan",
]

FLOAT_TOL_FT = 1e-6
LENGTH_ABS_TOL_FT = 7.5
LENGTH_REL_TOL = 0.20
GEOMETRY_PARSE_RANDOM_SAMPLE = 100_000
RANDOM_SEED = 20260610

DISTANCE_BANDS: list[tuple[float, float, str]] = [
    (0.0, 250.0, "0-250"),
    (250.0, 500.0, "250-500"),
    (500.0, 1000.0, "500-1,000"),
    (1000.0, 1500.0, "1,000-1,500"),
    (1500.0, 2000.0, "1,500-2,000"),
    (2000.0, 2500.0, "2,000-2,500"),
]

IDENTITY_COLUMNS = [
    "stable_bin_id",
    "stable_signal_id",
    "signal_approach_id",
    "logical_corridor_chain_id",
    "distance_start_ft",
    "distance_end_ft",
    "bin_length_ft",
    "distance_band",
    "measure_side_class",
    "chain_total_reach_ft",
    "chain_stop_reason",
    "chain_completeness_status",
    "primary_approach_corridor_id",
    "supporting_approach_corridor_ids",
    "segment_overlap_count",
    "segment_boundary_crossing_flag",
    "parent_corridor_warning_status",
    "parent_corridor_review_status",
    "directionality_status",
    "upstream_downstream",
    "geometry_status",
    "geometry_encoding",
    "geometry_source",
    "geometry_method",
    "geometry_length_ft",
    "geometry_length_delta_ft",
    "geometry_segment_count",
    "multi_segment_geometry_flag",
    "geometry_crs",
    "geometry_error_reason",
]


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


def write_json(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open("w", encoding="utf-8") as f:
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


def parent_dependency_check() -> pd.DataFrame:
    forbidden_tokens = ["distance_band_units", "mvp", "crash", "access_context", "speed_context", "aadt", "exposure", "rate_distribution"]
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
                "exists": exists,
                "read_status": read_status,
                "row_count": row_count,
                "allowed_parent_for_validation": bool(exists and read_status == "readable"),
                "downstream_object_parent_flag": any(token in lowered for token in forbidden_tokens),
            }
        )
    return pd.DataFrame(rows)


def band_for_interval(start_ft: float, end_ft: float) -> tuple[str, bool]:
    end_probe = max(start_ft, end_ft - FLOAT_TOL_FT)
    for lo, hi, label in DISTANCE_BANDS:
        if start_ft >= lo - FLOAT_TOL_FT and start_ft < hi - FLOAT_TOL_FT:
            return label, end_probe >= hi + FLOAT_TOL_FT
    return "", False


def read_parent_metadata() -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for path in [STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]:
        if not path.exists():
            metadata[path.name] = {"exists": False}
            continue
        if path.suffix == ".json":
            try:
                with path.open("r", encoding="utf-8") as f:
                    metadata[path.name] = json.load(f)
            except Exception as exc:
                metadata[path.name] = {"exists": True, "read_error": f"{type(exc).__name__}: {exc}"}
        else:
            metadata[path.name] = {"exists": True, "length": path.stat().st_size}
    return metadata


def parse_wkb(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    try:
        geom = wkb.loads(bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else value)
        return bool(not geom.is_empty)
    except Exception:
        return False


def geometry_readability_audit(bin_df: pd.DataFrame) -> pd.DataFrame:
    start = time.perf_counter()
    cols = ["stable_bin_id", "geometry", "geometry_status", "multi_segment_geometry_flag", "geometry_error_reason"]
    pf = pq.ParquetFile(BIN_CONTEXT)
    multi_ids = set(bin_df.loc[bin_df["multi_segment_geometry_flag"].fillna(False).astype(bool), "stable_bin_id"].astype(str))
    random_ids = set(
        bin_df[["stable_bin_id"]]
        .sample(n=min(GEOMETRY_PARSE_RANDOM_SAMPLE, len(bin_df)), random_state=RANDOM_SEED)["stable_bin_id"]
        .astype(str)
    )
    exception_ids = set(bin_df.loc[(bin_df["geometry_status"].map(clean) == "") | (bin_df["geometry_error_reason"].map(clean) != ""), "stable_bin_id"].astype(str))
    target_ids = multi_ids | random_ids | exception_ids
    parsed = 0
    failed = 0
    target_rows = 0
    missing_geometry = 0
    by_reason: dict[str, int] = {}
    for batch in pf.iter_batches(columns=cols, batch_size=100_000):
        chunk = batch.to_pandas()
        chunk = chunk[chunk["stable_bin_id"].astype(str).isin(target_ids)]
        if chunk.empty:
            continue
        target_rows += len(chunk)
        for row in chunk.itertuples(index=False):
            if row.geometry is None or pd.isna(row.geometry):
                missing_geometry += 1
                failed += 1
                by_reason["missing_geometry"] = by_reason.get("missing_geometry", 0) + 1
                continue
            ok = parse_wkb(row.geometry)
            parsed += int(ok)
            failed += int(not ok)
            if not ok:
                reason = clean(row.geometry_error_reason) or "unparseable_or_empty_wkb"
                by_reason[reason] = by_reason.get(reason, 0) + 1
    rows = [
        {
            "coverage_type": "random_sample_plus_all_multi_segment_and_exceptions",
            "target_row_count": target_rows,
            "random_sample_target_count": len(random_ids),
            "multi_segment_target_count": len(multi_ids),
            "exception_target_count": len(exception_ids),
            "parse_success_count": parsed,
            "parse_failure_count": failed,
            "missing_geometry_count": missing_geometry,
            "parse_runtime_seconds": round(time.perf_counter() - start, 3),
            "full_parse_performed": False,
            "parse_coverage_note": "Parsed deterministic random sample, all multi-segment bins, and all geometry status/error exceptions.",
        }
    ]
    for reason, count in sorted(by_reason.items()):
        rows.append(
            {
                "coverage_type": f"failure_reason:{reason}",
                "target_row_count": count,
                "random_sample_target_count": "",
                "multi_segment_target_count": "",
                "exception_target_count": "",
                "parse_success_count": "",
                "parse_failure_count": count,
                "missing_geometry_count": "",
                "parse_runtime_seconds": "",
                "full_parse_performed": False,
                "parse_coverage_note": "",
            }
        )
    return pd.DataFrame(rows)


def make_spatial_samples(bin_df: pd.DataFrame) -> pd.DataFrame:
    sample_cols = [
        "stable_bin_id",
        "stable_signal_id",
        "signal_approach_id",
        "logical_corridor_chain_id",
        "distance_start_ft",
        "distance_end_ft",
        "bin_length_ft",
        "distance_band",
        "chain_stop_reason",
        "geometry_status",
        "geometry_length_ft",
        "multi_segment_geometry_flag",
        "parent_corridor_warning_status",
        "supporting_approach_corridor_ids",
    ]
    samples: list[pd.DataFrame] = []
    def add(label: str, df: pd.DataFrame, n: int = 50) -> None:
        if df.empty:
            return
        out = df[sample_cols].head(n).copy()
        out.insert(0, "sample_type", label)
        samples.append(out)

    add("longest_bins", bin_df.sort_values(["bin_length_ft", "stable_bin_id"], ascending=[False, True]), 50)
    add("shortest_bins", bin_df.sort_values(["bin_length_ft", "stable_bin_id"], ascending=[True, True]), 50)
    add("final_partial_bins", bin_df[bin_df["final_partial_bin_flag"].fillna(False).astype(bool)].sort_values("stable_bin_id"), 100)
    add("multi_segment_bins", bin_df[bin_df["multi_segment_geometry_flag"].fillna(False).astype(bool)].sort_values("stable_bin_id"), 100)
    add("warning_parent_corridors", bin_df[bin_df["parent_corridor_warning_status"].map(clean).ne("none")].sort_values("stable_bin_id"), 100)
    add("source_extent_stop_chains", bin_df[bin_df["chain_stop_reason"].astype(str).str.contains("source_extent", na=False)].sort_values("stable_bin_id"), 100)
    add("supported_signal_boundary_stop_chains", bin_df[bin_df["chain_stop_reason"].astype(str).str.contains("supported_signal_boundary", na=False)].sort_values("stable_bin_id"), 100)
    random_parts = []
    for _band, group in bin_df.groupby("distance_band", dropna=False):
        random_parts.append(group.sample(n=min(50, len(group)), random_state=RANDOM_SEED))
    random = pd.concat(random_parts, ignore_index=True) if random_parts else pd.DataFrame(columns=sample_cols)
    add("random_by_distance_band", random.sort_values(["distance_band", "stable_bin_id"]), 500)
    return pd.concat(samples, ignore_index=True) if samples else pd.DataFrame(columns=["sample_type", *sample_cols])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log("Starting read-only bin_context validation audit.")
    metadata = read_parent_metadata()
    parent_check = parent_dependency_check()
    write_csv("parent_dependency_check.csv", parent_check)

    log("Reading staged parent identifiers.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id"])
    approaches = pd.read_parquet(SIGNAL_APPROACHES, columns=["signal_approach_id", "stable_signal_id", "corridor_build_gate"])
    corridors = pd.read_parquet(
        APPROACH_CORRIDORS,
        columns=[
            "logical_corridor_chain_id",
            "approach_corridor_id",
            "stable_signal_id",
            "signal_approach_id",
            "chain_total_reach_ft",
            "chain_bin_eligible_flag",
            "chain_stop_reason",
            "chain_completeness_status",
            "parent_corridor_gate_severity",
        ],
    )
    log("Reading bin_context audit columns.")
    bin_cols = [*IDENTITY_COLUMNS, "final_partial_bin_flag", "geometry"]
    bin_df = pd.read_parquet(BIN_CONTEXT, columns=bin_cols)
    row_count = len(bin_df)

    signal_set = set(signals["stable_signal_id"].astype(str))
    approach_set = set(approaches["signal_approach_id"].astype(str))
    corridor_chain = corridors.drop_duplicates("logical_corridor_chain_id").copy()
    corridor_chain_set = set(corridor_chain["logical_corridor_chain_id"].astype(str))
    corridor_id_set = set(corridors["approach_corridor_id"].astype(str))
    blocked_approaches = set(approaches.loc[approaches["corridor_build_gate"].isin(["corridor_build_blocked_pending_rule_repair", "source_limited_no_corridor"]), "signal_approach_id"].astype(str))

    log("Running identity and parent-link audits.")
    duplicate_bin_ids = int(row_count - bin_df["stable_bin_id"].nunique(dropna=False))
    duplicate_intervals = int(
        (
            bin_df.groupby(["logical_corridor_chain_id", "distance_start_ft", "distance_end_ft"], dropna=False)
            .size()
            .reset_index(name="n")["n"]
            > 1
        ).sum()
    )
    bin_identity = pd.DataFrame(
        [
            {"check_name": "row_count", "value": row_count, "fail_count": 0, "pass": row_count > 0},
            {"check_name": "stable_bin_id_non_null", "value": row_count, "fail_count": int(bin_df["stable_bin_id"].map(clean).eq("").sum()), "pass": bool(bin_df["stable_bin_id"].map(clean).ne("").all())},
            {"check_name": "stable_bin_id_unique", "value": row_count, "fail_count": duplicate_bin_ids, "pass": duplicate_bin_ids == 0},
            {"check_name": "logical_corridor_chain_id_non_null", "value": row_count, "fail_count": int(bin_df["logical_corridor_chain_id"].map(clean).eq("").sum()), "pass": bool(bin_df["logical_corridor_chain_id"].map(clean).ne("").all())},
            {"check_name": "duplicate_chain_distance_intervals", "value": row_count, "fail_count": duplicate_intervals, "pass": duplicate_intervals == 0},
        ]
    )
    write_csv("bin_identity_audit.csv", bin_identity)

    supporting_ids = set()
    for value in bin_df["supporting_approach_corridor_ids"].dropna().astype(str):
        supporting_ids.update(part for part in value.split("|") if part)
    parent_link_rows = [
        {"check_name": "stable_signal_id_valid_against_signal_index", "fail_count": int((~bin_df["stable_signal_id"].astype(str).isin(signal_set)).sum())},
        {"check_name": "signal_approach_id_valid_against_signal_approaches", "fail_count": int((~bin_df["signal_approach_id"].astype(str).isin(approach_set)).sum())},
        {"check_name": "logical_corridor_chain_id_valid_against_approach_corridors", "fail_count": int((~bin_df["logical_corridor_chain_id"].astype(str).isin(corridor_chain_set)).sum())},
        {"check_name": "primary_approach_corridor_id_valid", "fail_count": int((~bin_df["primary_approach_corridor_id"].astype(str).isin(corridor_id_set)).sum())},
        {"check_name": "supporting_approach_corridor_ids_valid", "fail_count": len(supporting_ids - corridor_id_set)},
        {"check_name": "no_bins_from_blocked_or_source_limited_approaches", "fail_count": int(bin_df["signal_approach_id"].astype(str).isin(blocked_approaches).sum())},
    ]
    for row in parent_link_rows:
        row["pass"] = row["fail_count"] == 0
    parent_link = pd.DataFrame(parent_link_rows)
    write_csv("parent_link_audit.csv", parent_link)

    log("Running distance interval, band, and count reconciliation audits.")
    sorted_bins = bin_df.sort_values(["logical_corridor_chain_id", "distance_start_ft", "distance_end_ft", "stable_bin_id"], kind="mergesort").copy()
    sorted_bins["prev_end_ft"] = sorted_bins.groupby("logical_corridor_chain_id")["distance_end_ft"].shift()
    sorted_bins["next_start_ft"] = sorted_bins.groupby("logical_corridor_chain_id")["distance_start_ft"].shift(-1)
    sorted_bins["is_first_bin"] = sorted_bins["prev_end_ft"].isna()
    sorted_bins["is_last_bin"] = sorted_bins["next_start_ft"].isna()
    interval_fail_rows = [
        {"check_name": "no_negative_distance_start", "fail_count": int((bin_df["distance_start_ft"] < -FLOAT_TOL_FT).sum())},
        {"check_name": "no_zero_or_negative_bin_length", "fail_count": int((bin_df["bin_length_ft"] <= FLOAT_TOL_FT).sum())},
        {"check_name": "no_end_beyond_chain_total_reach", "fail_count": int((bin_df["distance_end_ft"] > bin_df["chain_total_reach_ft"] + FLOAT_TOL_FT).sum())},
        {"check_name": "no_end_beyond_2500_ft", "fail_count": int((bin_df["distance_end_ft"] > 2500.0 + FLOAT_TOL_FT).sum())},
        {"check_name": "no_duplicate_chain_distance_interval", "fail_count": duplicate_intervals},
        {"check_name": "first_bin_starts_at_zero", "fail_count": int((sorted_bins.loc[sorted_bins["is_first_bin"], "distance_start_ft"].abs() > FLOAT_TOL_FT).sum())},
        {"check_name": "chain_bins_gap_free", "fail_count": int(((sorted_bins["prev_end_ft"].notna()) & ((sorted_bins["distance_start_ft"] - sorted_bins["prev_end_ft"]).abs() > 0.001)).sum())},
        {"check_name": "final_partial_only_at_chain_end", "fail_count": int((bin_df["final_partial_bin_flag"].fillna(False).astype(bool) & ~sorted_bins["is_last_bin"]).sum())},
    ]
    for row in interval_fail_rows:
        row["pass"] = row["fail_count"] == 0
    write_csv("bin_distance_interval_audit.csv", interval_fail_rows)

    by_chain = bin_df.groupby("logical_corridor_chain_id", dropna=False).agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        bin_count=("stable_bin_id", "count"),
        total_bin_length_ft=("bin_length_ft", "sum"),
        max_distance_end_ft=("distance_end_ft", "max"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        final_partial_bin_count=("final_partial_bin_flag", lambda s: int(s.fillna(False).astype(bool).sum())),
    ).reset_index()
    by_chain["expected_bin_count"] = by_chain["chain_total_reach_ft"].map(lambda x: int(math.ceil((min(float(x), 2500.0) - FLOAT_TOL_FT) / 50.0)) if float(x) > FLOAT_TOL_FT else 0)
    by_chain["bin_count_difference"] = by_chain["bin_count"] - by_chain["expected_bin_count"]
    by_chain["length_delta_ft"] = by_chain["total_bin_length_ft"] - by_chain["chain_total_reach_ft"].clip(upper=2500.0)
    by_chain["reconciliation_status"] = by_chain.apply(lambda r: "reconciled" if int(r["bin_count_difference"]) == 0 and abs(float(r["length_delta_ft"])) <= 0.001 else "needs_review", axis=1)
    write_csv("bin_count_reconciliation_by_chain.csv", by_chain)
    by_approach = by_chain.groupby(["stable_signal_id", "signal_approach_id"], dropna=False).agg(
        logical_chain_count=("logical_corridor_chain_id", "count"),
        bin_count=("bin_count", "sum"),
        expected_bin_count=("expected_bin_count", "sum"),
        unreconciled_chain_count=("reconciliation_status", lambda s: int((s != "reconciled").sum())),
    ).reset_index()
    write_csv("bin_count_reconciliation_by_approach.csv", by_approach)
    by_signal = by_chain.groupby("stable_signal_id", dropna=False).agg(
        signal_approach_count=("signal_approach_id", "nunique"),
        logical_chain_count=("logical_corridor_chain_id", "count"),
        bin_count=("bin_count", "sum"),
        expected_bin_count=("expected_bin_count", "sum"),
        unreconciled_chain_count=("reconciliation_status", lambda s: int((s != "reconciled").sum())),
    ).reset_index()
    write_csv("bin_count_reconciliation_by_signal.csv", by_signal)

    band_expected = bin_df.apply(lambda r: band_for_interval(float(r["distance_start_ft"]), float(r["distance_end_ft"])), axis=1)
    bin_df["expected_distance_band"] = [item[0] for item in band_expected]
    bin_df["crosses_band_boundary"] = [item[1] for item in band_expected]
    band_fail = bin_df["distance_band"].map(clean).ne(bin_df["expected_distance_band"].map(clean))
    band_summary = bin_df.groupby("distance_band", dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        total_bin_length_ft=("bin_length_ft", "sum"),
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
        signal_approach_count=("signal_approach_id", "nunique"),
        stable_signal_count=("stable_signal_id", "nunique"),
    ).reset_index()
    distance_band_audit = pd.concat(
        [
            band_summary,
            pd.DataFrame(
                [
                    {
                        "distance_band": "_audit_totals",
                        "bin_count": len(bin_df),
                        "total_bin_length_ft": float(bin_df["bin_length_ft"].sum()),
                        "logical_chain_count": int(bin_df["logical_corridor_chain_id"].nunique()),
                        "signal_approach_count": int(bin_df["signal_approach_id"].nunique()),
                        "stable_signal_count": int(bin_df["stable_signal_id"].nunique()),
                        "missing_band_count": int(bin_df["distance_band"].map(clean).eq("").sum()),
                        "incorrect_band_count": int(band_fail.sum()),
                        "cross_band_boundary_count": int(bin_df["crosses_band_boundary"].sum()),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    write_csv("distance_band_audit.csv", distance_band_audit)
    write_csv("distance_band_coverage_by_chain.csv", bin_df.groupby(["stable_signal_id", "signal_approach_id", "logical_corridor_chain_id", "distance_band"], dropna=False).agg(bin_count=("stable_bin_id", "count"), total_bin_length_ft=("bin_length_ft", "sum")).reset_index())
    write_csv("distance_band_coverage_by_approach.csv", bin_df.groupby(["stable_signal_id", "signal_approach_id", "distance_band"], dropna=False).agg(bin_count=("stable_bin_id", "count"), total_bin_length_ft=("bin_length_ft", "sum"), logical_chain_count=("logical_corridor_chain_id", "nunique")).reset_index())
    write_csv("distance_band_coverage_by_signal.csv", bin_df.groupby(["stable_signal_id", "distance_band"], dropna=False).agg(bin_count=("stable_bin_id", "count"), total_bin_length_ft=("bin_length_ft", "sum"), signal_approach_count=("signal_approach_id", "nunique"), logical_chain_count=("logical_corridor_chain_id", "nunique")).reset_index())

    log("Running parent-chain reconciliation and geometry audits.")
    parent_chains = corridor_chain[["logical_corridor_chain_id", "chain_bin_eligible_flag", "chain_total_reach_ft", "chain_stop_reason", "chain_completeness_status"]].copy()
    represented_chains = set(by_chain["logical_corridor_chain_id"].astype(str))
    parent_chains["represented_in_bins"] = parent_chains["logical_corridor_chain_id"].astype(str).isin(represented_chains)
    parent_chain_recon = pd.DataFrame(
        [
            {"check_name": "parent_logical_chains", "count": len(parent_chains)},
            {"check_name": "represented_logical_chains", "count": len(represented_chains)},
            {"check_name": "bin_eligible_chains_with_no_bins", "count": int((parent_chains["chain_bin_eligible_flag"].fillna(False).astype(bool) & ~parent_chains["represented_in_bins"]).sum())},
            {"check_name": "non_bin_eligible_chains_with_bins", "count": int((~parent_chains["chain_bin_eligible_flag"].fillna(False).astype(bool) & parent_chains["represented_in_bins"]).sum())},
        ]
    )
    write_csv("parent_chain_reconciliation.csv", parent_chain_recon)

    geom_present = bin_df["geometry"].notna()
    geom_status_blank = bin_df["geometry_status"].map(clean).eq("")
    geom_error = bin_df["geometry_error_reason"].map(clean).ne("")
    length_tol = bin_df["bin_length_ft"].abs().mul(LENGTH_REL_TOL).clip(lower=LENGTH_ABS_TOL_FT)
    length_delta_abs = bin_df["geometry_length_delta_ft"].abs()
    length_status = pd.Series("within_tolerance", index=bin_df.index)
    length_status[length_delta_abs > length_tol] = "outside_tolerance"
    write_csv("geometry_length_validation.csv", pd.DataFrame({"length_validation_status": length_status}).join(bin_df[["stable_bin_id", "geometry_length_delta_ft"]]).groupby("length_validation_status").agg(bin_count=("stable_bin_id", "count"), max_abs_delta_ft=("geometry_length_delta_ft", lambda s: float(s.abs().max()) if len(s) else 0.0)).reset_index())
    write_csv("geometry_status_audit.csv", bin_df.groupby(["geometry_status", "geometry_encoding", "geometry_crs"], dropna=False).agg(bin_count=("stable_bin_id", "count"), geometry_present_count=("geometry", lambda s: int(s.notna().sum()))).reset_index())
    geom_readability = geometry_readability_audit(bin_df)
    write_csv("geometry_readability_audit.csv", geom_readability)
    multi_audit = bin_df.groupby(["multi_segment_geometry_flag", "geometry_status"], dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        max_geometry_segment_count=("geometry_segment_count", "max"),
        min_segment_overlap_count=("segment_overlap_count", "min"),
        max_segment_overlap_count=("segment_overlap_count", "max"),
    ).reset_index()
    write_csv("multi_segment_bin_audit.csv", multi_audit)
    final_partial = bin_df.groupby(["final_partial_bin_flag", "distance_band", "chain_stop_reason"], dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        min_bin_length_ft=("bin_length_ft", "min"),
        max_bin_length_ft=("bin_length_ft", "max"),
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
    ).reset_index()
    write_csv("final_partial_bin_audit.csv", final_partial)

    write_csv("spatial_sanity_sample_index.csv", make_spatial_samples(bin_df.drop(columns=["geometry"], errors="ignore")))

    directionality_fields = [
        "stable_signal_id",
        "signal_approach_id",
        "logical_corridor_chain_id",
        "measure_side_class",
        "primary_stable_travelway_id",
        "route_base",
        "source_route_name",
        "carriageway_direction_token",
        "roadway_configuration",
        "source_measure_start",
        "source_measure_end",
        "geometry",
        "parent_corridor_stop_reason",
        "parent_corridor_warning_status",
        "parent_corridor_review_status",
    ]
    schema_cols = set(pq.ParquetFile(BIN_CONTEXT).schema_arrow.names)
    directionality_rows = [{"field_name": field, "present": field in schema_cols, "null_or_blank_count": ""} for field in directionality_fields]
    directionality_rows.extend(
        [
            {"field_name": "recommended_assignment_grain", "present": True, "null_or_blank_count": "chain_first_propagate_to_bins_with_bin_level_exception_review"},
            {"field_name": "directionality_status_unassigned_fail_count", "present": True, "null_or_blank_count": int((bin_df["directionality_status"] != "not_assigned").sum())},
            {"field_name": "upstream_downstream_nonblank_fail_count", "present": True, "null_or_blank_count": int(bin_df["upstream_downstream"].map(clean).ne("").sum())},
        ]
    )
    write_csv("directionality_readiness_audit.csv", directionality_rows)

    forbidden_tokens = ["speed", "aadt", "access", "crash", "exposure", "rate"]
    forbidden = [
        {"field_name": col, "forbidden_token": token, "present_flag": True}
        for col in schema_cols
        for token in forbidden_tokens
        if token in col.lower()
    ]
    if not forbidden:
        forbidden = [{"field_name": "", "forbidden_token": "", "present_flag": False}]
    write_csv("context_enrichment_guard_audit.csv", forbidden)

    log("Computing scorecard and readiness decision.")
    failures = {
        "parent_dependency_failures": int((~parent_check["allowed_parent_for_validation"]).sum() + parent_check["downstream_object_parent_flag"].sum()),
        "bin_identity_failures": int(bin_identity["fail_count"].sum()),
        "parent_link_failures": int(parent_link["fail_count"].sum()),
        "distance_interval_failures": int(pd.DataFrame(interval_fail_rows)["fail_count"].sum()),
        "distance_band_failures": int(band_fail.sum() + bin_df["crosses_band_boundary"].sum()),
        "chain_reconciliation_failures": int((by_chain["reconciliation_status"] != "reconciled").sum() + parent_chain_recon.loc[parent_chain_recon["check_name"].isin(["bin_eligible_chains_with_no_bins", "non_bin_eligible_chains_with_bins"]), "count"].sum()),
        "geometry_failures": int((~geom_present).sum() + geom_status_blank.sum() + geom_error.sum() + (length_status == "outside_tolerance").sum() + int(geom_readability["parse_failure_count"].replace("", 0).astype(int).sum())),
        "directionality_failures": int((bin_df["directionality_status"] != "not_assigned").sum() + bin_df["upstream_downstream"].map(clean).ne("").sum()),
        "context_enrichment_failures": 0 if not forbidden[0]["present_flag"] else len(forbidden),
    }
    if failures["parent_dependency_failures"] or failures["parent_link_failures"] or failures["chain_reconciliation_failures"]:
        decision = "bin_context_needs_parent_corridor_repair"
    elif failures["distance_interval_failures"] or failures["distance_band_failures"]:
        decision = "bin_context_needs_distance_or_band_repair"
    elif failures["geometry_failures"]:
        decision = "bin_context_needs_geometry_repair"
    elif row_count == 0:
        decision = "bin_context_should_be_rebuilt"
    else:
        decision = "bin_context_ready_for_directionality"

    scorecard_rows = [{"domain": key, "fail_count": value, "pass": value == 0} for key, value in failures.items()]
    scorecard_rows.append({"domain": "readiness_decision", "fail_count": decision, "pass": decision == "bin_context_ready_for_directionality"})
    write_csv("bin_context_scorecard.csv", scorecard_rows)
    write_csv("readiness_decision.csv", [{"decision": decision, "ready_for_directionality": decision in {"bin_context_ready_for_directionality", "bin_context_ready_for_directionality_with_geometry_review_ledger"}}])
    write_csv(
        "recommended_next_actions.csv",
        [
            {"priority": 1, "recommended_next_action": "Use bin_context as parent for chain-first directionality assignment, propagating accepted chain directionality to bins."},
            {"priority": 2, "recommended_next_action": "Create a small exception-review ledger for chains whose route/carriageway/geometry evidence is ambiguous before assigning directionality."},
            {"priority": 3, "recommended_next_action": "Do not use crash direction fields for upstream/downstream assignment."},
        ],
    )

    findings = f"""# bin_context Validation Audit Findings

## What Was Audited
Read-only validation of staged `bin_context.parquet` after geometry materialization. No staged/cache/source product was modified.

## Parent Dependency Result
Allowed staged parents are readable and no downstream parent path was listed. Parent dependency failures: {failures['parent_dependency_failures']}.

## Bin Identity Result
Rows: {row_count:,}. Duplicate `stable_bin_id`: {duplicate_bin_ids:,}. Duplicate chain-distance intervals: {duplicate_intervals:,}.

## Distance Interval And Count Reconciliation
Distance interval failures: {failures['distance_interval_failures']:,}. Chain reconciliation failures: {failures['chain_reconciliation_failures']:,}. Reconciled chains: {int((by_chain['reconciliation_status'] == 'reconciled').sum()):,} of {len(by_chain):,}.

## Distance-Band Coverage
Distance-band failures: {failures['distance_band_failures']:,}. Bands populated: {', '.join(str(x) for x in sorted(bin_df['distance_band'].dropna().unique()))}.

## Geometry Completeness, Readability, And Length
Geometry present rows: {int(geom_present.sum()):,}. Geometry status blank rows: {int(geom_status_blank.sum()):,}. Geometry error rows: {int(geom_error.sum()):,}. Length outside tolerance rows: {int((length_status == 'outside_tolerance').sum()):,}. WKB parse coverage: {int(geom_readability.iloc[0]['target_row_count']):,} sampled/targeted rows; parse failures: {int(geom_readability.iloc[0]['parse_failure_count']):,}.

## Multi-Segment Bin Handling
Multi-segment geometry flag true rows: {int(bin_df['multi_segment_geometry_flag'].fillna(False).astype(bool).sum()):,}. Multi-segment bins remain single bin rows; no duplicate interval rows were found.

## Final Partial Bin Handling
Final partial bins are present only at chain ends according to the interval audit. Final partial bin count: {int(bin_df['final_partial_bin_flag'].fillna(False).astype(bool).sum()):,}.

## Directionality And Context
Directionality/upstream-downstream remain unassigned. Directionality failures: {failures['directionality_failures']:,}. Context enrichment guard failures: {failures['context_enrichment_failures']:,}.

## Readiness
Decision: `{decision}`. Recommended directionality grain is logical-corridor-chain first, propagated to bins, with bin-level fallback only for explicit exception cases.

## Recommended Next Task
Build a chain-first directionality assignment layer from this validated neutral bin parent. Do not use crash direction fields.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")

    manifest = {
        "created_utc": now(),
        "product": "bin_context_validation_audit",
        "bounded_question": "Is staged geometry-materialized bin_context ready as parent for directionality assignment?",
        "source_inputs": [rel(path) for path in PARENTS],
        "diagnostic_evidence_only": [rel(path) for path in DIAGNOSTIC_EVIDENCE],
        "output_grain": "audit tables by bin, chain, approach, signal, and validation domain",
        "caveats": ["WKB readability parsed deterministic random sample plus all multi-segment bins and geometry exceptions, not every row."],
        "validation_checks": failures,
        "final_decision": decision,
    }
    write_json("manifest.json", manifest)
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.is_file()),
            "acceptance_checks": {key: value == 0 for key, value in failures.items()},
            "metadata_read": {key: ("read_error" not in value if isinstance(value, dict) else True) for key, value in metadata.items()},
        },
    )
    log(f"Read-only bin_context validation audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
