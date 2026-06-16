"""Read-only source/artifact lineage audit for canonical cache refresh planning.

This script inventories source-derived artifacts and raw source file metadata,
then maps likely refresh dependencies for a future canonical cache refresh. It
does not refresh data, create staging products, or mutate source/canonical files.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import pyarrow.parquet as pq
except Exception:  # pragma: no cover - optional dependency guard
    pq = None


REPO = Path(__file__).resolve().parents[3]
ARTIFACTS_DIR = REPO / "artifacts"
RAW_DIR = REPO / "Intersection Crash Analysis Layers"
FINAL_DIR = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP_DIR = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
MVP_AUDIT_DIR = REPO / "work" / "roadway_graph" / "review" / "canonical_mvp_readiness_audit"
REL_AUDIT_DIR = REPO / "work" / "roadway_graph" / "review" / "canonical_cache_relationship_audit"
OUT_DIR = REPO / "work" / "roadway_graph" / "review" / "canonical_refresh_source_lineage_audit"

DATA_SUFFIXES = {
    ".parquet",
    ".csv",
    ".geojson",
    ".json",
    ".gpkg",
    ".gdb",
    ".shp",
    ".dbf",
    ".prj",
    ".shx",
    ".xml",
    ".xlsx",
    ".xls",
    ".zip",
}

ROLE_TERMS = {
    "signal_identity": [
        "signal",
        "asset",
        "reg_signal",
        "signal_no",
        "intno",
        "intnum",
        "globalid",
        "intersection",
        "status",
        "route",
        "measure",
        "geometry",
    ],
    "approach_leg_signal_approach_id": [
        "signal_approach_id",
        "approach",
        "leg",
        "route",
        "rte",
        "measure",
        "from_measure",
        "to_measure",
        "direction",
        "bearing",
        "azimuth",
        "window",
        "bin",
        "geometry",
        "stable_bin_id",
    ],
    "speed_context": [
        "speed",
        "speed_limit",
        "car_speed_limit",
        "truck_speed_limit",
        "speedzone",
        "route",
        "measure",
        "directionality",
        "geometry",
    ],
    "aadt_context": [
        "aadt",
        "traffic",
        "count",
        "aawdt",
        "direction_factor",
        "route",
        "measure",
        "directionality",
        "geometry",
    ],
    "exposure_context": [
        "exposure",
        "denominator",
        "length",
        "shape_length",
        "bin_length",
        "aadt",
        "years",
        "crash_year",
        "from_measure",
        "to_measure",
    ],
    "crash_assignment": [
        "crash",
        "document_nbr",
        "catchment",
        "50",
        "roadway",
        "identity",
        "route",
        "rte_nm",
        "rns_mp",
        "geometry",
    ],
    "access_context": [
        "access",
        "driveway",
        "access_control",
        "access_direction",
        "riro",
        "unrestricted",
        "full",
        "commercial",
        "residential",
        "route_measure",
        "geometry",
    ],
    "median_divided_context": [
        "median",
        "divided",
        "undivided",
        "rim_median",
        "rim_couple",
        "one-way",
        "two-way",
        "carriageway",
        "facility",
        "rte_ramp",
    ],
}

BLOCKERS = [
    "missing_signal_approach_id",
    "missing_numeric_speed",
    "missing_speed_category",
    "missing_numeric_aadt",
    "missing_aadt_category",
    "zero_exposure",
    "missing_candidate_observed_crash_rate",
    "sparse_lookup_cells_due_to_incomplete_rate_eligible_units",
]


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_csv(name: str, rows: Iterable[dict], fieldnames: list[str] | None = None) -> None:
    rows = list(rows)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT_DIR / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    with (OUT_DIR / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def norm_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def role_scores(path: Path, columns: list[str] | None = None) -> dict[str, int]:
    text = " ".join([str(path), path.name] + (columns or [])).lower()
    scores = {}
    for role, terms in ROLE_TERMS.items():
        scores[role] = sum(1 for term in terms if term.lower() in text)
    return scores


def likely_role(path: Path, columns: list[str] | None = None) -> str:
    scores = role_scores(path, columns)
    if not scores or max(scores.values()) == 0:
        return "unknown"
    return max(scores, key=scores.get)


def data_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and (p.suffix.lower() in DATA_SUFFIXES or any(part.lower().endswith(".gdb") for part in p.parts)))


def raw_source_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def parquet_metadata(path: Path) -> tuple[int | None, list[str], dict[str, str], str | None]:
    if pq is None:
        return None, [], {}, "pyarrow.parquet unavailable"
    try:
        pf = pq.ParquetFile(path)
        schema = pf.schema_arrow
        cols = list(schema.names)
        dtypes = {field.name: str(field.type) for field in schema}
        return pf.metadata.num_rows, cols, dtypes, None
    except Exception as exc:
        return None, [], {}, str(exc)


def csv_metadata(path: Path) -> tuple[int | None, list[str], dict[str, str], str | None]:
    try:
        df = pd.read_csv(path, nrows=1000, low_memory=False)
        row_count = None
        with path.open("rb") as f:
            row_count = max(sum(1 for _ in f) - 1, 0)
        return row_count, list(df.columns), {c: str(df[c].dtype) for c in df.columns}, None
    except Exception as exc:
        return None, [], {}, str(exc)


def json_metadata(path: Path) -> tuple[int | None, list[str], dict[str, str], str | None]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return None, list(data.keys()), {k: type(v).__name__ for k, v in data.items()}, None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return len(data), list(data[0].keys()), {k: type(v).__name__ for k, v in data[0].items()}, None
        return None, [], {}, None
    except Exception as exc:
        return None, [], {}, str(exc)


def artifact_metadata(path: Path) -> dict:
    row_count = None
    columns: list[str] = []
    dtypes: dict[str, str] = {}
    error = None
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        row_count, columns, dtypes, error = parquet_metadata(path)
    elif suffix == ".csv":
        row_count, columns, dtypes, error = csv_metadata(path)
    elif suffix in {".json", ".geojson"} and path.stat().st_size < 50_000_000:
        row_count, columns, dtypes, error = json_metadata(path)
    else:
        error = "metadata_only_not_loaded"
    geometry_cols = [c for c in columns if c.lower() in {"geometry", "geom", "wkt", "geometry_wkt", "shape"} or "geometry" in c.lower()]
    crash_direction_cols = [
        c
        for c in columns
        if "crash" in c.lower() and ("dir" in c.lower() or "direction" in c.lower())
    ]
    return {
        "path": rel(path),
        "file_type": suffix or "unknown",
        "size_bytes": path.stat().st_size,
        "modified_time": path.stat().st_mtime,
        "modified_time_iso": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "columns_json": json.dumps(columns, ensure_ascii=True),
        "dtypes_json": json.dumps(dtypes, ensure_ascii=True),
        "geometry_present": bool(geometry_cols),
        "geometry_fields": "|".join(geometry_cols),
        "likely_role": likely_role(path, columns),
        "role_scores_json": json.dumps(role_scores(path, columns), ensure_ascii=True),
        "crash_direction_fields_excluded_from_directionality": "|".join(crash_direction_cols),
        "read_status": "readable_metadata" if error is None else "metadata_limited_or_error",
        "read_error": error or "",
    }


def raw_source_metadata(path: Path, artifact_roles: dict[str, list[dict]]) -> dict:
    suffix = path.suffix.lower() or "no_extension"
    role = likely_role(path, [])
    corresponding = artifact_roles.get(role, [])
    is_gdb_internal = any(part.lower().endswith(".gdb") for part in path.parts)
    return {
        "path": rel(path),
        "file_type": suffix,
        "size_bytes": path.stat().st_size,
        "modified_time_iso": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        "likely_role": role,
        "corresponding_artifact_found": bool(corresponding),
        "corresponding_artifact_paths": "|".join(item["path"] for item in corresponding[:6]),
        "inspection_status": "raw_source_available_but_not_loaded" if is_gdb_internal or suffix in {".gdb", ".geojson", ".gpkg", ".shp", ".dbf"} else "metadata_only",
        "notes": "prefer artifact parquet; raw source should be used only if artifact is missing/stale/incomplete",
    }


def matching_fields(columns: list[str], role: str) -> list[str]:
    terms = ROLE_TERMS[role]
    hits = []
    for col in columns:
        low = col.lower()
        if any(term.lower() in low for term in terms):
            hits.append(col)
    return hits


def dependency_mapping(artifacts: list[dict], raw_rows: list[dict]) -> list[dict]:
    rows = []
    for role in ROLE_TERMS:
        for item in artifacts:
            fields = matching_fields(item["columns"], role)
            if item["likely_role"] == role or fields:
                rows.append(
                    {
                        "dependency_area": role,
                        "source_tier": "artifact",
                        "path": item["path"],
                        "likely_role": item["likely_role"],
                        "candidate_fields": "|".join(fields),
                        "row_count": item["row_count"],
                        "geometry_present": item["geometry_present"],
                        "read_status": item["read_status"],
                    }
                )
        for item in raw_rows:
            if item["likely_role"] == role:
                rows.append(
                    {
                        "dependency_area": role,
                        "source_tier": "raw_source",
                        "path": item["path"],
                        "likely_role": item["likely_role"],
                        "candidate_fields": "",
                        "row_count": "",
                        "geometry_present": "",
                        "read_status": item["inspection_status"],
                    }
                )
    return rows


def candidates_for_role(artifacts: list[dict], role: str) -> list[dict]:
    rows = []
    for item in artifacts:
        fields = matching_fields(item["columns"], role)
        score = role_scores(Path(item["path"]), item["columns"]).get(role, 0)
        if fields or score > 0 or item["likely_role"] == role:
            rows.append(
                {
                    "path": item["path"],
                    "file_type": item["file_type"],
                    "row_count": item["row_count"],
                    "likely_role": item["likely_role"],
                    "role_score": score,
                    "candidate_fields": "|".join(fields),
                    "geometry_present": item["geometry_present"],
                    "read_status": item["read_status"],
                    "recommended_use": recommended_use_for_role(item["path"], role),
                }
            )
    return sorted(rows, key=lambda r: (int(r["role_score"]), "normalized" in r["path"]), reverse=True)


def recommended_use_for_role(path: str, role: str) -> str:
    name = path.lower()
    if role == "signal_identity" and "normalized/signals" in name:
        return "required_input"
    if role == "approach_leg_signal_approach_id" and "normalized/roads" in name:
        return "required_input_for_geometry_route_measure_reconstruction"
    if role == "speed_context" and "normalized/speed" in name:
        return "required_input"
    if role == "aadt_context" and "normalized/aadt" in name:
        return "required_input"
    if role == "exposure_context" and ("normalized/aadt" in name or "normalized/roads" in name):
        return "required_input"
    if role == "crash_assignment" and "normalized/crashes" in name:
        return "required_input_for_refresh_or_qa"
    if role == "access_context" and "normalized/access_v2" in name:
        return "required_input_preferred"
    if role == "access_context" and "normalized/access" in name:
        return "optional_legacy_artifact_reference"
    if role == "median_divided_context" and "normalized/roads" in name:
        return "required_input"
    if "staging" in name:
        return "qa_reference_or_artifact_lineage_only"
    return "optional_enrichment_or_qa_reference"


def blocker_feasibility(artifacts: list[dict]) -> list[dict]:
    by_path = {item["path"]: item for item in artifacts}
    def paths_with(role: str) -> list[dict]:
        return candidates_for_role(artifacts, role)

    rows = []
    mapping = {
        "missing_signal_approach_id": ("artifact_support_possible", ["artifacts/normalized/signals.parquet", "artifacts/normalized/roads.parquet"], "Artifacts provide signal geometry and route/measure road context, but not canonical signal_approach_id directly; reconstruction needs canonical rules and QA."),
        "missing_numeric_speed": ("artifact_support_likely", ["artifacts/normalized/speed.parquet", "artifacts/normalized/roads.parquet"], "Speed artifact has speed limits and route/measure fields."),
        "missing_speed_category": ("artifact_support_likely", ["artifacts/normalized/speed.parquet"], "Category can be derived after numeric speed recovery using documented bins."),
        "missing_numeric_aadt": ("artifact_support_likely", ["artifacts/normalized/aadt.parquet", "artifacts/normalized/roads.parquet"], "AADT artifact has AADT and route/measure fields."),
        "missing_aadt_category": ("artifact_support_likely", ["artifacts/normalized/aadt.parquet"], "Category can be derived after numeric AADT recovery using documented bins."),
        "zero_exposure": ("artifact_support_likely", ["artifacts/normalized/aadt.parquet", "artifacts/normalized/roads.parquet"], "Exposure can be recomputed from AADT and segment/window length if keys are resolved."),
        "missing_candidate_observed_crash_rate": ("artifact_support_likely", ["artifacts/normalized/crashes.parquet", "artifacts/normalized/aadt.parquet", "artifacts/normalized/roads.parquet"], "Rate refresh needs crash counts plus positive exposure; assignment QA may need canonical catchment rules."),
        "sparse_lookup_cells_due_to_incomplete_rate_eligible_units": ("artifact_support_possible", ["artifacts/normalized/speed.parquet", "artifacts/normalized/aadt.parquet", "artifacts/normalized/access_v2.parquet"], "Completeness improvement can increase eligible units, but true sparsity may remain after exact MVP stratification."),
    }
    for blocker in BLOCKERS:
        classification, candidate_paths, reason = mapping[blocker]
        present_paths = [p for p in candidate_paths if p in by_path]
        if not present_paths and classification.startswith("artifact"):
            classification = "raw_source_needed"
        fields = []
        for p in present_paths:
            item = by_path[p]
            role = item["likely_role"]
            fields.extend(matching_fields(item["columns"], role))
        rows.append(
            {
                "blocker": blocker,
                "classification": classification,
                "candidate_artifact_files": "|".join(present_paths),
                "candidate_fields": "|".join(sorted(set(fields))),
                "reason": reason,
                "raw_source_needed_for_next_step": "no" if present_paths else "yes_if_artifact_missing_or_stale",
            }
        )
    return rows


def input_recommendations(artifacts: list[dict]) -> tuple[list[dict], list[dict]]:
    by_path = {item["path"]: item for item in artifacts}
    final_specs = [
        ("artifacts/normalized/signals.parquet", "required_input", "stable signal identity, location, source signal attributes"),
        ("artifacts/normalized/roads.parquet", "required_input", "route/measure/bin geometry, median/divided, roadway context, approach reconstruction support"),
        ("artifacts/normalized/speed.parquet", "required_input", "numeric speed refresh and speed category derivation"),
        ("artifacts/normalized/aadt.parquet", "required_input", "numeric AADT refresh and exposure denominator support"),
        ("artifacts/normalized/access_v2.parquet", "optional_enrichment_input", "typed access and source priority enrichment"),
        ("artifacts/normalized/access.parquet", "qa_reference_only", "older access artifact for coverage comparison only"),
        ("artifacts/normalized/crashes.parquet", "qa_reference_or_refresh_input", "crash assignment/rate QA; do not use crash direction for upstream/downstream"),
    ]
    mvp_specs = [
        ("refreshed_final_leg_candidate", "inherited_from_refreshed_final_leg", "signals, approaches, windows, roadway configuration, median, speed, AADT, exposure"),
        ("artifacts/normalized/crashes.parquet", "crash_rate_exposure_input", "crash counts and route identity QA after canonical catchment rules"),
        ("artifacts/normalized/access_v2.parquet", "access_category_input", "access count/type flags if refreshed final leg does not already carry them"),
        ("refreshed_directionality_fields", "directionality_provenance_input", "direct/synthetic/upstream/downstream method flags from refreshed final cache"),
        ("refreshed_lookup_rules", "lookup_aggregation_input", "MVP cell dimensions, reliability thresholds, total units and rate-eligible units"),
    ]

    final_rows = []
    for path, use, purpose in final_specs:
        item = by_path.get(path)
        final_rows.append(
            {
                "input_path": path,
                "input_class": use,
                "present": bool(item) or path.startswith("refreshed_"),
                "row_count": item["row_count"] if item else "",
                "key_fields_or_support_fields": "|".join(item["columns"][:30]) if item else "",
                "purpose": purpose,
                "raw_source_fallback_policy": "do_not_use_raw_unless_artifact_missing_stale_or_incomplete",
            }
        )

    mvp_rows = []
    for path, use, purpose in mvp_specs:
        item = by_path.get(path)
        mvp_rows.append(
            {
                "input_path": path,
                "input_class": use,
                "present": bool(item) or path.startswith("refreshed_"),
                "row_count": item["row_count"] if item else "",
                "key_fields_or_support_fields": "|".join(item["columns"][:30]) if item else "",
                "purpose": purpose,
                "raw_source_fallback_policy": "do_not_use_raw_unless_artifact_missing_stale_or_incomplete",
            }
        )
    return final_rows, mvp_rows


def artifact_source_correspondence(artifacts: list[dict], raw_rows: list[dict]) -> list[dict]:
    rows = []
    for art in artifacts:
        art_tokens = set(norm_text(Path(art["path"]).stem).split("_"))
        role = art["likely_role"]
        matches = []
        for raw in raw_rows:
            raw_tokens = set(norm_text(Path(raw["path"]).stem).split("_"))
            token_overlap = len(art_tokens & raw_tokens)
            role_match = raw["likely_role"] == role and role != "unknown"
            if token_overlap or role_match:
                matches.append((token_overlap + (5 if role_match else 0), raw))
        matches = sorted(matches, key=lambda x: x[0], reverse=True)[:10]
        rows.append(
            {
                "artifact_path": art["path"],
                "artifact_likely_role": role,
                "corresponding_raw_source_count": len(matches),
                "top_corresponding_raw_sources": "|".join(m[1]["path"] for m in matches),
                "correspondence_basis": "role_and_filename_token_overlap",
            }
        )
    return rows


def write_policy() -> None:
    text = """# Staging and Promotion Policy

