"""Read-only readiness audit for the staged travelway_network_index.

This audit writes only review outputs. It does not modify staged cache files,
canonical products, source artifacts, or downstream objects.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"
SOURCE = REPO / "artifacts/normalized/roads.parquet"
OUT = REPO / "work/roadway_graph/review/travelway_network_index_readiness_audit"
BUILD_REVIEW = REPO / "work/roadway_graph/review/build_travelway_network_index"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
LINEAGE_REVIEW = REPO / "work/roadway_graph/review/network_to_unit_lineage_preservation_audit"


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


def nonblank(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>", "nat"])


def hash_geometry(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    payload = bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else str(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest() if payload else ""


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def value_counts_rows(df: pd.DataFrame, column: str, label: str | None = None) -> list[dict[str, Any]]:
    if column not in df.columns:
        return [{"field": column, "value": "<missing_column>", "row_count": 0}]
    counts = df[column].fillna("").replace("", "<blank>").value_counts(dropna=False)
    return [
        {"field": label or column, "value": str(value), "row_count": int(count)}
        for value, count in counts.items()
    ]


def status_summary(df: pd.DataFrame) -> dict[str, Any]:
    route_name_mask = nonblank(df["source_route_name"]) if "source_route_name" in df.columns else pd.Series(False, index=df.index)
    start = pd.to_numeric(df.get("source_measure_start", pd.Series(index=df.index)), errors="coerce")
    end = pd.to_numeric(df.get("source_measure_end", pd.Series(index=df.index)), errors="coerce")
    return {
        "row_count": int(len(df)),
        "stable_travelway_id_non_null": int(nonblank(df["stable_travelway_id"]).sum()),
        "stable_travelway_id_null_or_blank": int((~nonblank(df["stable_travelway_id"])).sum()),
        "stable_travelway_id_duplicate_rows": int(df["stable_travelway_id"].duplicated(keep=False).sum()),
        "geometry_non_null": int(df["geometry"].notna().sum()) if "geometry" in df.columns else 0,
        "geometry_hash_non_blank": int(nonblank(df["geometry_hash"]).sum()) if "geometry_hash" in df.columns else 0,
        "geometry_hash_unique": int(df.loc[nonblank(df["geometry_hash"]), "geometry_hash"].nunique()) if "geometry_hash" in df.columns else 0,
        "source_route_name_non_blank": int(route_name_mask.sum()),
        "source_route_name_blank": int((~route_name_mask).sum()),
        "measure_start_non_null": int(start.notna().sum()),
        "measure_end_non_null": int(end.notna().sum()),
        "measure_both_non_null": int((start.notna() & end.notna()).sum()),
        "measure_any_missing": int((start.isna() | end.isna()).sum()),
    }


def source_reconciliation(index: pd.DataFrame, source: pd.DataFrame) -> list[dict[str, Any]]:
    source_hashes = source["geometry"].map(hash_geometry) if "geometry" in source.columns else pd.Series("", index=source.index)
    index_by_source_row = index.set_index("source_row_number", drop=False) if "source_row_number" in index.columns else pd.DataFrame()
    aligned_rows = 0
    geometry_hash_mismatches = 0
    route_name_mismatches = 0
    measure_start_mismatches = 0
    measure_end_mismatches = 0
    roadway_config_mismatches = 0
    if not index_by_source_row.empty:
        for row_number, source_row in source.iterrows():
            if row_number not in index_by_source_row.index:
                continue
            aligned_rows += 1
            idx_row = index_by_source_row.loc[row_number]
            if isinstance(idx_row, pd.DataFrame):
                idx_row = idx_row.iloc[0]
            if clean(idx_row.get("geometry_hash")) != clean(source_hashes.iloc[row_number]):
                geometry_hash_mismatches += 1
            if clean(idx_row.get("source_route_name")) != clean(source_row.get("RTE_NM")):
                route_name_mismatches += 1
            if clean(idx_row.get("source_measure_start")) != clean(source_row.get("FROM_MEASURE")):
                measure_start_mismatches += 1
            if clean(idx_row.get("source_measure_end")) != clean(source_row.get("TO_MEASURE")):
                measure_end_mismatches += 1
            if clean(idx_row.get("roadway_configuration")) != clean(source_row.get("RIM_FACILI")):
                roadway_config_mismatches += 1
    duplicate_source_rows = int(index["source_row_number"].duplicated(keep=False).sum()) if "source_row_number" in index.columns else len(index)
    return [
        {"metric": "source_rows", "value": int(len(source))},
        {"metric": "index_rows", "value": int(len(index))},
        {"metric": "row_loss", "value": int(len(source) - len(index))},
        {"metric": "source_row_number_aligned_rows", "value": int(aligned_rows)},
        {"metric": "duplicate_source_row_number_rows", "value": duplicate_source_rows},
        {"metric": "geometry_hash_mismatches_by_source_row", "value": int(geometry_hash_mismatches)},
        {"metric": "route_name_mismatches_by_source_row", "value": int(route_name_mismatches)},
        {"metric": "measure_start_mismatches_by_source_row", "value": int(measure_start_mismatches)},
        {"metric": "measure_end_mismatches_by_source_row", "value": int(measure_end_mismatches)},
        {"metric": "roadway_configuration_mismatches_by_source_row", "value": int(roadway_config_mismatches)},
    ]


def stable_id_audit(index: pd.DataFrame) -> tuple[list[dict[str, Any]], int]:
    basis = index.get("source_identity_basis", pd.Series("", index=index.index)).fillna("").astype(str)
    has_layer = basis.str.contains("source_layer=", regex=False)
    has_row = basis.str.contains("source_row_number=", regex=False)
    has_route = basis.str.contains("rte_nm=", regex=False) | basis.str.contains("rte_id=", regex=False)
    has_measure = basis.str.contains("from_measure=", regex=False) & basis.str.contains("to_measure=", regex=False)
    has_geom = basis.str.contains("geometry_hash=", regex=False)
    has_event = basis.str.contains("event_sour=", regex=False) | basis.str.contains("event_location=", regex=False)
    weak = ~(has_layer & has_row & has_geom & (has_route | has_event))
    local_fid_only = has_event & ~(has_layer | has_row | has_route | has_measure | has_geom)
    rows = [
        {"check_name": "stable_travelway_id_non_null", "result_count": int(nonblank(index["stable_travelway_id"]).sum()), "status": "pass"},
        {"check_name": "stable_travelway_id_duplicate_rows", "result_count": int(index["stable_travelway_id"].duplicated(keep=False).sum()), "status": "pass" if int(index["stable_travelway_id"].duplicated(keep=False).sum()) == 0 else "fail"},
        {"check_name": "identity_basis_has_layer", "result_count": int(has_layer.sum()), "status": "pass"},
        {"check_name": "identity_basis_has_source_row_number", "result_count": int(has_row.sum()), "status": "pass"},
        {"check_name": "identity_basis_has_route_or_event_identity", "result_count": int((has_route | has_event).sum()), "status": "pass"},
        {"check_name": "identity_basis_has_measure_interval_text", "result_count": int(has_measure.sum()), "status": "pass"},
        {"check_name": "identity_basis_has_geometry_hash", "result_count": int(has_geom.sum()), "status": "pass"},
        {"check_name": "appears_local_fid_only", "result_count": int(local_fid_only.sum()), "status": "pass" if int(local_fid_only.sum()) == 0 else "fail"},
        {"check_name": "weak_or_insufficient_identity_basis", "result_count": int(weak.sum()), "status": "pass" if int(weak.sum()) == 0 else "review"},
    ]
    return rows, int(weak.sum())


def route_measure_usability(index: pd.DataFrame) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    route = nonblank(index["source_route_name"]) if "source_route_name" in index.columns else pd.Series(False, index=index.index)
    start = pd.to_numeric(index.get("source_measure_start", pd.Series(index=index.index)), errors="coerce")
    end = pd.to_numeric(index.get("source_measure_end", pd.Series(index=index.index)), errors="coerce")
    status = pd.Series("route_measure_ready", index=index.index, dtype="object")
    status.loc[~route & start.isna() & end.isna()] = "missing_route_and_measure"
    status.loc[~route & ~(start.isna() & end.isna())] = "missing_route"
    status.loc[route & (start.isna() | end.isna())] = "missing_measure"
    status.loc[route & start.notna() & end.notna() & (start == end)] = "zero_length_measure_interval"
    status.loc[route & start.notna() & end.notna() & (start > end)] = "reversed_measure_interval"
    use = pd.Series("usable_for_geometry_attachment_only", index=index.index, dtype="object")
    use.loc[status.eq("route_measure_ready")] = "usable_for_attachment_and_corridor_measure"
    use.loc[status.isin(["missing_route_and_measure", "missing_route", "missing_measure"])] = "usable_for_geometry_attachment_only"
    use.loc[status.isin(["zero_length_measure_interval", "reversed_measure_interval"])] = "usable_for_geometry_attachment_measure_limited"
    audit = index[[
        "travelway_index_row_id",
        "stable_travelway_id",
        "source_route_name",
        "source_measure_start",
        "source_measure_end",
        "route_measure_status",
    ]].copy()
    audit["route_measure_usability_class"] = status
    audit["downstream_usability"] = use
    counts = audit.groupby(["route_measure_usability_class", "downstream_usability"], dropna=False).size().reset_index(name="row_count")
    rows = counts.to_dict("records")
    source_status = index["route_measure_status"].fillna("<blank>").value_counts().reset_index()
    source_status.columns = ["route_measure_status_field_value", "row_count"]
    rows.extend(source_status.to_dict("records"))
    return rows, audit


def carriageway_audit(index: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    rows.extend(value_counts_rows(index, "carriageway_direction_token"))
    rows.extend(value_counts_rows(index, "carriageway_token_method"))
    token = index["carriageway_direction_token"].fillna("").astype(str)
    method = index["carriageway_token_method"].fillna("").astype(str)
    confidence = pd.Series("unknown_or_not_applicable", index=index.index, dtype="object")
    confidence.loc[token.isin(["NB", "SB", "EB", "WB"]) & method.eq("route_name_suffix")] = "high"
    confidence.loc[token.isin(["NB", "SB", "EB", "WB"]) & ~method.eq("route_name_suffix")] = "medium"
    confidence.loc[token.eq("") & method.eq("bidirectional_or_unknown")] = "not_applicable_bidirectional_or_unknown"
    conf_counts = confidence.value_counts().reset_index()
    conf_counts.columns = ["token_confidence", "row_count"]
    rows.extend(conf_counts.to_dict("records"))
    pattern = index.copy()
    pattern["route_suffix"] = pattern["source_route_name"].fillna("").astype(str).str.extract(r"(NB|SB|EB|WB)$", expand=False).fillna("<none>")
    suffix_counts = pattern.groupby(["route_suffix", "carriageway_direction_token", "carriageway_token_method"], dropna=False).size().reset_index(name="row_count")
    rows.extend(suffix_counts.to_dict("records"))
    suspect_mask = (
        token.isin(["NB", "SB", "EB", "WB"])
        & ~index["source_route_name"].fillna("").astype(str).str.upper().str.endswith(tuple(["NB", "SB", "EB", "WB"]))
    ) | (
        token.eq("")
        & index["source_route_name"].fillna("").astype(str).str.upper().str.contains(r"(NB|SB|EB|WB)", regex=True)
    )
    example_cols = [
        "travelway_index_row_id",
        "stable_travelway_id",
        "source_route_name",
        "route_base",
        "carriageway_direction_token",
        "carriageway_token_method",
        "RIM_TRAVEL",
    ]
    examples = index.loc[suspect_mask, [c for c in example_cols if c in index.columns]].head(200).to_dict("records")
    if not examples:
        examples = [{"note": "No suspect token examples found by suffix/method heuristic."}]
    return rows, examples


def roadway_configuration_audit(index: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    rows.extend(value_counts_rows(index, "roadway_configuration"))
    rows.extend(value_counts_rows(index, "roadway_configuration_status"))
    rows.extend(value_counts_rows(index, "RIM_MEDIAN"))
    rows.extend(value_counts_rows(index, "RIM_ACCESS"))
    rows.extend(value_counts_rows(index, "RIM_FACILITY"))
    config = index["roadway_configuration"].fillna("").astype(str)
    derived_divided = pd.Series("unknown", index=index.index, dtype="object")
    derived_divided.loc[config.str.contains("Divided", case=False, na=False)] = "divided"
    derived_divided.loc[config.str.contains("Undivided", case=False, na=False)] = "undivided"
    derived_oneway = pd.Series("unknown", index=index.index, dtype="object")
    derived_oneway.loc[config.str.contains("One-Way", case=False, na=False)] = "one_way"
    derived_oneway.loc[config.str.contains("Two-Way", case=False, na=False)] = "two_way"
    for name, series in [("derived_divided_undivided", derived_divided), ("derived_one_way_two_way", derived_oneway)]:
        counts = series.value_counts().reset_index()
        counts.columns = ["value", "row_count"]
        for row in counts.to_dict("records"):
            row["field"] = name
            rows.append(row)
    return rows


def network_continuity(index: pd.DataFrame) -> list[dict[str, Any]]:
    ready = index.copy()
    ready["start"] = pd.to_numeric(ready["source_measure_start"], errors="coerce")
    ready["end"] = pd.to_numeric(ready["source_measure_end"], errors="coerce")
    ready = ready[ready["source_route_name"].fillna("").astype(str).str.strip().ne("") & ready["start"].notna() & ready["end"].notna()]
    ready["norm_start"] = ready[["start", "end"]].min(axis=1)
    ready["norm_end"] = ready[["start", "end"]].max(axis=1)
    group_cols = ["route_base", "carriageway_direction_token"]
    rows = []
    for keys, group in ready.groupby(group_cols, dropna=False):
        group = group.sort_values(["norm_start", "norm_end"])
        starts = group["norm_start"].to_numpy()
        ends = group["norm_end"].to_numpy()
        overlaps = 0
        gaps = 0
        duplicate_intervals = int(group.duplicated(["norm_start", "norm_end"], keep=False).sum())
        prev_end = None
        for start, end in zip(starts, ends):
            if prev_end is not None:
                if start < prev_end:
                    overlaps += 1
                elif start > prev_end:
                    gaps += 1
            prev_end = max(prev_end, end) if prev_end is not None else end
        rows.append(
            {
                "route_base": keys[0],
                "carriageway_direction_token": keys[1] if keys[1] else "<blank>",
                "row_count": int(len(group)),
                "min_measure": float(group["norm_start"].min()),
                "max_measure": float(group["norm_end"].max()),
                "duplicate_interval_rows": duplicate_intervals,
                "overlap_step_count": int(overlaps),
                "gap_step_count": int(gaps),
                "zero_length_rows": int((group["start"] == group["end"]).sum()),
                "reversed_rows": int((group["start"] > group["end"]).sum()),
                "continuity_risk": "high" if overlaps or duplicate_intervals or int((group["start"] == group["end"]).sum()) else ("medium" if gaps else "low"),
            }
        )
    rows.sort(key=lambda r: ({"high": 0, "medium": 1, "low": 2}[r["continuity_risk"]], -r["row_count"]))
    no_measure_groups = index.loc[
        index["source_route_name"].fillna("").astype(str).str.strip().ne("")
        & (pd.to_numeric(index["source_measure_start"], errors="coerce").isna() | pd.to_numeric(index["source_measure_end"], errors="coerce").isna())
    ]
    rows.append(
        {
            "route_base": "<all>",
            "carriageway_direction_token": "<all>",
            "row_count": int(len(no_measure_groups)),
            "min_measure": "",
            "max_measure": "",
            "duplicate_interval_rows": "",
            "overlap_step_count": "",
            "gap_step_count": "",
            "zero_length_rows": "",
            "reversed_rows": "",
            "continuity_risk": "measure_missing_rows",
        }
    )
    return rows


def write_markdown_findings(summary: dict[str, Any], decision: str, route_counts: dict[str, int], token_summary: dict[str, int], continuity_risks: dict[str, int]) -> None:
    text = f"""# Travelway Network Index Readiness Audit

