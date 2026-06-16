"""Regenerate roadway_graph _index and audit source-to-artifact coverage.

Outputs are written only under work/roadway_graph/_index. This script does not
mutate source layers, artifacts, analysis products, review outputs, or cache
parquets.
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
import pyarrow.parquet as pq
import pyogrio


REPO = Path(__file__).resolve().parents[3]
WORK_RG = REPO / "work/roadway_graph"
INDEX = WORK_RG / "_index"
CURRENT = INDEX / "current"
COVERAGE = INDEX / "source_artifact_coverage"
FINAL_DECISION = INDEX / "final_decision.json"
RECOMMENDED = INDEX / "recommended_next_actions.csv"
ANALYSIS = WORK_RG / "analysis"
REPORT = WORK_RG / "report"
CACHE = ANALYSIS / "final_dataset_cache"
SUMMARIES = ANALYSIS / "final_summaries"
MVP = ANALYSIS / "mvp_dataset"
SOURCE = REPO / "Intersection Crash Analysis Layers"
ARTIFACTS = REPO / "artifacts"
NORMALIZED = ARTIFACTS / "normalized"
STAGING = ARTIFACTS / "staging"

EXPECTED_CACHE_PARQUETS = [
    "signal_index.parquet",
    "travelway_network_index.parquet",
    "signal_travelway_attachment.parquet",
    "signal_approaches.parquet",
    "approach_corridors.parquet",
    "bin_context.parquet",
    "distance_band_units.parquet",
    "distance_band_context.parquet",
]
EXPECTED_CACHE_METADATA = ["manifest.json", "schema.json", "README.md"]
EXPECTED_WORK_FOLDERS = {"_index", "analysis", "report"}
EXPECTED_ANALYSIS_FOLDERS = {"final_dataset_cache", "final_summaries", "mvp_dataset"}
ROLE_ARTIFACT_HINTS = {
    "signals": ["signals.parquet"],
    "roads/travelway": ["roads.parquet"],
    "speed": ["speed.parquet"],
    "AADT": ["aadt.parquet"],
    "access typed": ["access_v2.parquet"],
    "access untyped": ["access.parquet"],
    "crashes": ["crashes.parquet"],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def log(message: str) -> None:
    print(f"[{now()}] {message}", flush=True)


def clean_cols(cols: list[str]) -> list[str]:
    return [str(c) for c in cols]


def parquet_info(path: Path) -> dict[str, Any]:
    pf = pq.ParquetFile(path)
    cols = clean_cols(pf.schema_arrow.names)
    metadata = pf.schema_arrow.metadata or {}
    meta_text = {k.decode(errors="ignore"): v.decode(errors="ignore")[:500] for k, v in metadata.items()}
    return {
        "row_count": int(pf.metadata.num_rows),
        "column_count": len(cols),
        "columns": cols,
        "schema_metadata": meta_text,
    }


def classified_cols(cols: list[str]) -> dict[str, list[str]]:
    lower = {c.lower(): c for c in cols}
    id_tokens = ("id", "globalid", "objectid", "document_nbr", "signal", "travelway", "crash")
    route_tokens = ("route", "rte", "edge_rte", "linkid")
    measure_tokens = ("measure", "mp", "mile", "begin", "end")
    date_tokens = ("date", "year", "yr", "dt")
    geometry_tokens = ("geometry", "wkb", "wkt", "geom", "shape")
    return {
        "id_fields": [c for c in cols if any(t in c.lower() for t in id_tokens)],
        "route_fields": [c for c in cols if any(t in c.lower() for t in route_tokens)],
        "measure_fields": [c for c in cols if any(t in c.lower() for t in measure_tokens)],
        "date_year_fields": [c for c in cols if any(t in c.lower() for t in date_tokens)],
        "geometry_fields": [c for c in cols if any(t in c.lower() for t in geometry_tokens)],
        "lineage_fields": [c for c in cols if any(t in c.lower() for t in ("source", "artifact", "layer", "path", "lineage"))],
    }


def guess_role(name: str, fields: list[str]) -> str:
    text = (name + " " + " ".join(fields)).lower()
    if "access.parquet" in text and "access_v2.parquet" not in text:
        return "access untyped"
    if "accesspoints.gdb" in text:
        return "access untyped"
    if "access_v2.parquet" in text:
        return "access typed"
    if any(t in text for t in ("accesspoints", "layer_lrspoint", "layer_point", "access.parquet", "access_v2.parquet", "access_control", "access_direction")):
        if any(t in text for t in ("access_v2", "layer_lrspoint", "layer_point", "type", "riro", "review", "code", "access_control")):
            return "access typed"
        return "access untyped"
    if any(t in text for t in ("crash", "document_nbr")):
        return "crashes"
    if any(t in text for t in ("aadt", "traffic_volume", "direction_factor")):
        return "AADT"
    if any(t in text for t in ("speed", "posted")):
        return "speed"
    if any(t in text for t in ("signal", "hmms")):
        return "signals"
    if any(t in text for t in ("travelway", "roads", "routes", "rte_nm", "rim_")):
        return "roads/travelway"
    return "other/unknown"


def gate1_index() -> tuple[str, dict[str, Any]]:
    log("Gate 1: regenerating current roadway_graph index")
    CURRENT.mkdir(parents=True, exist_ok=True)
    work_rows = []
    if not WORK_RG.exists():
        return "index_regeneration_failed_stop", {"reason": "work/roadway_graph missing"}
    for child in sorted(WORK_RG.iterdir(), key=lambda p: p.name.lower()):
        if child.is_dir():
            file_count = sum(1 for p in child.rglob("*") if p.is_file())
            total_size = sum(p.stat().st_size for p in child.rglob("*") if p.is_file())
            work_rows.append(
                {
                    "folder": child.name,
                    "path": rel(child),
                    "file_count": file_count,
                    "total_size_bytes": total_size,
                    "expected_current_folder": child.name in EXPECTED_WORK_FOLDERS,
                    "unexpected_populated_folder": child.name not in EXPECTED_WORK_FOLDERS and file_count > 0,
                }
            )
    write_csv(CURRENT / "current_work_roadway_graph_inventory.csv", work_rows)

    unexpected = [r for r in work_rows if r["unexpected_populated_folder"]]
    write_csv(CURRENT / "unexpected_work_folders_check.csv", unexpected or [{"check": "no_unexpected_populated_folders", "passed": True}])

    analysis_rows = []
    for child in sorted(ANALYSIS.iterdir(), key=lambda p: p.name.lower()) if ANALYSIS.exists() else []:
        if child.is_dir():
            file_count = sum(1 for p in child.rglob("*") if p.is_file())
            total_size = sum(p.stat().st_size for p in child.rglob("*") if p.is_file())
            analysis_rows.append(
                {
                    "folder": child.name,
                    "path": rel(child),
                    "file_count": file_count,
                    "total_size_bytes": total_size,
                    "expected_current_analysis_product": child.name in EXPECTED_ANALYSIS_FOLDERS,
                }
            )
    write_csv(CURRENT / "current_analysis_folder_inventory.csv", analysis_rows)

    cache_rows = []
    cache_ok = CACHE.exists()
    for name in EXPECTED_CACHE_PARQUETS:
        path = CACHE / name
        row: dict[str, Any] = {"file_name": name, "path": rel(path), "exists": path.exists()}
        try:
            info = parquet_info(path)
            row.update(
                {
                    "readable": True,
                    "row_count": info["row_count"],
                    "column_count": info["column_count"],
                    "size_bytes": path.stat().st_size,
                    "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                    "sha256": sha256(path),
                }
            )
        except Exception as exc:
            row.update({"readable": False, "error": f"{type(exc).__name__}:{exc}"})
            cache_ok = False
        cache_rows.append(row)
    for name in EXPECTED_CACHE_METADATA:
        path = CACHE / name
        row = {"file_name": name, "path": rel(path), "exists": path.exists(), "size_bytes": path.stat().st_size if path.exists() else ""}
        try:
            if name.endswith(".json"):
                json.loads(path.read_text(encoding="utf-8"))
            else:
                path.read_text(encoding="utf-8")
            row["readable"] = True
            row["sha256"] = sha256(path)
        except Exception as exc:
            row["readable"] = False
            row["error"] = f"{type(exc).__name__}:{exc}"
            cache_ok = False
        cache_rows.append(row)
    write_csv(CURRENT / "final_dataset_cache_index.csv", cache_rows)

    def simple_inventory(folder: Path, expected_no_core: bool = False) -> list[dict[str, Any]]:
        rows = []
        if not folder.exists():
            return [{"path": rel(folder), "exists": False}]
        for path in sorted(folder.rglob("*"), key=lambda p: rel(p).lower()):
            if path.is_file():
                rows.append(
                    {
                        "path": rel(path),
                        "file_name": path.name,
                        "extension": path.suffix.lower(),
                        "size_bytes": path.stat().st_size,
                        "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                        "core_cache_parquet_flag": path.name in EXPECTED_CACHE_PARQUETS,
                        "parquet_flag": path.suffix.lower() == ".parquet",
                        "expected_lightweight": expected_no_core,
                    }
                )
        return rows

    summaries_rows = simple_inventory(SUMMARIES, expected_no_core=True)
    mvp_rows = simple_inventory(MVP, expected_no_core=False)
    write_csv(CURRENT / "final_summaries_index.csv", summaries_rows)
    write_csv(CURRENT / "mvp_dataset_index.csv", mvp_rows)

    summaries_ok = SUMMARIES.exists() and not any(r.get("core_cache_parquet_flag") for r in summaries_rows)
    mvp_ok = MVP.exists() and not any(r.get("core_cache_parquet_flag") for r in mvp_rows)
    decision = "index_regenerated_ready_for_source_artifact_audit" if cache_ok and summaries_ok and mvp_ok else "index_regeneration_failed_stop"
    manifest = {
        "created_utc": now(),
        "decision": decision,
        "current_work_roadway_graph_folders": work_rows,
        "final_dataset_cache_canonical": cache_ok,
        "final_summaries_lightweight": summaries_ok,
        "mvp_dataset_development_product": mvp_ok,
        "unexpected_populated_work_folders": unexpected,
    }
    write_json(CURRENT / "roadway_graph_current_state_manifest.json", manifest)
    readme = f"""# roadway_graph Current State

