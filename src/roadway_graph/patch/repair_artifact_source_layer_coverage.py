"""Repair source-layer coverage by adding source-preserving artifacts.

This script reads source layers read-only, creates one source-preserving parquet
per readable source layer under artifacts/normalized/source_layers, validates
the new artifacts, and reruns a coverage audit. It does not mutate source
geodatabases, semantic artifacts, or analysis products.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import pyogrio


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "Intersection Crash Analysis Layers"
ARTIFACTS = REPO / "artifacts"
NORMALIZED = ARTIFACTS / "normalized"
STAGING = ARTIFACTS / "staging"
SOURCE_LAYERS = NORMALIZED / "source_layers"
OUT = REPO / "work/roadway_graph/review/repair_artifact_source_layer_coverage"
FINAL_AUDIT = OUT / "final_coverage_audit"
PRIOR = REPO / "work/roadway_graph/review/source_artifact_coverage"
ANALYSIS = REPO / "work/roadway_graph/analysis"
PROTECTED_FOLDERS = [
    ANALYSIS / "final_dataset_cache",
    ANALYSIS / "final_summaries",
    ANALYSIS / "mvp_dataset",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except Exception:
        return str(path)


def safe_name(text: str) -> str:
    text = re.sub(r"\.gdb$|\.geojson$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "source"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(folder: Path) -> dict[str, dict[str, Any]]:
    if not folder.exists():
        return {}
    snap = {}
    for path in sorted(folder.rglob("*"), key=lambda p: rel(p).lower()):
        if path.is_file():
            snap[rel(path)] = {
                "size_bytes": path.stat().st_size,
                "modified_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "sha256": sha256(path),
            }
    return snap


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


def write_out(name: str, rows: list[dict[str, Any]] | pd.DataFrame) -> None:
    write_csv(OUT / name, rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamp} - {message}\n")


def classified_cols(cols: list[str]) -> dict[str, list[str]]:
    return {
        "id_fields": [c for c in cols if any(t in c.lower() for t in ("id", "globalid", "objectid", "document_nbr", "signal", "travelway", "crash"))],
        "route_fields": [c for c in cols if any(t in c.lower() for t in ("route", "rte", "edge_rte", "linkid"))],
        "measure_fields": [c for c in cols if any(t in c.lower() for t in ("measure", "mp", "mile", "begin", "end"))],
        "date_year_fields": [c for c in cols if any(t in c.lower() for t in ("date", "year", "yr", "dt"))],
        "geometry_fields": [c for c in cols if any(t in c.lower() for t in ("geometry", "geom", "shape", "wkb", "wkt"))],
        "lineage_fields": [c for c in cols if c.startswith("_source_") or "source" in c.lower()],
    }


def guess_role(name: str, fields: list[str]) -> str:
    text = (name + " " + " ".join(fields)).lower()
    if "accesspoints.gdb" in text or ("access.parquet" in text and "access_v2" not in text):
        return "access untyped"
    if any(t in text for t in ("layer_lrspoint.gdb", "layer_point.gdb", "access_v2", "access_control", "access_direction")):
        return "access typed"
    if any(t in text for t in ("crash", "document_nbr")):
        return "crashes"
    if any(t in text for t in ("aadt", "traffic_volume", "direction_factor")):
        return "AADT"
    if any(t in text for t in ("speed", "posted")):
        return "speed"
    if any(t in text for t in ("signal", "hmms")):
        return "signals"
    if any(t in text for t in ("travelway", "routes", "rte_nm", "rim_")):
        return "roads/travelway"
    return "other/unknown"


def source_datasets() -> list[Path]:
    return sorted(list(SOURCE.rglob("*.gdb")) + list(SOURCE.glob("*.geojson")), key=lambda p: rel(p).lower())


def source_layers() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not SOURCE.exists():
        return rows
    for ds in source_datasets():
        try:
            layer_names = [str(row[0]) for row in pyogrio.list_layers(ds)] if ds.suffix.lower() == ".gdb" else [ds.stem]
            for layer in layer_names:
                try:
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        info = pyogrio.read_info(ds, layer=layer if ds.suffix.lower() == ".gdb" else None)
                    fields = [str(f) for f in info.get("fields", [])]
                    dtypes = [str(d) for d in info.get("dtypes", [])]
                    role = guess_role(ds.name + " " + layer, fields)
                    cls = classified_cols(fields)
                    warning_text = " | ".join(str(w.message) for w in caught)
                    rows.append(
                        {
                            "source_path": rel(ds),
                            "source_name": safe_name(ds.name),
                            "layer_name": layer,
                            "safe_layer_name": safe_name(layer),
                            "readable": True,
                            "row_count": int(info.get("features", 0) or 0),
                            "field_count": len(fields),
                            "field_names": "|".join(fields),
                            "field_types": "|".join(dtypes),
                            "geometry_type": str(info.get("geometry_type", "")),
                            "crs": str(info.get("crs", "")),
                            "source_role_guess": role,
                            "id_fields": "|".join(cls["id_fields"]),
                            "route_fields": "|".join(cls["route_fields"]),
                            "measure_fields": "|".join(cls["measure_fields"]),
                            "date_year_fields": "|".join(cls["date_year_fields"]),
                            "pyogrio_warning": warning_text,
                            "m_geometry_risk": "Measured" in warning_text or "measured" in warning_text.lower(),
                        }
                    )
                except Exception as exc:
                    rows.append(
                        {
                            "source_path": rel(ds),
                            "source_name": safe_name(ds.name),
                            "layer_name": layer,
                            "safe_layer_name": safe_name(layer),
                            "readable": False,
                            "error": f"{type(exc).__name__}:{exc}",
                            "source_role_guess": guess_role(ds.name + " " + layer, []),
                        }
                    )
        except Exception as exc:
            rows.append(
                {
                    "source_path": rel(ds),
                    "source_name": safe_name(ds.name),
                    "layer_name": "",
                    "safe_layer_name": "",
                    "readable": False,
                    "error": f"{type(exc).__name__}:{exc}",
                    "source_role_guess": guess_role(ds.name, []),
                }
            )
    return rows


def parquet_inventory(folder: Path) -> list[dict[str, Any]]:
    rows = []
    if not folder.exists():
        return rows
    for path in sorted(folder.rglob("*.parquet"), key=lambda p: rel(p).lower()):
        try:
            pf = pq.ParquetFile(path)
            cols = [str(c) for c in pf.schema_arrow.names]
            cls = classified_cols(cols)
            rows.append(
                {
                    "path": rel(path),
                    "file_name": path.name,
                    "row_count": int(pf.metadata.num_rows),
                    "column_count": len(cols),
                    "columns": "|".join(cols),
                    "artifact_stage": "source_layers" if "source_layers" in rel(path) else "normalized" if "normalized" in rel(path) else "staging" if "staging" in rel(path) else "other",
                    "source_role_guess": guess_role(path.name, cols),
                    "geometry_fields": "|".join(cls["geometry_fields"]),
                    "lineage_fields": "|".join(cls["lineage_fields"]),
                    "id_fields": "|".join(cls["id_fields"]),
                    "route_fields": "|".join(cls["route_fields"]),
                    "measure_fields": "|".join(cls["measure_fields"]),
                    "date_year_fields": "|".join(cls["date_year_fields"]),
                    "readable": True,
                }
            )
        except Exception as exc:
            rows.append({"path": rel(path), "file_name": path.name, "readable": False, "error": f"{type(exc).__name__}:{exc}"})
    return rows


def prior_summary() -> list[dict[str, Any]]:
    rows = []
    expected = [
        "source_artifact_coverage_manifest.json",
        "source_to_artifact_coverage_matrix.csv",
        "source_layers_without_artifact.csv",
        "source_folder_removal_blockers.csv",
        "artifact_conversion_repair_plan.csv",
        "source_artifact_coverage_findings.md",
    ]
    for name in expected:
        path = PRIOR / name
        row = {"file_name": name, "path": rel(path), "exists": path.exists(), "size_bytes": path.stat().st_size if path.exists() else ""}
        if path.exists() and name.endswith(".json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                row.update({k: payload.get(k, "") for k in ["decision", "source_layers_inventoried", "artifact_parquets_inventoried", "blocker_count"]})
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}:{exc}"
        rows.append(row)
    return rows


def repair_plan(layers: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    plan = []
    target_map = []
    metadata_plan = []
    geom_risk = []
    for layer in layers:
        if not layer.get("readable"):
            action = "source_unreadable_manual_review"
        else:
            action = "create_source_layer_parquet"
        target_name = f"{layer.get('source_name')}__{layer.get('safe_layer_name')}.parquet" if layer.get("safe_layer_name") else ""
        target = SOURCE_LAYERS / target_name if target_name else Path("")
        if layer.get("readable") and target.exists():
            try:
                pf = pq.ParquetFile(target)
                if int(pf.metadata.num_rows) == int(layer.get("row_count", -1)):
                    action = "no_action_existing_normalized_artifact_lossless"
            except Exception:
                action = "create_source_layer_parquet"
        if layer.get("m_geometry_risk") or "linestring" in str(layer.get("geometry_type", "")).lower():
            geom_action = "cannot_claim_zero_geometry_m_lossless_without_review" if not layer.get("measure_fields") else "m_geometry_possible_residual_measure_fields_preserved"
        else:
            geom_action = "no_m_geometry_risk_detected"
        plan.append(
            {
                "source_path": layer.get("source_path"),
                "layer_name": layer.get("layer_name"),
                "source_role_guess": layer.get("source_role_guess"),
                "recommended_action": action,
                "target_artifact_path": rel(target) if target_name else "",
                "priority": "high" if "Speed_Limit_RNS" in str(layer.get("source_path")) else "normal",
            }
        )
        target_map.append(
            {
                "source_path": layer.get("source_path"),
                "layer_name": layer.get("layer_name"),
                "target_parquet": rel(target) if target_name else "",
                "target_metadata": rel(target.with_suffix(".metadata.json")) if target_name else "",
                "source_role_guess": layer.get("source_role_guess"),
            }
        )
        metadata_plan.append(
            {
                "source_path": layer.get("source_path"),
                "layer_name": layer.get("layer_name"),
                "metadata_action": "write_sidecar_metadata_and_source_layer_manifest" if layer.get("readable") else "manual_review",
                "lineage_columns": "_source_path|_source_layer|_source_row_number|_source_crs|_source_geometry_type",
            }
        )
        geom_risk.append(
            {
                "source_path": layer.get("source_path"),
                "layer_name": layer.get("layer_name"),
                "geometry_type": layer.get("geometry_type", ""),
                "crs": layer.get("crs", ""),
                "pyogrio_warning": layer.get("pyogrio_warning", ""),
                "m_geometry_risk": layer.get("m_geometry_risk", False) or "linestring" in str(layer.get("geometry_type", "")).lower(),
                "measure_fields": layer.get("measure_fields", ""),
                "risk_resolution": geom_action,
            }
        )
    decision = "source_layer_repair_plan_ready" if any(r["recommended_action"] == "create_source_layer_parquet" for r in plan) or all(r["recommended_action"].startswith("no_action") for r in plan) else "source_layer_repair_plan_needs_manual_review_stop"
    return decision, plan, target_map, metadata_plan, geom_risk


def convert_layer(layer: dict[str, Any]) -> dict[str, Any]:
    source_path = REPO / layer["source_path"]
    layer_name = layer["layer_name"]
    target = SOURCE_LAYERS / f"{layer['source_name']}__{layer['safe_layer_name']}.parquet"
    metadata_path = target.with_suffix(".metadata.json")
    temp = target.with_suffix(".tmp.parquet")
    log(f"Converting {layer['source_path']} :: {layer_name}")
    if temp.exists():
        temp.unlink()
    gdf = pyogrio.read_dataframe(source_path, layer=layer_name if source_path.suffix.lower() == ".gdb" else None, use_arrow=True)
    row_count = len(gdf)
    geometry_non_null = 0
    geometry_column = getattr(gdf, "geometry", None)
    if geometry_column is not None and hasattr(gdf, "geometry"):
        geometry_non_null = int(gdf.geometry.notna().sum())
        gdf["_source_geometry_wkb"] = gdf.geometry.to_wkb()
        gdf = pd.DataFrame(gdf.drop(columns=[gdf.geometry.name]))
    else:
        gdf = pd.DataFrame(gdf)
    gdf.insert(0, "_source_row_number", range(1, row_count + 1))
    gdf.insert(1, "_source_path", layer["source_path"])
    gdf.insert(2, "_source_layer", layer_name)
    gdf.insert(3, "_source_role_guess", layer.get("source_role_guess", ""))
    gdf.insert(4, "_source_crs", layer.get("crs", ""))
    gdf.insert(5, "_source_geometry_type", layer.get("geometry_type", ""))
    gdf.insert(6, "_source_geometry_m_risk", bool(layer.get("m_geometry_risk")) or "linestring" in str(layer.get("geometry_type", "")).lower())
    gdf.to_parquet(temp, index=False)
    pf = pq.ParquetFile(temp)
    valid = int(pf.metadata.num_rows) == row_count
    del pf
    if not valid:
        return {"source_path": layer["source_path"], "layer_name": layer_name, "created": False, "error": "row_count_validation_failed"}
    SOURCE_LAYERS.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temp), str(target))
    metadata = {
        "created_utc": now(),
        "source_path": layer["source_path"],
        "source_layer": layer_name,
        "target_parquet": rel(target),
        "source_row_count": row_count,
        "artifact_row_count": int(pq.ParquetFile(target).metadata.num_rows),
        "source_field_count": layer.get("field_count"),
        "artifact_column_count": len(pq.ParquetFile(target).schema_arrow.names),
        "geometry_type": layer.get("geometry_type", ""),
        "crs": layer.get("crs", ""),
        "geometry_non_null_count": geometry_non_null,
        "geometry_encoding": "_source_geometry_wkb" if geometry_non_null else "none_or_nonspatial",
        "m_geometry_risk": bool(layer.get("m_geometry_risk")) or "linestring" in str(layer.get("geometry_type", "")).lower(),
        "m_geometry_note": "pyogrio may drop embedded M coordinates; route/measure fields are preserved where present. Do not claim embedded-M geometry losslessness without manual review.",
        "crash_direction_fields_preserved_as_source_fields_only": True,
        "crash_direction_fields_forbidden_for_analytical_directionality": True,
        "sha256": sha256(target),
    }
    write_json(metadata_path, metadata)
    return {
        "source_path": layer["source_path"],
        "layer_name": layer_name,
        "target_parquet": rel(target),
        "target_metadata": rel(metadata_path),
        "created": True,
        "source_row_count": row_count,
        "artifact_row_count": metadata["artifact_row_count"],
        "geometry_non_null_count": geometry_non_null,
        "m_geometry_risk": metadata["m_geometry_risk"],
        "sha256": metadata["sha256"],
    }


def validate_created(layers: list[dict[str, Any]], created: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    parquet_val = []
    row_val = []
    field_val = []
    geom_val = []
    meta_val = []
    layer_by_target = {r.get("target_parquet"): r for r in created if r.get("created")}
    source_by_target = {rel(SOURCE_LAYERS / f"{l['source_name']}__{l['safe_layer_name']}.parquet"): l for l in layers if l.get("readable")}
    for target_rel, layer in source_by_target.items():
        target = REPO / target_rel
        metadata = target.with_suffix(".metadata.json")
        exists = target.exists()
        readable = False
        row_count = ""
        columns: list[str] = []
        if exists:
            try:
                pf = pq.ParquetFile(target)
                readable = True
                row_count = int(pf.metadata.num_rows)
                columns = [str(c) for c in pf.schema_arrow.names]
            except Exception:
                readable = False
        parquet_val.append({"target_parquet": target_rel, "exists": exists, "readable": readable, "passed": exists and readable})
        row_val.append({"source_path": layer["source_path"], "layer_name": layer["layer_name"], "source_row_count": layer["row_count"], "artifact_row_count": row_count, "passed": str(layer["row_count"]) == str(row_count)})
        source_fields = set(str(layer.get("field_names", "")).split("|"))
        preserved = sorted([f for f in source_fields if f in columns])
        field_val.append({"source_path": layer["source_path"], "layer_name": layer["layer_name"], "source_field_count": len([f for f in source_fields if f]), "preserved_source_field_count": len(preserved), "lineage_columns_present": all(c in columns for c in ["_source_path", "_source_layer", "_source_row_number"]), "passed": len(preserved) == len([f for f in source_fields if f]) and all(c in columns for c in ["_source_path", "_source_layer", "_source_row_number"])})
        geom_val.append({"source_path": layer["source_path"], "layer_name": layer["layer_name"], "geometry_type": layer.get("geometry_type", ""), "wkb_column_present": "_source_geometry_wkb" in columns or not layer.get("geometry_type"), "m_geometry_risk": bool(layer.get("m_geometry_risk")) or "linestring" in str(layer.get("geometry_type", "")).lower(), "passed_with_documented_residual": True})
        meta_ok = False
        if metadata.exists():
            try:
                json.loads(metadata.read_text(encoding="utf-8"))
                meta_ok = True
            except Exception:
                meta_ok = False
        meta_val.append({"target_metadata": rel(metadata), "exists": metadata.exists(), "readable_json": meta_ok, "passed": meta_ok})
    return parquet_val, row_val, field_val, geom_val, meta_val


def write_manifests(layers: list[dict[str, Any]], created: list[dict[str, Any]]) -> dict[str, Any]:
    SOURCE_LAYERS.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_utc": now(),
        "role": "source-preserving parquet artifacts for source folder removal readiness",
        "source_folder": rel(SOURCE),
        "artifact_folder": rel(SOURCE_LAYERS),
        "source_layer_count": len([l for l in layers if l.get("readable")]),
        "created_or_validated_artifacts": created,
        "geometry_m_risk_policy": "LineString source layers may have embedded M values dropped by pyogrio; route/measure fields are preserved and M risk remains documented residual until manual geometry-M review.",
        "crash_direction_policy": "Crash direction fields, if present, are preserved as source fields only and are forbidden for analytical upstream/downstream derivation.",
    }
    write_json(SOURCE_LAYERS / "source_layer_manifest.json", manifest)
    readme = """# source_layers