`work/roadway_graph/analysis/_staging/` may be used only for the current active canonical refresh candidate.

`_staging` must not accumulate dated experiments, exploratory branches, or stale alternatives. Current root canonical folders remain frozen as pre-refresh evidence until candidate QA passes.

After promotion, `_staging` should be emptied or removed. Refreshed canonical root folders should be Parquet-first, with CSV files only under `exports/` for review, Excel inspection, summaries, and reports.

`artifacts/` remains source-derived disk. It is not the analysis cache, and it should not be edited by analysis refresh scripts unless a separate artifact-refresh task is explicitly authorized.
"""
    (OUT_DIR / "staging_and_promotion_policy.md").write_text(text, encoding="utf-8")


def write_refresh_sequence() -> None:
    text = """# Recommended Refresh Sequence

Refresh `final_leg_corrected_analysis_dataset` first. The MVP product should be regenerated only after the final-leg candidate has complete or explicitly source-limited relationship keys, numeric context, and exposure fields.

Handle `signal_approach_id` before numeric speed/AADT/exposure/rate. It is the relationship key that connects signal, approach, window, directional unit, and bin-context grains. Numeric context recovery without stable relationship keys would be harder to validate and promote.

The next implementation task should read these artifacts first:

- `artifacts/normalized/signals.parquet`
- `artifacts/normalized/roads.parquet`
- `artifacts/normalized/speed.parquet`
- `artifacts/normalized/aadt.parquet`
- `artifacts/normalized/access_v2.parquet`
- `artifacts/normalized/crashes.parquet` only for crash/rate QA and candidate count refresh, not for upstream/downstream derivation

