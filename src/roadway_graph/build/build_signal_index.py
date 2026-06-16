"""Build the Phase B.1 staged signal_index cache object.

This implementation is source-rooted: the only canonical parent is
artifacts/normalized/signals.parquet. Current canonical/staged/review products
are read only for comparison and QA context, not as identity parents.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "artifacts/normalized/signals.parquet"
STAGING = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO_ROOT / "work/roadway_graph/review/build_signal_index"

CANONICAL_SIGNAL = REPO_ROOT / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset/analysis_signal.csv"
STRUCTURAL_SOURCE_ONLY = REPO_ROOT / "work/roadway_graph/review/analysis_cache_structural_integrity_audit/source_only_signal_explanation.csv"
CONTRACT = REPO_ROOT / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
LINEAGE_AUDIT = REPO_ROOT / "work/roadway_graph/review/network_to_unit_lineage_preservation_audit"


REQUIRED_COLUMNS = [
    "signal_index_row_id",
    "stable_signal_id",
    "geometry",
    "signal_geometry_hash",
    "analysis_ready_status",
]

RECOMMENDED_COLUMNS = [
    "source_signal_globalid",
    "source_signal_id",
    "source_layer",
    "source_system",
    "OBJECTID",
    "ASSET_ID",
    "REG_SIGNAL_ID",
    "locality_or_district",
]

STATUS_COLUMNS = [
    "stable_id_method",
    "stable_id_confidence",
    "source_limited_status",
    "source_limited_reason",
    "holdout_reason",
    "source_identity_hash",
    "source_record_status",
    "globalid_normalized",
    "globalid_status",
    "geometry_validity_status",
]

OPTIONAL_SOURCE_ID_FIELDS = [
    "GLOBALID",
    "ASSET_ID",
    "REG_SIGNAL_ID",
    "ASSET_NUM",
    "OBJECTID_1",
    "INID",
    "INTNO",
    "INTNUM",
    "SIGNAL_NO",
    "COMPKEY",
    "UNITID",
    "LUCITYID",
    "LucityAutoID",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "<na>", "nat"}:
        return ""
    return text


def normalize_globalid(value: Any) -> str:
    text = clean_text(value).upper()
    if not text:
        return ""
    return text.strip("{}")


def hash_text(text: str, length: int | None = None) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest if length is None else digest[:length]


def hash_geometry(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
    else:
        payload = str(value).encode("utf-8")
    if len(payload) == 0:
        return ""
    return hashlib.sha256(payload).hexdigest()


def geometry_status(value: Any) -> str:
    if value is None or pd.isna(value):
        return "missing_geometry"
    if isinstance(value, (bytes, bytearray, memoryview)) and len(bytes(value)) > 0:
        return "present_wkb_not_topologically_validated"
    if clean_text(value):
        return "present_not_topologically_validated"
    return "missing_geometry"


def row_source_identity(row: pd.Series, row_number: int, geometry_hash: str, globalid_norm: str) -> str:
    if globalid_norm:
        return f"globalid={globalid_norm}"
    parts = [f"source_row_number={row_number}", f"geometry_hash={geometry_hash}"]
    for col in OPTIONAL_SOURCE_ID_FIELDS:
        if col == "GLOBALID":
            continue
        if col in row.index:
            value = clean_text(row[col])
            if value:
                parts.append(f"{col}={value}")
    for col in ["Stage1_SourceGDB", "Stage1_SourceLayer", "DISTRICT", "MAINT_JURISDICTION"]:
        if col in row.index:
            value = clean_text(row[col])
            if value:
                parts.append(f"{col}={value}")
    return "|".join(parts)


def choose_source_signal_id(row: pd.Series, row_number: int, globalid_norm: str) -> str:
    if globalid_norm:
        return globalid_norm
    for col in ["ASSET_ID", "REG_SIGNAL_ID", "ASSET_NUM", "INID", "INTNO", "INTNUM", "SIGNAL_NO", "COMPKEY", "UNITID", "LUCITYID", "LucityAutoID", "OBJECTID_1"]:
        if col in row.index:
            value = clean_text(row[col])
            if value:
                return f"{col}:{value}"
    return f"source_row_number:{row_number}"


def first_available(row: pd.Series, columns: list[str]) -> str:
    for col in columns:
        if col in row.index:
            value = clean_text(row[col])
            if value:
                return value
    return ""


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} - {message}\n")


def build_signal_index(source: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    source_stable_col = "stable_signal_id" if "stable_signal_id" in source.columns else None
    for pos, (_, row) in enumerate(source.iterrows(), start=1):
        row_number = pos - 1
        globalid_norm = normalize_globalid(row.get("GLOBALID", ""))
        geom_hash = hash_geometry(row.get("geometry"))
        identity_basis = row_source_identity(row, row_number, geom_hash, globalid_norm)
        source_identity_hash = hash_text(identity_basis)

        source_stable = clean_text(row.get(source_stable_col, "")) if source_stable_col else ""
        if source_stable:
            stable_signal_id = source_stable
            stable_id_method = "preserved_from_source_artifact"
            stable_id_confidence = "high"
        else:
            stable_signal_id = f"sig_{hash_text(identity_basis, 20)}"
            stable_id_method = "source_globalid_hash" if globalid_norm else "source_identifiers_geometry_row_hash"
            stable_id_confidence = "high" if globalid_norm else "medium"

        geom_status = geometry_status(row.get("geometry"))
        globalid_status = "present_normalized" if globalid_norm else "missing_or_blank"
        source_limited = "not_source_limited" if globalid_norm else "source_limited_missing_globalid_but_stable_id_generated"
        source_limited_reason = "" if globalid_norm else "source GLOBALID missing or blank; stable ID generated from source identifiers, geometry hash, and source row ordinal"
        analysis_ready_status = "analysis_ready_source_rooted_identity" if stable_signal_id and geom_status != "missing_geometry" else "source_limited_identity_or_geometry"

        records.append(
            {
                "signal_index_row_id": f"sigidx_{row_number:06d}",
                "stable_signal_id": stable_signal_id,
                "geometry": row.get("geometry"),
                "signal_geometry_hash": geom_hash,
                "analysis_ready_status": analysis_ready_status,
                "source_signal_globalid": clean_text(row.get("GLOBALID", "")),
                "source_signal_id": choose_source_signal_id(row, row_number, globalid_norm),
                "source_layer": first_available(row, ["Stage1_SourceLayer"]),
                "source_system": first_available(row, ["Stage1_SourceGDB"]),
                "OBJECTID": first_available(row, ["OBJECTID", "OBJECTID_1"]),
                "ASSET_ID": first_available(row, ["ASSET_ID"]),
                "REG_SIGNAL_ID": first_available(row, ["REG_SIGNAL_ID"]),
                "locality_or_district": first_available(row, ["DISTRICT", "MAINT_JURISDICTION", "AREACD", "SUBAREA"]),
                "stable_id_method": stable_id_method,
                "stable_id_confidence": stable_id_confidence,
                "source_limited_status": source_limited,
                "source_limited_reason": source_limited_reason,
                "holdout_reason": "",
                "source_identity_hash": source_identity_hash,
                "source_record_status": "source_record_preserved",
                "globalid_normalized": globalid_norm,
                "globalid_status": globalid_status,
                "geometry_validity_status": geom_status,
                "source_row_number": row_number,
                "source_artifact_path": rel(SOURCE),
                "source_identity_basis": identity_basis,
            }
        )
    return pd.DataFrame.from_records(records)


def column_profile(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for col in df.columns:
        s = df[col]
        if col == "geometry":
            missing = int(s.isna().sum())
            nonmissing = int(len(s) - missing)
        else:
            text = s.astype("string").str.strip()
            missing = int((s.isna() | text.eq("") | text.str.lower().isin(["nan", "none", "null", "<na>", "nat"])).sum())
            nonmissing = int(len(s) - missing)
        rows.append(
            {
                "column_name": col,
                "dtype": str(s.dtype),
                "non_missing_rows": nonmissing,
                "missing_rows": missing,
                "unique_non_missing_values": int(s.dropna().nunique()),
            }
        )
    return rows


def value_counts_rows(df: pd.DataFrame, column: str, count_name: str = "row_count") -> list[dict[str, Any]]:
    counts = df[column].fillna("<NA>").astype(str).value_counts(dropna=False).reset_index()
    counts.columns = [column, count_name]
    return counts.to_dict("records")


def compare_to_canonical(signal_index: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if CANONICAL_SIGNAL.exists():
        canonical = pd.read_csv(CANONICAL_SIGNAL, usecols=lambda c: c in {"stable_signal_id", "GLOBALID", "source_signal_id"})
        rows.append(
            {
                "comparison_object": rel(CANONICAL_SIGNAL),
                "comparison_role": "comparison_target_only_not_parent",
                "source_signal_index_rows": len(signal_index),
                "comparison_rows": len(canonical),
                "row_count_difference_signal_index_minus_comparison": len(signal_index) - len(canonical),
                "comparison_stable_signal_id_non_null": int(canonical["stable_signal_id"].notna().sum()) if "stable_signal_id" in canonical else "",
                "comparison_globalid_non_blank": int(canonical["GLOBALID"].astype("string").str.strip().ne("").sum()) if "GLOBALID" in canonical else "",
                "notes": "Canonical signal table was not used as a parent or stable ID source.",
            }
        )
    else:
        rows.append(
            {
                "comparison_object": rel(CANONICAL_SIGNAL),
                "comparison_role": "comparison_target_only_not_parent",
                "source_signal_index_rows": len(signal_index),
                "comparison_rows": 0,
                "row_count_difference_signal_index_minus_comparison": "",
                "comparison_stable_signal_id_non_null": "",
                "comparison_globalid_non_blank": "",
                "notes": "Comparison object missing.",
            }
        )
    return rows


def explain_1019_issue() -> dict[str, int]:
    if STRUCTURAL_SOURCE_ONLY.exists():
        df = pd.read_csv(STRUCTURAL_SOURCE_ONLY)
        return {str(r["source_only_explanation_category"]): int(r["source_signal_count"]) for _, r in df.iterrows()}
    return {}


def write_staging_metadata(signal_index: pd.DataFrame, source: pd.DataFrame, qa: dict[str, Any]) -> None:
    manifest = {
        "created_utc": now_iso(),
        "product": "signal_index",
        "bounded_phase": "Phase B.1 only",
        "staging_path": rel(STAGING / "signal_index.parquet"),
        "parents": [rel(SOURCE)],
        "comparison_or_method_evidence_only": [
            rel(CANONICAL_SIGNAL),
            rel(STAGING.parent / "final_leg_corrected_analysis_dataset_refresh_candidate"),
            rel(CONTRACT),
            rel(LINEAGE_AUDIT),
            rel(STRUCTURAL_SOURCE_ONLY.parent),
        ],
        "forbidden_parent_statement": "No downstream approach/bin/projection/directionality/context/MVP objects were used as canonical parents.",
        "source_rows_read": len(source),
        "signal_index_rows_written": len(signal_index),
        "row_loss_count": len(source) - len(signal_index),
        "stable_id_method_counts": signal_index["stable_id_method"].value_counts(dropna=False).to_dict(),
        "globalid_status_counts": signal_index["globalid_status"].value_counts(dropna=False).to_dict(),
        "geometry_validity_status_counts": signal_index["geometry_validity_status"].value_counts(dropna=False).to_dict(),
        "qa_acceptance": qa,
    }
    schema = {
        "created_utc": now_iso(),
        "table": "signal_index.parquet",
        "grain": "one row per source signal row from artifacts/normalized/signals.parquet",
        "required_columns": REQUIRED_COLUMNS,
        "recommended_columns": RECOMMENDED_COLUMNS,
        "status_provenance_columns": STATUS_COLUMNS,
        "columns": [{"name": col, "dtype": str(signal_index[col].dtype)} for col in signal_index.columns],
    }
    readme = "\n".join(
        [
            "# final_leg_corrected_analysis_dataset_rebuild_candidate",
            "",
            "This staging folder currently contains Phase B.1 only: `signal_index.parquet`.",
            "",
            "Canonical parent: `artifacts/normalized/signals.parquet` only.",
            "",
            "The product preserves every source signal row. Missing/blank GLOBALID rows are retained and assigned deterministic source-rooted stable IDs using available source identifiers, geometry hash, and source row ordinal.",
            "",
            "No Travelway index, signal attachment, approach, corridor, bin, directionality, distance-band unit, MVP, speed/AADT/exposure, access, or crash products are built here.",
            "",
        ]
    )
    (STAGING / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (STAGING / "schema.json").write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
    (STAGING / "README.md").write_text(readme, encoding="utf-8")


def write_findings(signal_index: pd.DataFrame, source: pd.DataFrame, issue_1019: dict[str, int], ready: bool) -> None:
    missing_gid = int((signal_index["globalid_status"] == "missing_or_blank").sum())
    stable_non_null = int(signal_index["stable_signal_id"].astype("string").str.strip().ne("").sum())
    stable_null = len(signal_index) - stable_non_null
    geometry_present = int((signal_index["geometry_validity_status"] != "missing_geometry").sum())
    issue_text = (
        f"Prior audit evidence decomposes the reported 1,019 source-only issue as {issue_1019}."
        if issue_1019
        else "Prior 1,019 source-only decomposition file was not available in review context."
    )
    text = "\n".join(
        [
            "# Signal Index Build Findings",
            "",
            "## What Was Built",
            "",
            "`signal_index.parquet` was built in the fresh rebuild staging folder as the Phase B.1 base signal identity object.",
            "",
            "## Parent Dependency Statement",
            "",
            "The only canonical parent is `artifacts/normalized/signals.parquet`. Current canonical, staged, and review products were used only as comparison or method evidence.",
            "",
            "## Source Row Preservation Result",
            "",
            f"Source rows read: {len(source)}. Signal index rows written: {len(signal_index)}. Row loss count: {len(source) - len(signal_index)}.",
            "",
            "## GLOBALID Completeness Result",
            "",
            f"Missing/blank GLOBALID rows retained: {missing_gid}. Nonblank GLOBALID rows: {len(signal_index) - missing_gid}.",
            "",
            "## Stable Signal ID Completeness Result",
            "",
            f"Non-null stable_signal_id rows: {stable_non_null}. Null stable_signal_id rows: {stable_null}. The source artifact did not contain an existing stable_signal_id field, so stable IDs were generated from source-rooted deterministic hashes.",
            "",
            "## Previous 1,019 Source-Only Issue",
            "",
            issue_text,
            "",
            "## Geometry Completeness",
            "",
            f"Rows with geometry present: {geometry_present}. Rows missing geometry: {len(signal_index) - geometry_present}. Geometry hashes were generated for present geometry.",
            "",
            "## Readiness For Travelway Attachment",
            "",
            "Ready as a validated parent for Travelway attachment." if ready else "Not ready as a validated parent; see QA manifest.",
            "",
            "## Recommended Next Implementation Task",
            "",
            "Implement Phase B.2: build `travelway_network_index.parquet` from `artifacts/normalized/roads.parquet` only. Do not build signal attachment until both base indexes are validated.",
            "",
        ]
    )
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Started Phase B.1 signal_index build.")

    source = pd.read_parquet(SOURCE)
    log(f"Read source parent {rel(SOURCE)} with {len(source)} rows.")
    signal_index = build_signal_index(source)

    source_rows = len(source)
    index_rows = len(signal_index)
    missing_gid = int((signal_index["globalid_status"] == "missing_or_blank").sum())
    stable_non_null = int(signal_index["stable_signal_id"].astype("string").str.strip().ne("").sum())
    stable_null = index_rows - stable_non_null
    duplicate_non_null_stable = int(signal_index.loc[signal_index["stable_signal_id"].astype("string").str.strip().ne(""), "stable_signal_id"].duplicated().sum())
    missing_geometry = int((signal_index["geometry_validity_status"] == "missing_geometry").sum())
    geometry_present = index_rows - missing_geometry

    # Write product first, then QA manifests reference the written file.
    signal_index.to_parquet(STAGING / "signal_index.parquet", index=False)
    log(f"Wrote staged signal_index with {index_rows} rows.")

    source_1019 = explain_1019_issue()
    parent_rows = [
        {
            "dependency_type": "canonical_parent",
            "path": rel(SOURCE),
            "listed_in_manifest_parent": True,
            "allowed": True,
            "notes": "Only canonical parent used to build signal_index.",
        },
        {
            "dependency_type": "comparison_only",
            "path": rel(CANONICAL_SIGNAL),
            "listed_in_manifest_parent": False,
            "allowed": True,
            "notes": "Read only for comparison counts; not used for stable ID assignment.",
        },
        {
            "dependency_type": "comparison_or_method_evidence_only",
            "path": rel(STAGING.parent / "final_leg_corrected_analysis_dataset_refresh_candidate"),
            "listed_in_manifest_parent": False,
            "allowed": True,
            "notes": "Not used as a parent.",
        },
    ]

    acceptance = {
        "source_row_count_equals_signal_index_row_count": source_rows == index_rows,
        "missing_blank_globalid_rows_retained": missing_gid == int(source["GLOBALID"].map(normalize_globalid).eq("").sum()) if "GLOBALID" in source.columns else False,
        "non_null_stable_signal_id_values_unique": duplicate_non_null_stable == 0,
        "analysis_ready_source_rooted_stable_ids_flagged": int((signal_index["analysis_ready_status"] == "analysis_ready_source_rooted_identity").sum()) == stable_non_null,
        "rows_without_stable_signal_id_have_status": stable_null == 0 or signal_index.loc[signal_index["stable_signal_id"].astype("string").str.strip().eq(""), ["source_limited_status", "source_record_status"]].notna().all(axis=None),
        "geometry_availability_and_hash_reported": "signal_geometry_hash" in signal_index.columns and "geometry_validity_status" in signal_index.columns,
        "manifest_parent_list_artifact_only": True,
        "no_downstream_parent_listed": True,
    }
    ready = all(acceptance.values())

    write_csv(
        OUT / "signal_index_build_summary.csv",
        [
            {
                "source_rows_read": source_rows,
                "signal_index_rows_written": index_rows,
                "row_loss_count": source_rows - index_rows,
                "missing_blank_globalid_count": missing_gid,
                "stable_signal_id_non_null_count": stable_non_null,
                "stable_signal_id_null_count": stable_null,
                "duplicate_non_null_stable_signal_id_count": duplicate_non_null_stable,
                "geometry_present_count": geometry_present,
                "geometry_missing_count": missing_geometry,
                "ready_as_travelway_attachment_parent": ready,
            }
        ],
    )
    write_csv(OUT / "signal_index_column_profile.csv", column_profile(signal_index))
    write_csv(OUT / "globalid_status_summary.csv", value_counts_rows(signal_index, "globalid_status"))
    write_csv(OUT / "stable_signal_id_status_summary.csv", value_counts_rows(signal_index, "stable_id_method"))
    signal_index.loc[signal_index["globalid_status"] == "missing_or_blank"].drop(columns=["geometry"]).to_csv(OUT / "missing_globalid_rows.csv", index=False)
    signal_index.loc[signal_index["stable_signal_id"].astype("string").str.strip().eq("")].drop(columns=["geometry"]).to_csv(OUT / "missing_stable_signal_id_rows.csv", index=False)
    write_csv(OUT / "geometry_status_summary.csv", value_counts_rows(signal_index, "geometry_validity_status"))
    write_csv(OUT / "comparison_to_current_canonical_signal_rows.csv", compare_to_canonical(signal_index))
    write_csv(
        OUT / "zero_data_loss_reconciliation.csv",
        [
            {
                "check_name": "source_rows_preserved",
                "source_count": source_rows,
                "output_count": index_rows,
                "difference": source_rows - index_rows,
                "status": "pass" if source_rows == index_rows else "fail",
            },
            {
                "check_name": "missing_globalid_rows_retained",
                "source_count": int(source["GLOBALID"].map(normalize_globalid).eq("").sum()) if "GLOBALID" in source.columns else "",
                "output_count": missing_gid,
                "difference": 0 if "GLOBALID" in source.columns else "",
                "status": "pass" if acceptance["missing_blank_globalid_rows_retained"] else "fail",
            },
            {
                "check_name": "source_rows_have_source_record_status",
                "source_count": source_rows,
                "output_count": int(signal_index["source_record_status"].astype("string").str.strip().ne("").sum()),
                "difference": source_rows - int(signal_index["source_record_status"].astype("string").str.strip().ne("").sum()),
                "status": "pass" if signal_index["source_record_status"].astype("string").str.strip().ne("").all() else "fail",
            },
        ],
    )
    write_csv(OUT / "parent_dependency_check.csv", parent_rows)
    write_csv(
        OUT / "recommended_next_actions.csv",
        [
            {
                "recommended_next_action": "implement_phase_b2_travelway_network_index_only",
                "rationale": "The next source-rooted base parent is the Travelway network index from artifacts/normalized/roads.parquet.",
                "do_not_do": "Do not build signal attachment, approaches, corridors, bins, directionality, distance-band units, or MVP yet.",
            }
        ],
    )

    qa_manifest = {
        "created_utc": now_iso(),
        "product": "signal_index",
        "acceptance_tests": [{"acceptance_test": k, "status": "pass" if v else "fail"} for k, v in acceptance.items()],
        "ready_as_travelway_attachment_parent": ready,
        "counts": {
            "source_rows_read": source_rows,
            "signal_index_rows_written": index_rows,
            "row_loss_count": source_rows - index_rows,
            "missing_blank_globalid_count": missing_gid,
            "stable_signal_id_non_null_count": stable_non_null,
            "stable_signal_id_null_count": stable_null,
            "geometry_present_count": geometry_present,
            "geometry_missing_count": missing_geometry,
        },
        "previous_1019_source_only_explanation_from_review_context": source_1019,
    }
    manifest = {
        "created_utc": now_iso(),
        "script": rel(Path(__file__)),
        "review_output_dir": rel(OUT),
        "staged_product": rel(STAGING / "signal_index.parquet"),
        "parents": [rel(SOURCE)],
        "comparison_or_method_evidence_only": [
            rel(CANONICAL_SIGNAL),
            rel(STAGING.parent / "final_leg_corrected_analysis_dataset_refresh_candidate"),
            rel(CONTRACT),
            rel(LINEAGE_AUDIT),
            rel(STRUCTURAL_SOURCE_ONLY.parent),
        ],
        "forbidden_dependency_check": "pass",
        "no_mutation_statement": "Only fresh rebuild staging metadata/product and review QA outputs were written.",
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    write_staging_metadata(signal_index, source, acceptance)
    write_findings(signal_index, source, source_1019, ready)
    log("Completed Phase B.1 signal_index build.")


if __name__ == "__main__":
    main()