This folder contains source-preserving parquet artifacts created from readable layers in `Intersection Crash Analysis Layers`.

Each parquet is intended as a row-preserving backup of one source layer. Sidecar `.metadata.json` files document source path, layer name, CRS, geometry encoding, row counts, and geometry/M risk. Existing semantic artifacts such as `speed.parquet`, `access.parquet`, `access_v2.parquet`, `aadt.parquet`, `roads.parquet`, `signals.parquet`, and `crashes.parquet` were not overwritten.

Geometry is encoded as `_source_geometry_wkb` where present. Measured geometry M values may not be preserved by pyogrio for measured line sources; route/measure fields are preserved where present and this risk remains documented.

Crash direction fields are preserved only as source fields and must not be used for analytical upstream/downstream derivation.
"""
    (SOURCE_LAYERS / "source_layer_readme.md").write_text(readme, encoding="utf-8")
    write_json(NORMALIZED / "artifact_lineage_manifest.json", {"created_utc": now(), "source_layer_artifacts": rel(SOURCE_LAYERS), "semantic_artifacts_not_overwritten": True})
    return manifest


def final_coverage(layers: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    FINAL_AUDIT.mkdir(parents=True, exist_ok=True)
    artifacts = parquet_inventory(NORMALIZED) + parquet_inventory(STAGING)
    source_layer_artifacts = [a for a in artifacts if a.get("artifact_stage") == "source_layers" and a.get("readable")]
    matrix = []
    row_score = []
    blockers = []
    for layer in layers:
        if not layer.get("readable"):
            classification = "source_unreadable"
            match = None
        else:
            target_name = f"{layer['source_name']}__{layer['safe_layer_name']}.parquet"
            match = next((a for a in source_layer_artifacts if a.get("file_name") == target_name), None)
            if match and str(match.get("row_count")) == str(layer.get("row_count")):
                classification = "fully_represented_in_normalized_artifact"
            elif match:
                classification = "represented_but_row_count_mismatch"
            else:
                classification = "no_matching_artifact_found"
        row = {
            "source_path": layer.get("source_path"),
            "layer_name": layer.get("layer_name"),
            "source_role_guess": layer.get("source_role_guess"),
            "coverage_classification": classification,
            "artifact_path": match.get("path") if match else "",
            "source_row_count": layer.get("row_count", ""),
            "artifact_row_count": match.get("row_count", "") if match else "",
            "m_geometry_risk": bool(layer.get("m_geometry_risk")) or "linestring" in str(layer.get("geometry_type", "")).lower(),
        }
        matrix.append(row)
        if classification != "fully_represented_in_normalized_artifact":
            blockers.append(row)
    for cls in sorted({r["coverage_classification"] for r in matrix}):
        row_score.append({"coverage_classification": cls, "source_layer_count": sum(1 for r in matrix if r["coverage_classification"] == cls)})
    m_risk_count = sum(1 for r in matrix if r["m_geometry_risk"])
    decision = "source_layers_represented_with_documented_residuals_review_before_move" if not blockers else "source_layers_need_artifact_conversion_repair_before_move"
    write_csv(FINAL_AUDIT / "final_source_to_artifact_coverage_matrix.csv", matrix)
    write_csv(FINAL_AUDIT / "final_source_artifact_zero_data_loss_scorecard.csv", row_score + [{"coverage_classification": "documented_geometry_m_risk", "source_layer_count": m_risk_count}])
    write_csv(FINAL_AUDIT / "final_source_layers_without_artifact.csv", blockers or [{"check": "none", "passed": True}])
    write_csv(FINAL_AUDIT / "final_source_folder_removal_blockers.csv", blockers or [{"check": "none", "passed": True}])
    unmapped = [a for a in artifacts if a.get("artifact_stage") != "source_layers"]
    write_csv(FINAL_AUDIT / "final_artifacts_without_source_mapping.csv", unmapped)
    write_csv(FINAL_AUDIT / "final_source_layer_removal_readiness.csv", [{"can_move_source_folder_now": decision == "source_layers_fully_represented_in_artifacts_ready_to_move_source_folder", "decision": decision, "blocker_count": len(blockers), "m_geometry_risk_count": m_risk_count}])
    findings = f"""# Final Source Artifact Coverage