Generated UTC: {now()}

`final_dataset_cache` exists and is treated as the canonical core cache: {cache_ok}.

`final_summaries` exists and is lightweight with no core cache parquet objects: {summaries_ok}.

`mvp_dataset` exists as a first MVP development product and does not contain copied core cache parquets: {mvp_ok}.

Unexpected populated folders under `work/roadway_graph`: {', '.join(r['folder'] for r in unexpected) if unexpected else 'none'}.

Gate 1 decision: `{decision}`.
"""
    (CURRENT / "roadway_graph_current_state_readme.md").write_text(readme, encoding="utf-8")
    return decision, manifest


def list_source_layers() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    folder_rows = []
    layer_rows = []
    schema_rows = []
    if not SOURCE.exists():
        return [{"path": rel(SOURCE), "exists": False}], [], [], []
    for item in sorted(SOURCE.iterdir(), key=lambda p: p.name.lower()):
        folder_rows.append(
            {
                "path": rel(item),
                "name": item.name,
                "extension": item.suffix.lower(),
                "is_dir": item.is_dir(),
                "size_bytes": sum(p.stat().st_size for p in item.rglob("*") if p.is_file()) if item.is_dir() else item.stat().st_size,
                "modified_utc": datetime.fromtimestamp(item.stat().st_mtime, timezone.utc).isoformat(),
            }
        )
    source_datasets = list(SOURCE.rglob("*.gdb")) + list(SOURCE.glob("*.geojson"))
    for ds in sorted(source_datasets, key=lambda p: rel(p).lower()):
        try:
            if ds.suffix.lower() == ".gdb":
                layers = pyogrio.list_layers(ds)
                layer_names = [str(row[0]) for row in layers]
            else:
                layer_names = [ds.stem]
            for layer in layer_names:
                try:
                    info = pyogrio.read_info(ds, layer=layer if ds.suffix.lower() == ".gdb" else None)
                    fields = clean_cols(list(info.get("fields", [])))
                    dtypes = [str(x) for x in list(info.get("dtypes", []))]
                    role = guess_role(ds.name + " " + layer, fields)
                    cls = classified_cols(fields)
                    layer_rows.append(
                        {
                            "source_path": rel(ds),
                            "geodatabase_or_file": ds.name,
                            "layer_name": layer,
                            "readable": True,
                            "row_count": info.get("features", ""),
                            "field_count": len(fields),
                            "geometry_type": info.get("geometry_type", ""),
                            "crs": str(info.get("crs", "")),
                            "geometry_non_null_count": "",
                            "id_fields": "|".join(cls["id_fields"]),
                            "route_fields": "|".join(cls["route_fields"]),
                            "measure_fields": "|".join(cls["measure_fields"]),
                            "date_year_fields": "|".join(cls["date_year_fields"]),
                            "source_role_guess": role,
                        }
                    )
                    for field, dtype in zip(fields, dtypes):
                        schema_rows.append(
                            {
                                "source_path": rel(ds),
                                "layer_name": layer,
                                "field_name": field,
                                "field_type": dtype,
                                "source_role_guess": role,
                            }
                        )
                except Exception as exc:
                    layer_rows.append(
                        {
                            "source_path": rel(ds),
                            "geodatabase_or_file": ds.name,
                            "layer_name": layer,
                            "readable": False,
                            "error": f"{type(exc).__name__}:{exc}",
                            "source_role_guess": guess_role(ds.name + " " + layer, []),
                        }
                    )
        except Exception as exc:
            layer_rows.append(
                {
                    "source_path": rel(ds),
                    "geodatabase_or_file": ds.name,
                    "layer_name": "",
                    "readable": False,
                    "error": f"{type(exc).__name__}:{exc}",
                    "source_role_guess": guess_role(ds.name, []),
                }
            )
    return folder_rows, layer_rows, schema_rows, source_datasets


def artifact_inventory(folder: Path) -> list[dict[str, Any]]:
    rows = []
    if not folder.exists():
        return [{"path": rel(folder), "exists": False}]
    for path in sorted(folder.rglob("*.parquet"), key=lambda p: rel(p).lower()):
        try:
            info = parquet_info(path)
            cols = info["columns"]
            cls = classified_cols(cols)
            role = guess_role(path.name, cols)
            rows.append(
                {
                    "path": rel(path),
                    "file_name": path.name,
                    "row_count": info["row_count"],
                    "column_count": info["column_count"],
                    "columns": "|".join(cols),
                    "geometry_fields": "|".join(cls["geometry_fields"]),
                    "crs_metadata": json.dumps(info["schema_metadata"])[:500],
                    "lineage_fields": "|".join(cls["lineage_fields"]),
                    "id_fields": "|".join(cls["id_fields"]),
                    "route_fields": "|".join(cls["route_fields"]),
                    "measure_fields": "|".join(cls["measure_fields"]),
                    "date_year_fields": "|".join(cls["date_year_fields"]),
                    "artifact_stage": "normalized" if "normalized" in rel(path) else "staging" if "staging" in rel(path) else "other",
                    "source_role_guess": role,
                    "appears_normalized": "normalized" in rel(path),
                    "appears_derived_or_obsolete": False,
                    "readable": True,
                }
            )
        except Exception as exc:
            rows.append({"path": rel(path), "file_name": path.name, "readable": False, "error": f"{type(exc).__name__}:{exc}"})
    return rows


def score_mapping(source: dict[str, Any], artifacts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if not source.get("readable", False):
        return "source_unreadable", []
    role = source.get("source_role_guess", "other/unknown")
    candidates = [a for a in artifacts if a.get("readable") and a.get("source_role_guess") == role]
    if role in ROLE_ARTIFACT_HINTS:
        hinted = [a for a in artifacts if a.get("file_name") in ROLE_ARTIFACT_HINTS[role] and a.get("readable")]
        candidates = hinted or candidates
    if role == "access typed":
        candidates = [a for a in artifacts if a.get("file_name") == "access_v2.parquet"] or candidates
    if role == "access untyped":
        candidates = [a for a in artifacts if a.get("file_name") == "access.parquet"] or candidates
    if not candidates:
        return "no_matching_artifact_found" if role != "other/unknown" else "source_role_uncertain", []
    src_rows = source.get("row_count", "")
    exact_row_candidates = [a for a in candidates if str(a.get("row_count", "")) == str(source.get("row_count", ""))]
    normalized = [a for a in candidates if a.get("artifact_stage") == "normalized"]
    bests = exact_row_candidates or normalized or candidates
    statuses = []
    for a in bests:
        art_rows = a.get("row_count", "")
        row_match = str(src_rows) == str(art_rows)
        source_cols = set(str(source.get("id_fields", "") + "|" + source.get("route_fields", "") + "|" + source.get("measure_fields", "") + "|" + source.get("date_year_fields", "")).split("|"))
        artifact_cols = set(str(a.get("id_fields", "") + "|" + a.get("route_fields", "") + "|" + a.get("measure_fields", "") + "|" + a.get("date_year_fields", "")).split("|"))
        important_overlap = len({c for c in source_cols if c} & {c for c in artifact_cols if c})
        geometry_ok = bool(a.get("geometry_fields"))
        lineage_ok = bool(a.get("lineage_fields"))
        if row_match and geometry_ok and lineage_ok:
            status = "fully_represented_in_normalized_artifact" if a.get("artifact_stage") == "normalized" else "fully_represented_in_staging_artifact_only"
        elif not row_match:
            status = "represented_but_row_count_mismatch"
        elif not geometry_ok:
            status = "represented_but_geometry_or_crs_mismatch"
        elif not lineage_ok:
            status = "represented_but_metadata_incomplete"
        elif important_overlap == 0:
            status = "represented_but_field_loss_suspected"
        else:
            status = "represented_but_metadata_incomplete"
        statuses.append((status, a))
    if len(bests) > 1:
        return "represented_by_multiple_artifacts", bests
    return statuses[0]


def gate2_coverage() -> tuple[str, dict[str, Any]]:
    log("Gate 2: auditing source layer to artifact coverage")
    COVERAGE.mkdir(parents=True, exist_ok=True)
    if not SOURCE.exists():
        decision = "source_artifact_coverage_inconclusive_do_not_move_source_folder"
        write_csv(COVERAGE / "source_folder_inventory.csv", [{"path": rel(SOURCE), "exists": False}])
        return decision, {"reason": "source folder missing"}

    folder_rows, layer_rows, schema_rows, _ = list_source_layers()
    norm_rows = artifact_inventory(NORMALIZED)
    staging_rows = artifact_inventory(STAGING)
    all_artifacts = [r for r in norm_rows + staging_rows if r.get("readable")]
    write_csv(COVERAGE / "source_folder_inventory.csv", folder_rows)
    write_csv(COVERAGE / "source_geodatabase_layer_inventory.csv", layer_rows)
    write_csv(COVERAGE / "source_layer_schema_inventory.csv", schema_rows)
    write_csv(COVERAGE / "normalized_artifact_inventory.csv", norm_rows)
    write_csv(COVERAGE / "staging_artifact_inventory.csv", staging_rows)

    matrix = []
    row_compare = []
    field_check = []
    geom_check = []
    lineage_check = []
    mapped_artifacts: set[str] = set()
    for src in layer_rows:
        status, candidates = score_mapping(src, all_artifacts)
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not candidates:
            matrix.append(
                {
                    "source_path": src.get("source_path"),
                    "layer_name": src.get("layer_name"),
                    "source_role_guess": src.get("source_role_guess"),
                    "coverage_classification": status,
                    "artifact_path": "",
                    "source_row_count": src.get("row_count", ""),
                    "artifact_row_count": "",
                }
            )
            continue
        for art in candidates:
            mapped_artifacts.add(art["path"])
            source_rows = src.get("row_count", "")
            artifact_rows = art.get("row_count", "")
            matrix.append(
                {
                    "source_path": src.get("source_path"),
                    "layer_name": src.get("layer_name"),
                    "source_role_guess": src.get("source_role_guess"),
                    "coverage_classification": status,
                    "artifact_path": art.get("path"),
                    "source_row_count": source_rows,
                    "artifact_row_count": artifact_rows,
                }
            )
            row_compare.append(
                {
                    "source_path": src.get("source_path"),
                    "layer_name": src.get("layer_name"),
                    "artifact_path": art.get("path"),
                    "source_row_count": source_rows,
                    "artifact_row_count": artifact_rows,
                    "row_count_match": str(source_rows) == str(artifact_rows),
                }
            )
            src_fields = set((src.get("id_fields", "") + "|" + src.get("route_fields", "") + "|" + src.get("measure_fields", "") + "|" + src.get("date_year_fields", "")).split("|"))
            art_fields = set((art.get("id_fields", "") + "|" + art.get("route_fields", "") + "|" + art.get("measure_fields", "") + "|" + art.get("date_year_fields", "")).split("|"))
            field_check.append(
                {
                    "source_path": src.get("source_path"),
                    "layer_name": src.get("layer_name"),
                    "artifact_path": art.get("path"),
                    "source_key_route_measure_date_fields": "|".join(sorted(x for x in src_fields if x)),
                    "artifact_key_route_measure_date_fields": "|".join(sorted(x for x in art_fields if x)),
                    "overlap_count": len({x for x in src_fields if x} & {x for x in art_fields if x}),
                    "field_preservation_plausible": len({x for x in src_fields if x} & {x for x in art_fields if x}) > 0 or src.get("source_role_guess") == "other/unknown",
                }
            )
            geom_check.append(
                {
                    "source_path": src.get("source_path"),
                    "layer_name": src.get("layer_name"),
                    "artifact_path": art.get("path"),
                    "source_geometry_type": src.get("geometry_type", ""),
                    "source_crs": src.get("crs", ""),
                    "artifact_geometry_fields": art.get("geometry_fields", ""),
                    "artifact_crs_metadata": art.get("crs_metadata", ""),
                    "geometry_or_encoding_present": bool(art.get("geometry_fields")),
                    "crs_documented": bool(art.get("crs_metadata")) or bool(src.get("crs")),
                }
            )
            lineage_check.append(
                {
                    "source_path": src.get("source_path"),
                    "layer_name": src.get("layer_name"),
                    "artifact_path": art.get("path"),
                    "artifact_lineage_fields": art.get("lineage_fields", ""),
                    "source_layer_path_preserved_or_inferable": bool(art.get("lineage_fields")),
                }
            )
    write_csv(COVERAGE / "source_to_artifact_coverage_matrix.csv", matrix)
    write_csv(COVERAGE / "source_artifact_row_count_comparison.csv", row_compare)
    write_csv(COVERAGE / "source_artifact_field_preservation_check.csv", field_check)
    write_csv(COVERAGE / "source_artifact_geometry_crs_check.csv", geom_check)
    write_csv(COVERAGE / "source_artifact_lineage_check.csv", lineage_check)

    blockers = [r for r in matrix if r["coverage_classification"] in {"no_matching_artifact_found", "source_unreadable", "source_role_uncertain", "represented_but_row_count_mismatch", "represented_but_geometry_or_crs_mismatch", "represented_but_field_loss_suspected"}]
    no_art = [r for r in matrix if r["coverage_classification"] in {"no_matching_artifact_found", "source_unreadable", "source_role_uncertain"}]
    unmapped_artifacts = [a for a in all_artifacts if a["path"] not in mapped_artifacts]
    score_rows = []
    for cls in sorted({r["coverage_classification"] for r in matrix}):
        count = sum(1 for r in matrix if r["coverage_classification"] == cls)
        score_rows.append({"coverage_classification": cls, "source_layer_mapping_count": count})
    write_csv(COVERAGE / "source_artifact_zero_data_loss_scorecard.csv", score_rows)
    write_csv(COVERAGE / "source_layers_without_artifact.csv", no_art or [{"check": "none", "passed": True}])
    write_csv(COVERAGE / "artifacts_without_source_mapping.csv", unmapped_artifacts or [{"check": "none", "passed": True}])
    write_csv(
        COVERAGE / "source_layer_removal_readiness.csv",
        [
            {
                "source_folder": rel(SOURCE),
                "can_move_source_folder_now": len(blockers) == 0,
                "blocker_count": len(blockers),
                "note": "Do not move in this task regardless of decision.",
            }
        ],
    )
    write_csv(COVERAGE / "source_folder_removal_blockers.csv", blockers or [{"check": "none", "passed": True}])
    repair_plan = []
    for b in blockers:
        repair_plan.append(
            {
                "source_path": b.get("source_path"),
                "layer_name": b.get("layer_name"),
                "coverage_classification": b.get("coverage_classification"),
                "recommended_action": "Create or repair normalized artifact with row-count, geometry/CRS, lineage, IDs, and route/measure/date preservation documentation.",
            }
        )
    write_csv(COVERAGE / "artifact_conversion_repair_plan.csv", repair_plan or [{"check": "no_conversion_repair_needed", "passed": True}])

    if any(r["coverage_classification"] in {"no_matching_artifact_found", "source_role_uncertain"} for r in matrix):
        decision = "source_layers_need_artifact_conversion_repair_before_move"
    elif any(r["coverage_classification"] in {"represented_but_metadata_incomplete"} for r in matrix):
        decision = "source_layers_need_artifact_metadata_repair_before_move"
    elif blockers:
        decision = "source_layers_represented_with_documented_residuals_review_before_move"
    else:
        decision = "source_layers_fully_represented_in_artifacts_ready_to_move_source_folder"
    findings = f"""# Source Artifact Coverage Findings