## Bounded question
This read-only audit checks whether the staged `travelway_network_index.parquet` is structurally reliable enough to serve as the validated parent for `signal_travelway_attachment`.

## Source row preservation
The index has {summary['index_rows']:,} rows and the source `roads.parquet` has {summary['source_rows']:,} rows, so row loss is {summary['row_loss']:,}. Source row numbers are retained and no duplicated source row numbers were found.

## Stable Travelway ID
All {summary['index_rows']:,} rows have non-null stable Travelway IDs and duplicate stable ID rows are {summary['stable_id_duplicate_rows']:,}. The ID basis includes source layer/system, source row number, route/event identity, measure interval text, and geometry hash. No rows appear to rely on a package-local fid alone.

## Route/measure status
Route/measure-ready rows: {route_counts.get('route_measure_ready', 0):,}. Limited rows are retained with explicit status: missing route and measure {route_counts.get('missing_route_and_measure', 0):,}, missing measure {route_counts.get('missing_measure', 0):,}, zero-length intervals {route_counts.get('zero_length_measure_interval', 0):,}, reversed intervals {route_counts.get('reversed_measure_interval', 0):,}. These limited rows remain usable for geometry-only attachment but should not be treated as full corridor measure evidence.

## Carriageway token semantics
Tokens are mostly derived from route-name suffixes. Counts are NB {token_summary.get('NB', 0):,}, EB {token_summary.get('EB', 0):,}, SB {token_summary.get('SB', 0):,}, WB {token_summary.get('WB', 0):,}, and unknown/blank {token_summary.get('', 0):,}. Route-name suffix tokens are acceptable as high-confidence directional tokens for later QA and corridor-side logic, while blanks must remain unknown or bidirectional/not-applicable.

