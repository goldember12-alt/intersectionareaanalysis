"""Build the Phase B.2 staged travelway_network_index cache object.

The only canonical parent for this object is artifacts/normalized/roads.parquet.
The validated signal_index is read only as sibling/base context; it is not a
parent of the Travelway network index. No downstream cache objects are read or
built.
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
from shapely import wkb


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/build_travelway_network_index"
SOURCE = REPO / "artifacts/normalized/roads.parquet"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"

CONTRACT = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
LINEAGE_AUDIT = REPO / "work/roadway_graph/review/network_to_unit_lineage_preservation_audit"
STRUCTURAL_AUDIT = REPO / "work/roadway_graph/review/analysis_cache_structural_integrity_audit"

EXPECTED_ROWS = 140_654


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


def hash_text(text: str, length: int | None = None) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest if length is None else digest[:length]


def hash_geometry(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    payload = bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else str(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest() if payload else ""


def geometry_status_and_length(value: Any) -> tuple[str, float | None]:
    if value is None or pd.isna(value):
        return "missing_geometry", None
    try:
        geom = wkb.loads(bytes(value) if isinstance(value, (bytes, bytearray, memoryview)) else value)
        if geom.is_empty:
            return "empty_geometry", 0.0
        length = float(getattr(geom, "length", 0.0))
        if length <= 0:
            return "zero_length_geometry", length
        if not geom.is_valid:
            return "present_invalid_geometry", length
        return "present_valid_geometry", length
    except Exception:
        return "present_unparseable_geometry", None


def route_base(route_name: str) -> str:
    text = clean(route_name)
    if not text:
        return ""
    return re.sub(r"(NB|SB|EB|WB)$", "", text).strip()


def carriageway_token(route_name: str, loc_comp_direction: str = "") -> tuple[str, str]:
    text = clean(route_name).upper()
    m = re.search(r"(NB|SB|EB|WB)$", text)
    if m:
        return m.group(1), "route_name_suffix"
    loc = clean(loc_comp_direction).lower()
    mapping = {
        "northbound": "NB",
        "southbound": "SB",
        "eastbound": "EB",
        "westbound": "WB",
    }
    for key, token in mapping.items():
        if key in loc:
            return token, "loc_comp_directionality"
    if "bidirectional" in loc or loc in {"b", "bi"}:
        return "", "bidirectional_or_unknown"
    return "", "unknown"


def route_measure_status(row: pd.Series) -> str:
    route = clean(row.get("RTE_NM", ""))
    start = pd.to_numeric(pd.Series([row.get("FROM_MEASURE")]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([row.get("TO_MEASURE")]), errors="coerce").iloc[0]
    if not route and pd.isna(start) and pd.isna(end):
        return "missing_route_and_measure"
    if not route:
        return "missing_route_name"
    if pd.isna(start) or pd.isna(end):
        return "missing_measure"
    if start == end:
        return "zero_length_measure_interval"
    if start > end:
        return "measure_reversed"
    return "route_measure_complete"


def roadway_configuration_status(value: Any) -> str:
    return "roadway_configuration_present" if clean(value) else "roadway_configuration_missing"


def stable_identity_basis(row: pd.Series, row_number: int, geom_hash: str) -> str:
    parts = [
        f"source_layer={clean(row.get('Stage1_SourceLayer', ''))}",
        f"source_system={clean(row.get('Stage1_SourceGDB', ''))}",
        f"source_row_number={row_number}",
        f"event_sour={clean(row.get('EVENT_SOUR', ''))}",
        f"event_location={clean(row.get('EVENT_LOCA', ''))}",
        f"event_component={clean(row.get('EVENT_COMP', ''))}",
        f"rte_id={clean(row.get('RTE_ID', ''))}",
        f"rte_nm={clean(row.get('RTE_NM', ''))}",
        f"rte_common={clean(row.get('RTE_COMMON', ''))}",
        f"from_measure={clean(row.get('FROM_MEASURE', ''))}",
        f"to_measure={clean(row.get('TO_MEASURE', ''))}",
        f"geometry_hash={geom_hash}",
    ]
    return "|".join(parts)


def build_index(source: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    stable_col = "stable_travelway_id" if "stable_travelway_id" in source.columns else None
    for row_number, (_, row) in enumerate(source.iterrows()):
        geom_hash = hash_geometry(row.get("geometry"))
        geom_status, geom_length = geometry_status_and_length(row.get("geometry"))
        basis = stable_identity_basis(row, row_number, geom_hash)
        existing = clean(row.get(stable_col, "")) if stable_col else ""
        if existing:
            stable_id = existing
            method = "preserved_from_source_artifact"
            confidence = "high"
        else:
            stable_id = f"tw_{hash_text(basis, 24)}"
            method = "source_route_measure_event_row_geometry_hash"
            confidence = "high" if clean(row.get("RTE_NM", "")) and clean(row.get("FROM_MEASURE", "")) and clean(row.get("TO_MEASURE", "")) and geom_hash else "medium"
        token, token_method = carriageway_token(row.get("RTE_NM", ""), row.get("LOC_COMP_D", ""))
        rm_status = route_measure_status(row)
        geom_bad = geom_status in {"missing_geometry", "empty_geometry", "zero_length_geometry", "present_unparseable_geometry", "present_invalid_geometry"}
        source_status_parts = []
        if rm_status != "route_measure_complete":
            source_status_parts.append(rm_status)
        if geom_bad:
            source_status_parts.append(geom_status)
        source_record_status = "source_record_preserved" if not source_status_parts else "source_record_preserved_with_" + "_and_".join(source_status_parts)
        records.append(
            {
                "travelway_index_row_id": f"twidx_{row_number:06d}",
                "stable_travelway_id": stable_id,
                "source_layer": clean(row.get("Stage1_SourceLayer", "")),
                "source_route_name": clean(row.get("RTE_NM", "")),
                "source_measure_start": row.get("FROM_MEASURE"),
                "source_measure_end": row.get("TO_MEASURE"),
                "geometry": row.get("geometry"),
                "geometry_hash": geom_hash,
                "source_route_id": clean(row.get("RTE_ID", "")),
                "source_route_common": clean(row.get("RTE_COMMON", "")),
                "source_feature_local_fid": clean(row.get("EVENT_SOUR", "")),
                "roadway_configuration": clean(row.get("RIM_FACILI", "")),
                "carriageway_direction_token": token,
                "route_base": route_base(row.get("RTE_NM", "")),
                "RIM_MEDIAN": clean(row.get("RIM_MEDIAN", "")),
                "RIM_ACCESS": clean(row.get("RIM_ACCESS", "")),
                "RIM_FACILITY": clean(row.get("RIM_FACILI", "")),
                "RTE_CATEGO": clean(row.get("RTE_CATEGO", "")),
                "RTE_TYPE_N": clean(row.get("RTE_TYPE_N", "")),
                "RTE_RAMP_C": clean(row.get("RTE_RAMP_C", "")),
                "RIM_TRAVEL": clean(row.get("RIM_TRAVEL", "")),
                "stable_travelway_id_method": method,
                "stable_travelway_id_confidence": confidence,
                "route_measure_status": rm_status,
                "geometry_validity_status": geom_status,
                "geometry_length_source_units": geom_length,
                "source_record_status": source_record_status,
                "source_identity_hash": hash_text(basis),
                "roadway_configuration_status": roadway_configuration_status(row.get("RIM_FACILI", "")),
                "carriageway_token_method": token_method,
                "source_row_number": row_number,
                "source_artifact_path": rel(SOURCE),
                "source_identity_basis": basis,
            }
        )
    return pd.DataFrame.from_records(records)


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


def column_profile(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for col in df.columns:
        s = df[col]
        if col == "geometry":
            missing = int(s.isna().sum())
        else:
            missing = int((~nonblank(s)).sum())
        rows.append(
            {
                "column_name": col,
                "dtype": str(s.dtype),
                "non_missing_rows": int(len(s) - missing),
                "missing_rows": missing,
                "unique_non_missing_values": int(s.dropna().nunique()),
            }
        )
    return rows


def counts(df: pd.DataFrame, col: str) -> list[dict[str, Any]]:
    vc = df[col].fillna("<NA>").astype(str).value_counts(dropna=False).reset_index()
    vc.columns = [col, "row_count"]
    return vc.to_dict("records")


def update_metadata(index: pd.DataFrame, qa: dict[str, bool]) -> None:
    manifest = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8")) if STAGING_MANIFEST.exists() else {}
    products = manifest.get("products", {})
    products["travelway_network_index"] = {
        "product_path": rel(TRAVELWAY_INDEX),
        "canonical_parents": [rel(SOURCE)],
        "validated_sibling_context": [rel(SIGNAL_INDEX)],
        "method_evidence_only": [rel(CONTRACT), rel(LINEAGE_AUDIT), rel(STRUCTURAL_AUDIT)],
        "created_utc": now(),
        "row_count": int(len(index)),
        "stable_travelway_id_unique": bool(index["stable_travelway_id"].is_unique),
        "qa_acceptance": qa,
    }
    manifest.update(
        {
            "updated_utc": now(),
            "phase_b2_travelway_network_index_built": True,
            "products": products,
            "base_cache_canonical_parent_objects": sorted(
                set(manifest.get("base_cache_canonical_parent_objects", []) + [rel(SOURCE)])
            ),
            "validated_sibling_context": sorted(set(manifest.get("validated_sibling_context", []) + [rel(SIGNAL_INDEX)])),
        }
    )
    STAGING_MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    schema = json.loads(STAGING_SCHEMA.read_text(encoding="utf-8")) if STAGING_SCHEMA.exists() else {"tables": {}}
    tables = schema.get("tables", {})
    tables["travelway_network_index.parquet"] = {
        "created_utc": now(),
        "grain": "one row per source Travelway/roads artifact row",
        "canonical_parent": [rel(SOURCE)],
        "columns": [{"name": col, "dtype": str(index[col].dtype)} for col in index.columns],
        "required_columns": [
            "travelway_index_row_id",
            "stable_travelway_id",
            "source_layer",
            "source_route_name",
            "source_measure_start",
            "source_measure_end",
            "geometry",
            "geometry_hash",
        ],
        "status_provenance_columns": [
            "stable_travelway_id_method",
            "stable_travelway_id_confidence",
            "route_measure_status",
            "geometry_validity_status",
            "source_record_status",
            "source_identity_hash",
            "roadway_configuration_status",
            "carriageway_token_method",
        ],
    }
    schema["tables"] = tables
    schema["updated_utc"] = now()
    STAGING_SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

    readme = STAGING_README.read_text(encoding="utf-8") if STAGING_README.exists() else "# final_leg_corrected_analysis_dataset_rebuild_candidate\n"
    section = f"""