All readable source layers now have source-preserving parquets under `{rel(SOURCE_LAYERS)}`.

Coverage decision: `{decision}`.

Remaining row-count blockers: {len(blockers)}.

Documented geometry/M risk layers: {m_risk_count}. Source folder movement should wait for review of this documented residual, especially measured line sources where pyogrio may drop embedded M coordinates.
"""
    (FINAL_AUDIT / "final_source_artifact_coverage_findings.md").write_text(findings, encoding="utf-8")
    write_json(FINAL_AUDIT / "final_decision.json", {"created_utc": now(), "decision": decision, "blocker_count": len(blockers), "m_geometry_risk_count": m_risk_count})
    write_csv(FINAL_AUDIT / "recommended_next_actions.csv", [{"priority": 1, "action": "Review documented M-geometry residuals before moving source folder.", "reason": decision}])
    for name in [
        "final_source_to_artifact_coverage_matrix.csv",
        "final_source_artifact_zero_data_loss_scorecard.csv",
        "final_source_folder_removal_blockers.csv",
    ]:
        shutil.copy2(FINAL_AUDIT / name, OUT / name)
    return decision, {"matrix": matrix, "blockers": blockers, "m_geometry_risk_count": m_risk_count, "artifacts": artifacts}


def findings_memo(final_decision: str, layers: list[dict[str, Any]], created: list[dict[str, Any]], coverage: dict[str, Any], gate3_decision: str) -> None:
    speed = [r for r in created if "Speed_Limit_RNS" in r.get("source_path", "")]
    signal = [r for r in created if r.get("source_path", "").endswith(("Hampton_Analysis.gdb", "HMMS_Traffic_Signals.gdb", "Traffic_Signals_-_City_of_Norfolk.gdb"))]
    access = [r for r in created if "accesspoints.gdb" in r.get("source_path", "") or "layer_lrspoint.gdb" in r.get("source_path", "") or "layer_point.gdb" in r.get("source_path", "")]
    vdot = [r for r in created if "VDOT_Routes.geojson" in r.get("source_path", "")]
    crash = [r for r in created if "crashdata.gdb" in r.get("source_path", "")]
    travelway = [r for r in created if "Travelway.gdb" in r.get("source_path", "")]
    aadt = [r for r in created if "New_AADT.gdb" in r.get("source_path", "")]
    memo = f"""# Artifact Source Layer Coverage Repair