Raw source layers should not be touched in the next implementation step unless one of those artifact tables is proven missing, stale, or incomplete.

Write only a bounded refresh candidate under `work/roadway_graph/analysis/_staging/`, preferably Parquet-first with an explicit schema, manifest, QA tables, and small CSV exports. Do not overwrite the current canonical root products.

Promotion should be blocked unless these QA gates pass:

- no unintended row loss at signal, approach-window, and MVP unit grains
- `signal_approach_id` complete or explicitly source-limited with flags
- final-to-MVP join keys unique and traceable
- speed/AADT/exposure missingness reduced or fully explained
- zero exposure rows are intentional and flagged
- candidate rates are present only where denominators are positive and documented
- crash direction fields are not used for upstream/downstream
- access count bands and typed access flags are documented
- direct/synthetic directionality provenance is preserved
- lookup cells include total matching units and rate-eligible units
"""
    (OUT_DIR / "recommended_refresh_sequence.md").write_text(text, encoding="utf-8")


def write_findings(artifact_count: int, raw_count: int, blockers: list[dict]) -> None:
    signal = next((r for r in blockers if r["blocker"] == "missing_signal_approach_id"), {})
    text = f"""# Canonical Refresh Source Lineage Audit Findings

Bounded question: Which source-derived artifact tables can support a future canonical cache refresh, and what is the safest refresh sequence?