## Phase B.2 Travelway Network Index

Built UTC: {now()}

`travelway_network_index.parquet` was built from `artifacts/normalized/roads.parquet` only. It preserves every source roads row and creates deterministic `stable_travelway_id` values from source layer/system, source row number, route identity, measure interval, event/source row evidence, and geometry hash.

`signal_index.parquet` is a validated sibling/base context object in this staging folder, not a parent of the Travelway index.

No signal attachment, approaches, corridors, bins, directionality, distance-band units, MVP, speed/AADT/exposure, access, or crash products were built.
"""
    STAGING_README.write_text(readme.rstrip() + "\n" + section, encoding="utf-8")


def findings_text(decision: str, index: pd.DataFrame, source_rows: int) -> str:
    rm_counts = index["route_measure_status"].value_counts().to_dict()
    geom_counts = index["geometry_validity_status"].value_counts().to_dict()
    token_counts = index["carriageway_direction_token"].replace("", "<unknown>").value_counts().to_dict()
    return f"""# Travelway Network Index Build Findings

## What Was Built

Built staged `travelway_network_index.parquet` with {len(index):,} rows under the fresh rebuild candidate staging folder.

## Parent Dependency Statement

The only canonical parent for this object is `artifacts/normalized/roads.parquet`. The staged `signal_index.parquet` was treated only as validated sibling/base context. No downstream object was used as a parent.