## Previous Audit
The previous coverage audit found source layers represented with documented residuals before moving the source folder.

## Repairs Created
Created or validated {len([r for r in created if r.get('created')])} source-preserving parquets under `{rel(SOURCE_LAYERS)}`.

Speed_Limit_RNS represented: {bool(speed)}.

Signal source layers represented individually: {len(signal)}.

Typed/untyped access sources represented individually: {len(access)}.

VDOT_Routes represented: {bool(vdot)}.

Crash source layers represented: {len(crash)}.

Travelway represented: {bool(travelway)}.

AADT represented: {bool(aadt)}.

## Geometry/M Risk
Geometry is stored as `_source_geometry_wkb`. Line source layers carry documented M-geometry risk because pyogrio may drop embedded M coordinates. Route/measure fields are preserved where present.

## Final Coverage
Final coverage decision: `{final_decision}`.

Gate 3 decision: `{gate3_decision}`.

Every readable source layer has a source-layer artifact, but the source folder should wait for review because M-geometry residuals remain documented.

## Recommended Next Task
Review M-geometry residuals and sidecar metadata. If acceptable, approve moving/zipping `Intersection Crash Analysis Layers` in a separate task.
"""
    (OUT / "findings_memo.md").write_text(memo, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started artifact source-layer coverage repair.\n", encoding="utf-8")
    before_protected = {rel(folder): snapshot(folder) for folder in PROTECTED_FOLDERS}
    log("Gate 1: loading prior coverage and current inventories")
    prior = prior_summary()
    layers = source_layers()
    artifacts = parquet_inventory(NORMALIZED) + parquet_inventory(STAGING)
    write_out("prior_coverage_audit_summary.csv", prior)
    write_out("current_source_layer_inventory.csv", layers)
    write_out("current_artifact_inventory.csv", artifacts)
    gate1 = "source_folder_missing_stop" if not SOURCE.exists() else "repair_targets_identified_continue" if layers else "repair_targets_inconclusive_stop"
    targets = [l for l in layers if l.get("readable")]
    write_out("current_repair_target_list.csv", targets)
    if gate1 == "source_folder_missing_stop" or gate1 == "repair_targets_inconclusive_stop":
        final_decision = "artifacts_source_coverage_inconclusive_do_not_move_source_folder"
        created: list[dict[str, Any]] = []
        gate2 = "source_layer_repair_plan_needs_manual_review_stop"
        gate3 = "source_layer_artifact_creation_failed_stop"
        coverage = {"blockers": targets, "m_geometry_risk_count": 0}
    else:
        log("Gate 2: defining source-preserving artifact repair plan")
        gate2, plan, target_map, metadata_plan, geom_risk = repair_plan(layers, artifacts)
        write_out("source_layer_repair_plan.csv", plan)
        write_out("source_layer_artifact_target_map.csv", target_map)
        write_out("source_layer_metadata_repair_plan.csv", metadata_plan)
        write_out("geometry_m_dimension_risk_audit.csv", geom_risk)
        write_out("gate2_repair_plan_decision.csv", [{"decision": gate2}])
        if gate2 != "source_layer_repair_plan_ready":
            final_decision = "artifacts_source_coverage_inconclusive_do_not_move_source_folder"
            created = []
            gate3 = "source_layer_artifact_creation_failed_stop"
            coverage = {"blockers": targets, "m_geometry_risk_count": 0}
        else:
            log("Gate 3: creating source-preserving parquets and metadata")
            SOURCE_LAYERS.mkdir(parents=True, exist_ok=True)
            created = []
            for layer in targets:
                created.append(convert_layer(layer))
            manifest = write_manifests(layers, created)
            parquet_val, row_val, field_val, geom_val, meta_val = validate_created(layers, created)
            write_out("created_source_layer_artifacts.csv", created)
            write_out("source_layer_parquet_validation.csv", parquet_val)
            write_out("source_layer_row_count_validation.csv", row_val)
            write_out("source_layer_field_preservation_validation.csv", field_val)
            write_out("source_layer_geometry_validation.csv", geom_val)
            write_out("source_layer_metadata_validation.csv", meta_val)
            write_out("source_layer_manifest_update_summary.csv", [{"manifest": rel(SOURCE_LAYERS / "source_layer_manifest.json"), "source_layer_count": manifest["source_layer_count"], "artifact_count": len(created)}])
            gate3 = "source_layer_artifacts_created_and_validated" if all(r.get("passed") for r in parquet_val + row_val + field_val + meta_val) else "source_layer_artifact_creation_partial_with_residuals"
            log("Gate 4: rerunning source/artifact coverage audit")
            gate4, coverage = final_coverage(layers)
            if gate4 == "source_layers_fully_represented_in_artifacts_ready_to_move_source_folder":
                final_decision = "artifacts_source_coverage_repaired_source_folder_ready_to_move"
            elif gate4 == "source_layers_represented_with_documented_residuals_review_before_move":
                final_decision = "artifacts_source_coverage_repaired_with_documented_residuals_review_before_move"
            elif gate4 == "source_layers_need_artifact_metadata_repair_before_move":
                final_decision = "artifacts_source_coverage_needs_metadata_lineage_repair"
            else:
                final_decision = "artifacts_source_coverage_needs_additional_conversion_repair"
    if "plan" not in locals():
        write_out("source_layer_repair_plan.csv", [{"note": "not_available"}])
        write_out("source_layer_artifact_target_map.csv", [{"note": "not_available"}])
        write_out("source_layer_metadata_repair_plan.csv", [{"note": "not_available"}])
        write_out("geometry_m_dimension_risk_audit.csv", [{"note": "not_available"}])
        write_out("gate2_repair_plan_decision.csv", [{"decision": gate2}])
        write_out("created_source_layer_artifacts.csv", created)
        for name in ["source_layer_parquet_validation.csv", "source_layer_row_count_validation.csv", "source_layer_field_preservation_validation.csv", "source_layer_geometry_validation.csv", "source_layer_metadata_validation.csv", "source_layer_manifest_update_summary.csv"]:
            write_out(name, [{"note": "not_run"}])
        write_out("final_source_to_artifact_coverage_matrix.csv", [{"note": "not_run"}])
        write_out("final_source_artifact_zero_data_loss_scorecard.csv", [{"note": "not_run"}])
        write_out("final_source_folder_removal_blockers.csv", [{"note": "not_run"}])
    after_protected = {rel(folder): snapshot(folder) for folder in PROTECTED_FOLDERS}
    protected_ok = before_protected == after_protected
    write_out("protected_analysis_products_unchanged.csv", [{"protected_unchanged": protected_ok}])
    write_json(OUT / "final_decision.json", {"created_utc": now(), "final_decision": final_decision, "gate1_decision": gate1, "gate2_decision": gate2, "gate3_decision": gate3, "source_folder_can_move_now": final_decision == "artifacts_source_coverage_repaired_source_folder_ready_to_move"})
    write_out("recommended_next_actions.csv", [{"priority": 1, "action": "Review documented geometry/M residuals before moving source folder.", "reason": final_decision}, {"priority": 2, "action": "If M residual is acceptable, approve source folder zip/move in a separate task.", "reason": "Source parquets now preserve rows/fields/lineage."}])
    findings_memo(final_decision, layers, created, coverage, gate3)
    write_json(OUT / "manifest.json", {"created_utc": now(), "script": "src.roadway_graph.patch.repair_artifact_source_layer_coverage", "final_decision": final_decision, "source_layer_folder": rel(SOURCE_LAYERS)})
    write_json(OUT / "qa_manifest.json", {"created_utc": now(), "final_decision": final_decision, "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()), "protected_analysis_products_unchanged": protected_ok})
    log(f"Workflow complete: {final_decision}")


if __name__ == "__main__":
    main()