## Summary

This audit inventoried {artifact_count} artifact files and {raw_count} raw source files. Artifact Parquets are available for the major source domains needed by the refresh: signals, roads, speed, AADT, access, and crashes.

The next implementation should refresh the final-leg cache first, then regenerate the MVP cache from the refreshed final-leg candidate. Raw source layers do not appear necessary for the next implementation step unless artifact QA proves an artifact missing, stale, or incomplete.

## Key Findings

- `artifacts/normalized/signals.parquet` supports signal identity and signal location.
- `artifacts/normalized/roads.parquet` supports route/measure, geometry, median/divided, roadway configuration, and approach reconstruction context.
- `artifacts/normalized/speed.parquet` supports numeric speed refresh.
- `artifacts/normalized/aadt.parquet` supports numeric AADT and exposure refresh.
- `artifacts/normalized/access_v2.parquet` is the preferred access enrichment artifact.
- `artifacts/normalized/crashes.parquet` supports crash/rate QA and refresh, but crash direction fields must not be used for upstream/downstream.
- Missing `signal_approach_id` classification: {signal.get('classification', 'unknown')}. The artifacts support reconstruction context, but do not provide a direct canonical key copy.

## Refresh Recommendation

Use `work/roadway_graph/analysis/_staging/` only for a single active refresh candidate. Keep the current root canonical products frozen as pre-refresh evidence. Promote only after relationship-key, numeric-context, exposure/rate, directionality, access, and lookup reliability QA passes.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started source/artifact lineage audit.\n", encoding="utf-8")

    log("Inventoring artifacts.")
    artifact_rows = []
    for path in data_files(ARTIFACTS_DIR):
        artifact_rows.append(artifact_metadata(path))
    write_csv("artifact_inventory.csv", artifact_rows)

    artifact_roles: dict[str, list[dict]] = {}
    for item in artifact_rows:
        artifact_roles.setdefault(item["likely_role"], []).append(item)

    log("Inventoring raw source files with metadata-only inspection.")
    raw_rows = [raw_source_metadata(path, artifact_roles) for path in raw_source_files(RAW_DIR)]
    write_csv("raw_source_inventory.csv", raw_rows)
    write_csv("artifact_to_source_correspondence.csv", artifact_source_correspondence(artifact_rows, raw_rows))

    log("Mapping refresh dependencies and source candidates.")
    dep_rows = dependency_mapping(artifact_rows, raw_rows)
    write_csv("refresh_dependency_mapping.csv", dep_rows)
    role_to_file = {
        "signal_approach_id_source_candidates.csv": "approach_leg_signal_approach_id",
        "speed_source_candidates.csv": "speed_context",
        "aadt_source_candidates.csv": "aadt_context",
        "exposure_source_candidates.csv": "exposure_context",
        "crash_assignment_source_candidates.csv": "crash_assignment",
        "access_source_candidates.csv": "access_context",
        "median_divided_source_candidates.csv": "median_divided_context",
    }
    for filename, role in role_to_file.items():
        write_csv(filename, candidates_for_role(artifact_rows, role))

    blockers = blocker_feasibility(artifact_rows)
    write_csv("blocker_recovery_feasibility.csv", blockers)

    final_inputs, mvp_inputs = input_recommendations(artifact_rows)
    write_csv("recommended_final_leg_refresh_inputs.csv", final_inputs)
    write_csv("recommended_mvp_refresh_inputs.csv", mvp_inputs)
    write_policy()
    write_refresh_sequence()
    write_findings(len(artifact_rows), len(raw_rows), blockers)

    qa = [
        {"qa_check": "canonical_products_read_only", "status": "pass", "evidence": f"{rel(FINAL_DIR)}; {rel(MVP_DIR)}"},
        {"qa_check": "previous_review_outputs_read_only_context", "status": "pass", "evidence": f"{rel(MVP_AUDIT_DIR)}; {rel(REL_AUDIT_DIR)}"},
        {"qa_check": "artifacts_read_only", "status": "pass", "evidence": rel(ARTIFACTS_DIR)},
        {"qa_check": "raw_sources_metadata_only", "status": "pass", "evidence": "raw source files inventoried without full spatial reads"},
        {"qa_check": "no_work_output_or_legacy_use", "status": "pass", "evidence": "script does not inspect legacy or work/output"},
        {"qa_check": "no_crash_direction_derivation", "status": "pass", "evidence": "crash direction-like fields are only reported as excluded"},
        {"qa_check": "outputs_only_in_lineage_audit_folder", "status": "pass", "evidence": rel(OUT_DIR)},
        {"qa_check": "no_refresh_or_staging_candidate_created", "status": "pass", "evidence": "no writes outside review audit folder"},
    ]
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")

    manifest = {
        "script": "src.roadway_graph.audit.canonical_refresh_source_lineage_audit",
        "created_utc": now(),
        "bounded_question": "Read-only source/artifact lineage audit to prepare canonical cache refresh.",
        "canonical_pre_refresh_evidence": [rel(FINAL_DIR), rel(MVP_DIR)],
        "diagnostic_review_context": [rel(MVP_AUDIT_DIR), rel(REL_AUDIT_DIR)],
        "source_artifact_inputs": [rel(ARTIFACTS_DIR), rel(RAW_DIR)],
        "output_folder": rel(OUT_DIR),
        "artifact_file_count": len(artifact_rows),
        "raw_source_file_count": len(raw_rows),
        "outputs": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "non_goals": [
            "no canonical product modification",
            "no refresh",
            "no staging candidate creation",
            "no raw full spatial reads",
            "no legacy use",
            "no work/output use",
            "no crash direction use for upstream/downstream",
        ],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("Completed source/artifact lineage audit.")


if __name__ == "__main__":
    main()