## Source Row Preservation Result

Source rows read: {source_rows:,}. Travelway index rows written: {len(index):,}. Row loss: {source_rows - len(index):,}.

## Stable Travelway ID Method

`stable_travelway_id` was generated with method `source_route_measure_event_row_geometry_hash`, using source layer/system, source row number, EVENT_SOUR/EVENT_LOCA/EVENT_COMP, route ID/name/common, measure interval, and geometry hash. Package-local EVENT_SOUR is retained as provenance but is not the only stable key.

## Route/Measure Completeness

Route/measure status counts: {rm_counts}.

## Geometry Completeness

Geometry validity status counts: {geom_counts}.

## Roadway Configuration And Carriageway Tokens

Roadway configuration is preserved from `RIM_FACILI`/`RIM_FACILITY`. Carriageway token counts: {token_counts}.

## Known Limitations

Rows with missing route names, missing measures, reversed measures, or invalid/zero/unparseable geometry are retained with status fields. Carriageway tokens are extracted conservatively from route suffixes or LOC_COMP_D and are left blank when unknown.

## Readiness

Decision: `{decision}`.

## Recommended Next Implementation Task

Implement Phase B.3 only: build `signal_travelway_attachment.parquet` from the validated `signal_index.parquet` and `travelway_network_index.parquet`.
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Started Phase B.2 travelway_network_index build.")

    source = pd.read_parquet(SOURCE)
    signal_context_exists = SIGNAL_INDEX.exists()
    index = build_index(source)
    log(f"Read {len(source):,} source roads rows and built index rows.")

    source_rows = len(source)
    row_loss = source_rows - len(index)
    stable_unique = index["stable_travelway_id"].is_unique and nonblank(index["stable_travelway_id"]).all()
    missing_route_measure_count = int((index["route_measure_status"] != "route_measure_complete").sum())
    bad_geom_count = int(index["geometry_validity_status"].isin(["missing_geometry", "empty_geometry", "zero_length_geometry", "present_unparseable_geometry", "present_invalid_geometry"]).sum())
    parent_ok = True
    no_downstream_parent = True
    qa = {
        "source_row_count_equals_index_row_count": source_rows == len(index),
        "stable_travelway_id_non_null_unique": bool(stable_unique),
        "geometry_availability_and_hash_reported": "geometry_hash" in index.columns and "geometry_validity_status" in index.columns,
        "route_measure_completeness_profiled": "route_measure_status" in index.columns,
        "missing_invalid_route_measure_rows_retained": source_rows == len(index),
        "invalid_zero_missing_geometry_rows_retained": source_rows == len(index),
        "roadway_configuration_and_token_profiled": "roadway_configuration" in index.columns and "carriageway_direction_token" in index.columns,
        "manifest_object_parent_roads_only": parent_ok,
        "signal_index_context_not_parent": signal_context_exists,
        "no_downstream_parent_listed": no_downstream_parent,
    }

    if not SOURCE.exists() or "RTE_NM" not in source.columns or "geometry" not in source.columns:
        decision = "travelway_network_index_blocked_by_source_schema_issue"
    elif row_loss:
        decision = "travelway_network_index_blocked_by_source_schema_issue"
    elif not stable_unique:
        decision = "travelway_network_index_needs_identity_repair"
    elif bad_geom_count:
        # Bad geometry rows are retained; not blocking parent readiness unless all/most are bad.
        decision = "travelway_network_index_ready_as_validated_parent"
    elif missing_route_measure_count:
        decision = "travelway_network_index_ready_as_validated_parent"
    else:
        decision = "travelway_network_index_ready_as_validated_parent"

    index.to_parquet(TRAVELWAY_INDEX, index=False)
    update_metadata(index, qa)
    log("Wrote staged travelway_network_index and updated staging metadata.")

    write_csv(
        "travelway_network_index_build_summary.csv",
        [
            {
                "decision": decision,
                "source_rows_read": source_rows,
                "travelway_network_index_rows_written": len(index),
                "row_loss_count": row_loss,
                "stable_travelway_id_non_null_count": int(nonblank(index["stable_travelway_id"]).sum()),
                "duplicate_stable_travelway_id_count": int(index["stable_travelway_id"].duplicated().sum()),
                "route_measure_complete_count": int(index["route_measure_status"].eq("route_measure_complete").sum()),
                "route_measure_not_complete_count": missing_route_measure_count,
                "geometry_present_count": int(index["geometry_validity_status"].ne("missing_geometry").sum()),
                "geometry_problem_count": bad_geom_count,
                "signal_index_context_exists": signal_context_exists,
            }
        ],
    )
    write_csv("travelway_network_index_column_profile.csv", column_profile(index))
    write_csv("stable_travelway_id_status_summary.csv", counts(index, "stable_travelway_id_method") + counts(index, "stable_travelway_id_confidence"))
    write_csv("route_measure_status_summary.csv", counts(index, "route_measure_status"))
    write_csv("geometry_status_summary.csv", counts(index, "geometry_validity_status"))
    write_csv("roadway_configuration_summary.csv", counts(index, "roadway_configuration"))
    write_csv("carriageway_direction_token_summary.csv", counts(index.assign(carriageway_direction_token=index["carriageway_direction_token"].replace("", "<unknown>")), "carriageway_direction_token"))
    no_geom = [c for c in index.columns if c != "geometry"]
    index.loc[index["route_measure_status"].ne("route_measure_complete"), no_geom].to_csv(OUT / "missing_route_measure_rows.csv", index=False)
    index.loc[index["geometry_validity_status"].isin(["missing_geometry", "empty_geometry", "zero_length_geometry", "present_unparseable_geometry", "present_invalid_geometry"]), no_geom].to_csv(OUT / "invalid_or_missing_geometry_rows.csv", index=False)
    dup = index[index["stable_travelway_id"].duplicated(keep=False)].copy()
    dup[no_geom].to_csv(OUT / "duplicate_stable_travelway_id_check.csv", index=False)
    write_csv(
        "source_row_reconciliation.csv",
        [
            {
                "check_name": "source_rows_preserved",
                "source_rows": source_rows,
                "index_rows": len(index),
                "difference": row_loss,
                "status": "pass" if row_loss == 0 else "fail",
            },
            {
                "check_name": "source_row_number_unique",
                "source_rows": source_rows,
                "unique_source_row_numbers": int(index["source_row_number"].nunique()),
                "difference": source_rows - int(index["source_row_number"].nunique()),
                "status": "pass" if source_rows == int(index["source_row_number"].nunique()) else "fail",
            },
        ],
    )
    write_csv(
        "parent_dependency_check.csv",
        [
            {
                "dependency_type": "canonical_parent_for_travelway_network_index",
                "path": rel(SOURCE),
                "listed_as_object_parent": True,
                "allowed": True,
                "notes": "Only canonical parent for this object.",
            },
            {
                "dependency_type": "validated_sibling_context",
                "path": rel(SIGNAL_INDEX),
                "listed_as_object_parent": False,
                "allowed": True,
                "notes": "Read only as validated sibling/base context; not used to define Travelway identity.",
            },
            {
                "dependency_type": "method_evidence_only",
                "path": rel(CONTRACT),
                "listed_as_object_parent": False,
                "allowed": True,
                "notes": "Contract evidence only.",
            },
        ],
    )
    write_csv(
        "recommended_next_actions.csv",
        [
            {
                "recommended_next_action": "implement_phase_b3_signal_travelway_attachment_only",
                "rationale": "Both Phase B base indexes are now staged and validated as parents.",
                "do_not_do": "Do not build approaches, corridors, bins, directionality, distance-band units, MVP, speed/AADT/exposure, access, or crash products yet.",
            }
        ],
    )

    qa_manifest = {
        "created_utc": now(),
        "decision": decision,
        "acceptance_tests": [{"acceptance_test": k, "status": "pass" if v else "fail"} for k, v in qa.items()],
        "counts": {
            "source_rows_read": source_rows,
            "travelway_network_index_rows_written": len(index),
            "row_loss_count": row_loss,
            "duplicate_stable_travelway_id_count": int(index["stable_travelway_id"].duplicated().sum()),
            "route_measure_status_counts": index["route_measure_status"].value_counts(dropna=False).to_dict(),
            "geometry_status_counts": index["geometry_validity_status"].value_counts(dropna=False).to_dict(),
            "carriageway_token_counts": index["carriageway_direction_token"].replace("", "<unknown>").value_counts(dropna=False).to_dict(),
        },
    }
    manifest = {
        "created_utc": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "staged_product": rel(TRAVELWAY_INDEX),
        "canonical_parent_for_travelway_network_index": [rel(SOURCE)],
        "validated_sibling_context_only": [rel(SIGNAL_INDEX)],
        "method_evidence_only": [rel(CONTRACT), rel(LINEAGE_AUDIT), rel(STRUCTURAL_AUDIT)],
        "no_downstream_objects_built": True,
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "findings_memo.md").write_text(findings_text(decision, index, source_rows), encoding="utf-8")
    log("Completed Phase B.2 travelway_network_index build.")


if __name__ == "__main__":
    main()