Inventoried source folder: `{rel(SOURCE)}`.

Source layers inventoried: {len(layer_rows)}.

Artifact parquets inventoried: {len(all_artifacts)}.

Decision: `{decision}`.

The source folder should not be moved out of the repo in this task. Current blockers: {len(blockers)}.

Unmapped artifacts: {len(unmapped_artifacts)}.

Review `source_folder_removal_blockers.csv` and `artifact_conversion_repair_plan.csv` before moving or zipping source layers.
"""
    (COVERAGE / "source_artifact_coverage_findings.md").write_text(findings, encoding="utf-8")
    write_json(
        COVERAGE / "source_artifact_coverage_manifest.json",
        {
            "created_utc": now(),
            "decision": decision,
            "source_folder": rel(SOURCE),
            "source_layers_inventoried": len(layer_rows),
            "artifact_parquets_inventoried": len(all_artifacts),
            "blocker_count": len(blockers),
            "unmapped_artifact_count": len(unmapped_artifacts),
        },
    )
    return decision, {"source_layers": len(layer_rows), "artifacts": len(all_artifacts), "blockers": blockers, "unmapped_artifacts": unmapped_artifacts, "scorecard": score_rows}


def main() -> None:
    INDEX.mkdir(parents=True, exist_ok=True)
    gate1_decision, gate1 = gate1_index()
    if gate1_decision != "index_regenerated_ready_for_source_artifact_audit":
        gate2_decision = "source_artifact_coverage_inconclusive_do_not_move_source_folder"
        gate2 = {"reason": "gate1_failed"}
    else:
        gate2_decision, gate2 = gate2_coverage()
    write_json(
        FINAL_DECISION,
        {
            "created_utc": now(),
            "gate1_decision": gate1_decision,
            "gate2_decision": gate2_decision,
            "source_folder_can_be_moved_out_of_repo_now": gate2_decision == "source_layers_fully_represented_in_artifacts_ready_to_move_source_folder",
        },
    )
    recs = [
        {"priority": 1, "action": "Review source artifact blockers before moving the source folder.", "reason": gate2_decision},
        {"priority": 2, "action": "Repair or document artifact lineage/coverage gaps in artifacts, not work/review.", "reason": "Source folder movement requires zero-data-loss confidence."},
        {"priority": 3, "action": "Keep final_dataset_cache, final_summaries, and mvp_dataset unchanged.", "reason": "This was an index/audit task."},
    ]
    write_csv(RECOMMENDED, recs)
    log(f"Workflow complete: gate1={gate1_decision}; gate2={gate2_decision}")


if __name__ == "__main__":
    main()