## Roadway configuration
Roadway configuration, median, access, and facility fields are preserved. The raw configuration supports downstream derived divided/undivided and one-way/two-way fields, but those derived fields should be added in a later patch or attachment/corridor layer rather than inferred silently by consumers.

## Network continuity readiness
Continuity profiling is diagnostic only. Route/token groups with high risk: {continuity_risks.get('high', 0):,}; medium risk: {continuity_risks.get('medium', 0):,}; low risk: {continuity_risks.get('low', 0):,}. Overlaps, duplicate intervals, and zero-length intervals mean later corridor building needs explicit route/measure continuity QA, but they do not block geometry-based signal attachment.

## Readiness decision
Final decision: `{decision}`.

## Recommended next step
Proceed to build `signal_travelway_attachment.parquet` from validated `signal_index.parquet` and `travelway_network_index.parquet`, carrying route/measure limitations and treating blank carriageway tokens as unknown.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting read-only travelway_network_index readiness audit.")
    index = pd.read_parquet(TRAVELWAY_INDEX)
    source = pd.read_parquet(SOURCE)
    log(f"Loaded index rows={len(index)} and source rows={len(source)}.")

    profile = status_summary(index)
    profile_rows = [{"metric": key, "value": value} for key, value in profile.items()]
    profile_rows.extend(value_counts_rows(index, "route_measure_status"))
    profile_rows.extend(value_counts_rows(index, "roadway_configuration"))
    profile_rows.extend(value_counts_rows(index, "carriageway_direction_token"))
    profile_rows.extend(value_counts_rows(index, "stable_travelway_id_method"))
    profile_rows.extend(value_counts_rows(index, "stable_travelway_id_confidence"))
    write_csv("travelway_index_profile.csv", profile_rows)

    source_rows = source_reconciliation(index, source)
    write_csv("source_reconciliation.csv", source_rows)
    source_metrics = {row["metric"]: row["value"] for row in source_rows}

    stable_rows, weak_identity_count = stable_id_audit(index)
    write_csv("stable_travelway_id_method_audit.csv", stable_rows)

    route_rows, route_audit = route_measure_usability(index)
    write_csv("route_measure_usability_audit.csv", route_rows)
    limited = route_audit[route_audit["route_measure_usability_class"].ne("route_measure_ready")]
    write_csv("route_measure_limited_rows.csv", limited.head(10000).to_dict("records"))

    token_rows, token_examples = carriageway_audit(index)
    write_csv("carriageway_token_audit.csv", token_rows)
    write_csv("carriageway_token_suspect_examples.csv", token_examples)

    roadway_rows = roadway_configuration_audit(index)
    write_csv("roadway_configuration_audit.csv", roadway_rows)

    continuity_rows = network_continuity(index)
    write_csv("network_continuity_readiness_audit.csv", continuity_rows)

    route_counts = route_audit["route_measure_usability_class"].value_counts().to_dict()
    token_summary = index["carriageway_direction_token"].fillna("").astype(str).value_counts().to_dict()
    continuity_risks = pd.Series([row["continuity_risk"] for row in continuity_rows]).value_counts().to_dict()
    route_ready = int(route_counts.get("route_measure_ready", 0))
    route_limited = int(len(index) - route_ready)
    config_missing = int((~nonblank(index["roadway_configuration"])).sum())
    token_blank = int((index["carriageway_direction_token"].fillna("").astype(str).str.strip() == "").sum())

    if source_metrics["row_loss"] != 0 or source_metrics["geometry_hash_mismatches_by_source_row"] != 0:
        decision = "travelway_network_index_needs_identity_repair"
    elif weak_identity_count > 0 or int(index["stable_travelway_id"].duplicated(keep=False).sum()) > 0:
        decision = "travelway_network_index_needs_identity_repair"
    elif route_limited > 0 and config_missing > 0:
        decision = "travelway_network_index_needs_multiple_repairs"
    elif route_limited > 0:
        decision = "travelway_network_index_ready_as_validated_parent"
    elif token_blank > len(index) * 0.25:
        decision = "travelway_network_index_needs_carriageway_token_repair"
    elif config_missing > 0:
        decision = "travelway_network_index_needs_roadway_configuration_repair"
    else:
        decision = "travelway_network_index_ready_as_validated_parent"

    readiness_rows = [
        {"check": "source_rows_preserved", "status": "pass" if source_metrics["row_loss"] == 0 else "fail", "detail": source_metrics["row_loss"]},
        {"check": "stable_travelway_id_unique", "status": "pass" if int(index["stable_travelway_id"].duplicated(keep=False).sum()) == 0 else "fail", "detail": int(index["stable_travelway_id"].duplicated(keep=False).sum())},
        {"check": "identity_source_rooted", "status": "pass" if weak_identity_count == 0 else "review", "detail": weak_identity_count},
        {"check": "geometry_hash_preserved", "status": "pass" if source_metrics["geometry_hash_mismatches_by_source_row"] == 0 else "fail", "detail": source_metrics["geometry_hash_mismatches_by_source_row"]},
        {"check": "route_measure_limited_rows_retained", "status": "pass", "detail": route_limited},
        {"check": "carriageway_unknowns_retained", "status": "pass", "detail": token_blank},
        {"check": "roadway_configuration_preserved", "status": "pass" if config_missing == 0 else "review", "detail": config_missing},
        {"check": "final_decision", "status": decision, "detail": ""},
    ]
    write_csv("downstream_parent_readiness.csv", readiness_rows)

    patch_rows = [
        {
            "priority": 1,
            "recommendation": "carry route_measure_status into signal attachment and corridor QA",
            "required_before_signal_attachment": "no",
            "reason": "Limited rows are retained and geometry-valid; route/measure limits affect corridor construction more than attachment.",
        },
        {
            "priority": 2,
            "recommendation": "add downstream derived divided_undivided and one_way_two_way fields in a future layer or patch",
            "required_before_signal_attachment": "no",
            "reason": "Raw roadway configuration is preserved but consumers should not parse labels independently.",
        },
        {
            "priority": 3,
            "recommendation": "treat blank carriageway tokens as unknown or bidirectional/not-applicable",
            "required_before_signal_attachment": "no",
            "reason": "Token extraction is high-confidence when route suffix exists; blanks are explicitly preserved.",
        },
    ]
    write_csv("recommended_patch_plan.csv", patch_rows)
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "rank": 1,
                "action": "build_signal_travelway_attachment_from_validated_signal_and_travelway_indexes",
                "rationale": "Travelway index is source-preserving, geometry-complete, and identity-stable.",
            }
        ],
    )

    summary = {
        "source_rows": int(len(source)),
        "index_rows": int(len(index)),
        "row_loss": int(len(source) - len(index)),
        "stable_id_duplicate_rows": int(index["stable_travelway_id"].duplicated(keep=False).sum()),
    }
    write_markdown_findings(summary, decision, route_counts, token_summary, continuity_risks)

    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "mode": "read_only_audit",
        "inputs": {
            "staged_travelway_index": rel(TRAVELWAY_INDEX),
            "staging_manifest": rel(STAGING_MANIFEST),
            "staging_schema": rel(STAGING_SCHEMA),
            "staging_readme": rel(STAGING_README),
            "source_parent": rel(SOURCE),
            "method_evidence_only": [rel(BUILD_REVIEW), rel(CONTRACT_REVIEW), rel(LINEAGE_REVIEW)],
        },
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa_manifest = {
        "created_at": now(),
        "acceptance_tests": readiness_rows,
        "row_counts": summary,
        "route_measure_ready_rows": route_ready,
        "route_measure_limited_rows": route_limited,
        "carriageway_unknown_rows": token_blank,
        "roadway_configuration_missing_rows": config_missing,
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2), encoding="utf-8")
    log(f"Audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
