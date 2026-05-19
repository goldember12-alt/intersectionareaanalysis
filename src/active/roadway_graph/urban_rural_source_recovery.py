from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

try:
    import geopandas as gpd
    import pyogrio
    from pyproj import Transformer
except Exception:  # pragma: no cover - handled at runtime in environments without GIS deps
    gpd = None
    pyogrio = None
    Transformer = None


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = Path("review/current/urban_rural_source_recovery")
REVIEW_CURRENT = OUTPUT_ROOT / "review/current"

TEXT_SEARCH_ROOTS = (
    Path("src"),
    Path("docs"),
    Path("legacy"),
    Path("artifacts"),
    Path("work/output"),
)
ARTIFACT_ROOTS = (
    Path("artifacts/normalized"),
    Path("artifacts/staging"),
    Path("artifacts/staged"),
    Path("work/output"),
)
GDB_ROOT = Path("Intersection Crash Analysis Layers")

DIRECTIONAL_CONTEXT_FILE = OUTPUT_ROOT / "analysis/current/directional_bin_context_table/directional_bin_context.csv"
IDENTITY_BINS_FILE = REVIEW_CURRENT / "roadway_identity_metadata_propagation/directional_bins_identity_enriched.csv"
CRASH_READINESS_FILE = REVIEW_CURRENT / "crash_directional_assignment_analysis_readiness/crash_directional_assignment_readiness_by_crash.csv"
NORMALIZED_CRASHES_FILE = Path("artifacts/normalized/crashes.parquet")
STABLE_CRS_SANITY_FILE = REVIEW_CURRENT / "reference_signal_directional_bin_catchments/catchment_crs_coordinate_sanity.csv"

TEXT_EXTENSIONS = {".py", ".md", ".json", ".txt", ".csv", ".yml", ".yaml", ".toml", ".ps1", ".cmd", ".bat"}
MAX_TEXT_BYTES = 25_000_000
MAX_TEXT_HITS_PER_FILE = 200

SEARCH_PATTERNS = (
    "URBAN",
    "RURAL",
    "AREA_TYPE",
    "AREA TYPE",
    "AreaType",
    "URBAN_CODE",
    "RURAL_CODE",
    "AREA_CLASS",
    "URBANIZED",
    "UZA",
    "UA",
    "MPO",
    "PLANNING",
    "JURISDICTION",
    "DISTRICT",
    "COUNTY",
    "MUNICIPALITY",
    "FED_FUNC_CLASS",
    "FEDERAL_FUNCTIONAL_CLASS",
    "FUNC_CLASS",
    "FUNCTIONAL_CLASS",
    "VDOT classification",
    "FIPS",
    "Census",
    "locality",
    "urban/rural",
)
FIELD_TOKENS = tuple(token.upper().replace(" ", "_") for token in SEARCH_PATTERNS) + (
    "AREACD",
    "SUBAREA",
    "USGAREAKEY",
    "PLAN_DISTRICT",
    "PHYSICAL_JURIS",
    "JURIS_CODE",
    "MPO_NAME",
    "MPO_DSC",
    "FUN",
    "FAC",
)
JOIN_TOKENS = (
    "source_road_row_id",
    "source_bin_key",
    "base_segment_id",
    "reference_signal_id",
    "reference_directional_bin_id",
    "signal_id",
    "signal_no",
    "reg_signal_id",
    "rte_nm",
    "rte_common",
    "route",
    "event_source",
    "event_sour",
    "event_location",
    "event_component",
    "measure",
    "from_measure",
    "to_measure",
    "juris",
    "county",
    "district",
)
CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _append_log(lines: list[str], message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    lines.append(f"{stamp} {message}")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.upper() in {"", "NAN", "NONE", "<NA>", "NULL"} else text


def _sample_values(series: pd.Series, limit: int = 8) -> str:
    values: list[str] = []
    for value in series.map(_clean):
        if value and value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return " | ".join(values)


def _is_candidate_field(column: str) -> bool:
    upper = column.upper().replace(" ", "_")
    parts = {part for part in re.split(r"[^A-Z0-9]+", upper) if part}
    for token in FIELD_TOKENS:
        if len(token) <= 3:
            if token in parts:
                return True
            continue
        if token in upper:
            return True
    return False


def _is_join_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in JOIN_TOKENS)


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS)


def _source_type(dataset_name: str, field_name: str) -> str:
    field = field_name.upper()
    parts = {part for part in re.split(r"[^A-Z0-9]+", field) if part}
    dataset = dataset_name.lower()
    if "AREA_TYPE" == field:
        return "crash-level AREA_TYPE only"
    if "crash" in dataset and field in {"VDOT_DISTRICT", "JURIS_CODE", "PHYSICAL_JURIS", "PLAN_DISTRICT", "MPO_NAME"}:
        return "crash-level jurisdiction/planning context"
    if "URBAN" in field or "RURAL" in field:
        if "crash" in dataset:
            return "crash-level AREA_TYPE only"
        if "road" in dataset or "travelway" in dataset:
            return "roadway-level urban/rural truth"
        return "unknown/requires review"
    if "MPO" in parts or "PLAN" in field or "PLANNING" in field:
        return "jurisdiction/planning proxy"
    if "JURIS" in field or "COUNTY" in field or "DISTRICT" in field or "MUNIC" in field or "FIPS" in field:
        return "jurisdiction/planning proxy"
    if "FUNC" in field or field in {"FUN", "FAC"}:
        return "functional class proxy"
    if field in {"AREACD", "SUBAREA", "USGAREAKEY"}:
        return "unknown/requires review"
    return "unknown/requires review"


def _defensibility(source_type: str) -> tuple[int, str, bool]:
    if source_type == "roadway-level urban/rural truth":
        return 100, "direct roadway-level class", True
    if source_type == "signal-level urban/rural context":
        return 65, "signal-level candidate; needs field-definition review before bin use", False
    if source_type == "jurisdiction/planning proxy":
        return 55, "proxy context only; needs documented urban-area or policy definition", False
    if source_type == "functional class proxy":
        return 45, "functional class is not rural/urban truth", False
    if source_type == "crash-level AREA_TYPE only":
        return 35, "crash context only; not roadway-level truth", False
    if source_type == "crash-level jurisdiction/planning context":
        return 25, "crash record context only; not roadway-level truth", False
    return 20, "requires source documentation and join-path review", False


def _text_files() -> list[Path]:
    paths: list[Path] = []
    for root in TEXT_SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if OUTPUT_DIR.as_posix().replace("/", "\\") in str(path):
                continue
            if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
                try:
                    if path.stat().st_size <= MAX_TEXT_BYTES:
                        paths.append(path)
                except OSError:
                    continue
    return paths


def _search_text(lines: list[str]) -> pd.DataFrame:
    _append_log(lines, "starting code/doc/artifact text search")
    regex_parts = []
    for pattern in SEARCH_PATTERNS:
        if pattern in {"UA", "UZA"}:
            regex_parts.append(rf"\b{re.escape(pattern)}\b")
        elif " " in pattern or "/" in pattern:
            regex_parts.append(re.escape(pattern))
        else:
            regex_parts.append(rf"\b{re.escape(pattern)}\b")
    regex = re.compile("|".join(regex_parts), flags=re.IGNORECASE)
    rows: list[dict[str, Any]] = []
    for path in _text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            rows.append({"path": str(path), "line_number": "", "matched_pattern": "", "line_text": "", "read_status": f"error: {type(exc).__name__}: {exc}"})
            continue
        file_hits = 0
        for number, line in enumerate(text.splitlines(), start=1):
            match = regex.search(line)
            if not match:
                continue
            rows.append(
                {
                    "path": str(path),
                    "line_number": number,
                    "matched_pattern": match.group(0),
                    "line_text": line.strip()[:1000],
                    "read_status": "matched",
                }
            )
            file_hits += 1
            if file_hits >= MAX_TEXT_HITS_PER_FILE:
                rows.append(
                    {
                        "path": str(path),
                        "line_number": "",
                        "matched_pattern": "",
                        "line_text": f"hit cap reached at {MAX_TEXT_HITS_PER_FILE} matches for this file",
                        "read_status": "hit_cap_reached",
                    }
                )
                break
    _append_log(lines, f"completed text search with {len(rows)} hits")
    return pd.DataFrame(rows)


def _artifact_paths() -> list[Path]:
    paths: list[Path] = []
    for root in ARTIFACT_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if OUTPUT_DIR.as_posix().replace("/", "\\") in str(path):
                continue
            if path.is_file() and path.suffix.lower() in {".parquet", ".csv"}:
                paths.append(path)
    return paths


def _read_columns(path: Path) -> list[str]:
    if path.suffix.lower() == ".parquet":
        return pq.ParquetFile(path).schema_arrow.names
    return pd.read_csv(path, nrows=0).columns.tolist()


def _read_sample(path: Path, columns: list[str], nrows: int = 2000) -> pd.DataFrame:
    safe_columns = [column for column in columns if column != "geometry" and not _is_crash_direction_field(column)]
    if not safe_columns:
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path, columns=safe_columns).head(nrows)
    return pd.read_csv(path, usecols=safe_columns, dtype=str, keep_default_na=False, nrows=nrows)


def _inspect_artifacts(lines: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    _append_log(lines, "starting parquet/csv schema inventory")
    schema_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    for path in _artifact_paths():
        try:
            columns = _read_columns(path)
        except Exception as exc:
            schema_rows.append({"path": str(path), "artifact_type": path.suffix.lower().lstrip("."), "read_status": f"error: {type(exc).__name__}: {exc}", "field_name": "", "candidate_source_type": "", "sample_values": ""})
            continue
        candidate_columns = [column for column in columns if _is_candidate_field(column)]
        join_columns = [column for column in columns if _is_join_field(column)]
        sample = pd.DataFrame()
        if candidate_columns:
            try:
                sample = _read_sample(path, candidate_columns)
            except Exception:
                sample = pd.DataFrame()
        if not candidate_columns:
            continue
        for column in candidate_columns:
            dataset_name = path.stem
            source_type = _source_type(dataset_name, column)
            schema_rows.append(
                {
                    "path": str(path),
                    "artifact_type": path.suffix.lower().lstrip("."),
                    "read_status": "schema_inspected",
                    "field_name": column,
                    "candidate_source_type": source_type,
                    "sample_values": _sample_values(sample[column]) if column in sample.columns else "",
                }
            )
            field_rows.append(
                {
                    "source_family": "artifact",
                    "source_path": str(path),
                    "layer_or_table": path.stem,
                    "field_name": column,
                    "candidate_source_type": source_type,
                    "join_field_candidates": " | ".join(join_columns[:30]),
                    "sample_values": _sample_values(sample[column]) if column in sample.columns else "",
                    "notes": "schema/sample inventory only; no final urban/rural join performed",
                }
            )
    _append_log(lines, f"completed artifact inventory with {len(field_rows)} candidate fields")
    return pd.DataFrame(schema_rows), pd.DataFrame(field_rows)


def _stable_bounds() -> dict[str, Any]:
    if not STABLE_CRS_SANITY_FILE.exists():
        return {}
    try:
        frame = pd.read_csv(STABLE_CRS_SANITY_FILE)
    except Exception:
        return {}
    row = frame.loc[frame["dataset"].astype(str).eq("catchments_after_geojson_reload")]
    if row.empty:
        row = frame.head(1)
    if row.empty:
        return {}
    data = row.iloc[0].to_dict()
    try:
        return {
            "crs": _clean(data.get("crs")),
            "bounds": [float(data.get("minx")), float(data.get("miny")), float(data.get("maxx")), float(data.get("maxy"))],
        }
    except Exception:
        return {}


def _bounds_overlap(source_bounds: Any, source_crs: Any, stable: dict[str, Any]) -> str:
    if not stable or source_bounds is None or len(source_bounds) != 4:
        return "unknown"
    try:
        sminx, sminy, smaxx, smaxy = [float(value) for value in source_bounds]
        tminx, tminy, tmaxx, tmaxy = [float(value) for value in stable["bounds"]]
    except Exception:
        return "unknown"
    crs_text = _clean(source_crs)
    stable_crs = _clean(stable.get("crs"))
    if crs_text and stable_crs and crs_text != stable_crs and Transformer is not None:
        try:
            transformer = Transformer.from_crs(crs_text, stable_crs, always_xy=True)
            points = [
                transformer.transform(sminx, sminy),
                transformer.transform(sminx, smaxy),
                transformer.transform(smaxx, sminy),
                transformer.transform(smaxx, smaxy),
            ]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            sminx, sminy, smaxx, smaxy = min(xs), min(ys), max(xs), max(ys)
        except Exception:
            return "unknown"
    return str(sminx <= tmaxx and smaxx >= tminx and sminy <= tmaxy and smaxy >= tminy).lower()


def _inspect_gdb_layers(lines: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    _append_log(lines, "starting geodatabase layer inventory")
    if pyogrio is None:
        return pd.DataFrame(), pd.DataFrame()
    stable = _stable_bounds()
    layer_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    for gdb in GDB_ROOT.rglob("*.gdb") if GDB_ROOT.exists() else []:
        try:
            layers = pyogrio.list_layers(gdb)
        except Exception as exc:
            layer_rows.append({"gdb_path": str(gdb), "layer_name": "", "read_status": f"error: {type(exc).__name__}: {exc}"})
            continue
        for layer_name, listed_geometry_type in layers:
            try:
                info = pyogrio.read_info(gdb, layer=layer_name)
            except Exception as exc:
                layer_rows.append({"gdb_path": str(gdb), "layer_name": str(layer_name), "read_status": f"error: {type(exc).__name__}: {exc}"})
                continue
            fields = [str(field) for field in info.get("fields", [])]
            candidate_fields = [field for field in fields if _is_candidate_field(field)]
            join_fields = [field for field in fields if _is_join_field(field)]
            crs = _clean(info.get("crs"))
            overlap = _bounds_overlap(info.get("total_bounds"), crs, stable)
            layer_rows.append(
                {
                    "gdb_path": str(gdb),
                    "layer_name": str(layer_name),
                    "row_count": info.get("features", ""),
                    "geometry_type": _clean(info.get("geometry_type")) or str(listed_geometry_type),
                    "crs": crs,
                    "candidate_urban_rural_fields": " | ".join(candidate_fields),
                    "candidate_join_fields": " | ".join(join_fields),
                    "overlaps_stable_roadway_graph_universe": overlap,
                    "read_status": "layer_inspected",
                    "notes": "",
                }
            )
            sample = pd.DataFrame()
            if candidate_fields:
                try:
                    sample = pyogrio.read_dataframe(gdb, layer=layer_name, columns=candidate_fields, max_features=2000, read_geometry=False)
                except Exception:
                    sample = pd.DataFrame()
            for field in candidate_fields:
                source_type = _source_type(f"{gdb.stem}:{layer_name}", field)
                field_rows.append(
                    {
                        "source_family": "geodatabase",
                        "source_path": str(gdb),
                        "layer_or_table": str(layer_name),
                        "field_name": field,
                        "candidate_source_type": source_type,
                        "join_field_candidates": " | ".join(join_fields[:30]),
                        "sample_values": _sample_values(sample[field]) if field in sample.columns else "",
                        "notes": f"stable bounds overlap: {overlap}",
                    }
                )
    _append_log(lines, f"completed geodatabase inventory with {len(layer_rows)} layers and {len(field_rows)} candidate fields")
    return pd.DataFrame(layer_rows), pd.DataFrame(field_rows)


def _rank_candidates(fields: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if fields.empty:
        return pd.DataFrame(columns=["rank", "source_family", "source_path", "layer_or_table", "field_name", "candidate_source_type", "defensibility_score", "defensibility_notes", "defensible_for_candidate_join", "recommended_join_method"])
    for row in fields.to_dict(orient="records"):
        score, notes, defensible = _defensibility(str(row.get("candidate_source_type", "")))
        join_fields = str(row.get("join_field_candidates", ""))
        if "source_road_row_id" in join_fields:
            method = "existing propagated roadway identity fields"
        elif "EVENT" in join_fields.upper() or "RTE" in join_fields.upper() or "ROUTE" in join_fields.upper():
            method = "route/measure or route identity review"
        elif "signal" in join_fields.lower():
            method = "signal ID review"
        elif str(row.get("source_family")) == "geodatabase":
            method = "spatial overlay or nearest roadway review"
        else:
            method = "no direct join path identified"
        rows.append({**row, "defensibility_score": score, "defensibility_notes": notes, "defensible_for_candidate_join": defensible, "recommended_join_method": method})
    ranked = pd.DataFrame(rows).sort_values(["defensibility_score", "source_family", "source_path", "field_name"], ascending=[False, True, True, True]).reset_index(drop=True)
    ranked.insert(0, "rank", range(1, len(ranked) + 1))
    return ranked


def _join_key_audit(ranking: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in ranking.to_dict(orient="records"):
        join_fields = str(row.get("join_field_candidates", ""))
        rows.append(
            {
                "source_family": row.get("source_family", ""),
                "source_path": row.get("source_path", ""),
                "layer_or_table": row.get("layer_or_table", ""),
                "field_name": row.get("field_name", ""),
                "candidate_source_type": row.get("candidate_source_type", ""),
                "candidate_join_fields": join_fields,
                "can_join_by_roadway_identity": "source_road_row_id" in join_fields or "source_bin_key" in join_fields,
                "can_join_by_route_measure": any(token in join_fields.lower() for token in ["route", "rte", "measure", "event_sour"]),
                "can_join_by_signal_id": "signal" in join_fields.lower(),
                "can_join_by_jurisdiction_or_area": any(token in join_fields.lower() for token in ["juris", "county", "district", "mpo"]),
                "can_join_by_spatial_overlay": row.get("source_family") == "geodatabase",
                "join_path_decision": row.get("recommended_join_method", ""),
            }
        )
    return pd.DataFrame(rows)


def _stable_context() -> pd.DataFrame:
    if DIRECTIONAL_CONTEXT_FILE.exists():
        cols = pd.read_csv(DIRECTIONAL_CONTEXT_FILE, nrows=0).columns.tolist()
        usecols = [column for column in ["reference_signal_id", "reference_directional_bin_id", "distance_window", "has_assigned_crash", "unique_assigned_crash_count"] if column in cols]
        return pd.read_csv(DIRECTIONAL_CONTEXT_FILE, dtype=str, keep_default_na=False, usecols=usecols)
    if IDENTITY_BINS_FILE.exists():
        cols = pd.read_csv(IDENTITY_BINS_FILE, nrows=0).columns.tolist()
        usecols = [column for column in ["reference_signal_id", "reference_directional_bin_id", "distance_window", "bin_midpoint_ft_from_reference_signal"] if column in cols]
        frame = pd.read_csv(IDENTITY_BINS_FILE, dtype=str, keep_default_na=False, usecols=usecols)
        if "distance_window" not in frame.columns and "bin_midpoint_ft_from_reference_signal" in frame.columns:
            midpoint = pd.to_numeric(frame["bin_midpoint_ft_from_reference_signal"], errors="coerce")
            frame["distance_window"] = midpoint.map(lambda value: "high_priority_0_1000ft" if pd.notna(value) and value <= 1000 else "sensitivity_1000_2500ft" if pd.notna(value) and value <= 2500 else "outside_2500ft")
        frame["has_assigned_crash"] = "false"
        frame["unique_assigned_crash_count"] = "0"
        return frame
    return pd.DataFrame()


def _crash_area_type_candidate_preview() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not (NORMALIZED_CRASHES_FILE.exists() and CRASH_READINESS_FILE.exists()):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    readiness_cols = pd.read_csv(CRASH_READINESS_FILE, nrows=0).columns.tolist()
    use_readiness = [column for column in ["crash_id", "reference_signal_id", "reference_directional_bin_id", "bin_midpoint_ft_from_reference_signal"] if column in readiness_cols]
    if "crash_id" not in use_readiness:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    readiness = pd.read_csv(CRASH_READINESS_FILE, dtype=str, keep_default_na=False, usecols=use_readiness)
    midpoint = pd.to_numeric(readiness.get("bin_midpoint_ft_from_reference_signal"), errors="coerce")
    readiness = readiness.loc[midpoint.le(2500)].copy()
    crashes_cols = pq.ParquetFile(NORMALIZED_CRASHES_FILE).schema_arrow.names
    if "DOCUMENT_NBR" not in crashes_cols or "AREA_TYPE" not in crashes_cols:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    crashes = pd.read_parquet(NORMALIZED_CRASHES_FILE, columns=["DOCUMENT_NBR", "AREA_TYPE"])
    crashes["crash_id"] = crashes["DOCUMENT_NBR"].astype(str)
    joined = readiness.merge(crashes[["crash_id", "AREA_TYPE"]], on="crash_id", how="left")
    preview = joined.head(200).copy()
    preview["candidate_source_type"] = "crash-level AREA_TYPE only"
    preview["use_as_roadway_truth"] = False
    by_bin = (
        joined.groupby("reference_directional_bin_id", dropna=False)
        .agg(
            crashes_with_area_type=("AREA_TYPE", lambda s: int(s.map(_clean).ne("").sum())),
            crash_area_type_values=("AREA_TYPE", lambda s: " | ".join(sorted(v for v in set(s.map(_clean)) if v))),
        )
        .reset_index()
    )
    by_signal = (
        joined.groupby("reference_signal_id", dropna=False)
        .agg(
            assigned_crashes=("crash_id", "nunique"),
            bins_with_crash_area_type=("reference_directional_bin_id", "nunique"),
            crash_area_type_values=("AREA_TYPE", lambda s: " | ".join(sorted(v for v in set(s.map(_clean)) if v))),
        )
        .reset_index()
    )
    by_signal["candidate_source_type"] = "crash-level AREA_TYPE only"
    by_signal["use_as_roadway_truth"] = False
    return preview, by_bin, by_signal


def _coverage_estimate(ranking: pd.DataFrame) -> pd.DataFrame:
    stable = _stable_context()
    total_bins = len(stable)
    high_bins = int(stable.get("distance_window", pd.Series(dtype=str)).eq("high_priority_0_1000ft").sum()) if not stable.empty else 0
    sensitivity_bins = int(stable.get("distance_window", pd.Series(dtype=str)).eq("sensitivity_1000_2500ft").sum()) if not stable.empty else 0
    signal_count = int(stable.get("reference_signal_id", pd.Series(dtype=str)).nunique()) if not stable.empty else 0
    crash_bins = int(stable.get("has_assigned_crash", pd.Series(dtype=str)).astype(str).str.lower().isin(["true", "1"]).sum()) if not stable.empty else 0
    rows: list[dict[str, Any]] = []
    coverage_candidates = ranking.head(25).copy()
    if not ranking.empty and "candidate_source_type" in ranking.columns:
        crash_rows = ranking.loc[ranking["candidate_source_type"].eq("crash-level AREA_TYPE only")]
        coverage_candidates = pd.concat([coverage_candidates, crash_rows], ignore_index=True).drop_duplicates(
            subset=["source_path", "layer_or_table", "field_name"]
        )
    crash_preview = pd.DataFrame()
    crash_by_bin = pd.DataFrame()
    crash_by_signal = pd.DataFrame()
    if not coverage_candidates.empty and coverage_candidates["candidate_source_type"].eq("crash-level AREA_TYPE only").any():
        crash_preview, crash_by_bin, crash_by_signal = _crash_area_type_candidate_preview()
    for row in coverage_candidates.to_dict(orient="records"):
        source_type = str(row.get("candidate_source_type", ""))
        if bool(row.get("defensible_for_candidate_join")):
            status = "not_run_candidate_join_in_recovery_module"
            covered = ""
            note = "candidate is defensible but this recovery pass only estimates readiness unless a cheap join is implemented"
        elif source_type == "crash-level AREA_TYPE only":
            covered = int(crash_by_bin["crashes_with_area_type"].gt(0).sum()) if not crash_by_bin.empty else 0
            status = "crash_context_only_not_roadway_truth"
            signal_covered = int(crash_by_signal["reference_signal_id"].nunique()) if not crash_by_signal.empty else 0
            note = f"coverage applies only to bins with assigned crashes and cannot fill no-crash bins; reference signals with crash AREA_TYPE context: {signal_covered}"
        else:
            covered = ""
            status = "not_defensible_for_bin_context"
            note = "coverage not estimated because the source is a proxy or requires source-definition review"
        rows.append(
            {
                "source_path": row.get("source_path", ""),
                "layer_or_table": row.get("layer_or_table", ""),
                "field_name": row.get("field_name", ""),
                "candidate_source_type": source_type,
                "coverage_status": status,
                "estimated_covered_bins": covered,
                "total_stable_bins": total_bins,
                "total_0_1000ft_bins": high_bins,
                "total_1000_2500ft_bins": sensitivity_bins,
                "reference_signals": signal_count,
                "bins_with_assigned_crashes": crash_bins,
                "notes": note,
            }
        )
    return pd.DataFrame(rows)


def _rejected_candidates(ranking: pd.DataFrame) -> pd.DataFrame:
    if ranking.empty:
        return pd.DataFrame(columns=["source_path", "layer_or_table", "field_name", "candidate_source_type", "rejection_reason"])
    rejected = ranking.loc[~ranking["defensible_for_candidate_join"].astype(bool)].copy()
    rejected["rejection_reason"] = rejected["defensibility_notes"]
    return rejected[["source_family", "source_path", "layer_or_table", "field_name", "candidate_source_type", "rejection_reason", "recommended_join_method", "sample_values"]]


def _summary(ranking: pd.DataFrame, text_hits: pd.DataFrame, artifacts: pd.DataFrame, gdb_layers: pd.DataFrame) -> pd.DataFrame:
    best = ranking.head(1).iloc[0].to_dict() if not ranking.empty else {}
    defensible = ranking.loc[ranking["defensible_for_candidate_join"].astype(bool)] if not ranking.empty else pd.DataFrame()
    return pd.DataFrame(
        [
            {"metric": "bounded_question", "value": "urban/rural source recovery for stable directional-bin universe"},
            {"metric": "text_search_roots", "value": " | ".join(str(path) for path in TEXT_SEARCH_ROOTS)},
            {"metric": "artifact_search_roots", "value": " | ".join(str(path) for path in ARTIFACT_ROOTS)},
            {"metric": "gdb_search_root", "value": str(GDB_ROOT)},
            {"metric": "text_search_hits", "value": len(text_hits)},
            {"metric": "artifact_candidate_field_hits", "value": len(artifacts)},
            {"metric": "gdb_layers_inspected", "value": len(gdb_layers)},
            {"metric": "candidate_sources_ranked", "value": len(ranking)},
            {"metric": "defensible_candidate_sources", "value": len(defensible)},
            {"metric": "best_candidate_source", "value": f"{best.get('source_path', '')}:{best.get('layer_or_table', '')}.{best.get('field_name', '')}" if best else ""},
            {"metric": "best_candidate_type", "value": best.get("candidate_source_type", "")},
            {"metric": "best_candidate_defensible", "value": best.get("defensible_for_candidate_join", False)},
            {"metric": "combined_context_table_overwritten", "value": False},
            {"metric": "crash_direction_fields_read_or_used", "value": False},
        ]
    )


def _findings(summary: pd.DataFrame, ranking: pd.DataFrame, coverage: pd.DataFrame, outputs: dict[str, Path]) -> str:
    metrics = {row["metric"]: row["value"] for row in summary.to_dict(orient="records")}
    best = ranking.head(1).iloc[0].to_dict() if not ranking.empty else {}
    defensible = bool(best.get("defensible_for_candidate_join", False))
    coverage_row = coverage.head(1).iloc[0].to_dict() if not coverage.empty else {}
    return "\n".join(
        [
            "# Urban/Rural Source Recovery Findings",
            "",
            "## Bounded Question",
            "",
            "Recover and rank possible urban/rural context sources for the stable 0-2,500 ft directional-bin universe. This is diagnostic-only and does not update the combined context table.",
            "",
            "## Search Scope",
            "",
            f"- text roots: {metrics.get('text_search_roots')}",
            f"- artifact roots: {metrics.get('artifact_search_roots')}",
            f"- geodatabase root: {metrics.get('gdb_search_root')}",
            f"- text hits: {metrics.get('text_search_hits')}",
            f"- artifact candidate fields: {metrics.get('artifact_candidate_field_hits')}",
            f"- geodatabase layers inspected: {metrics.get('gdb_layers_inspected')}",
            "",
            "## Best Candidate",
            "",
            f"- source: {metrics.get('best_candidate_source') or 'none'}",
            f"- source type: {metrics.get('best_candidate_type') or 'none'}",
            f"- defensible for candidate bin join now: {defensible}",
            f"- recommended join method: {best.get('recommended_join_method', 'none')}",
            f"- rationale: {best.get('defensibility_notes', 'none')}",
            "",
            "## Coverage",
            "",
            f"- total stable bins: {coverage_row.get('total_stable_bins', '')}",
            f"- 0-1,000 ft bins: {coverage_row.get('total_0_1000ft_bins', '')}",
            f"- 1,000-2,500 ft bins: {coverage_row.get('total_1000_2500ft_bins', '')}",
            f"- reference signals: {coverage_row.get('reference_signals', '')}",
            f"- bins with assigned crashes: {coverage_row.get('bins_with_assigned_crashes', '')}",
            f"- estimated covered bins for best candidate: {coverage_row.get('estimated_covered_bins', '')}",
            f"- coverage status: {coverage_row.get('coverage_status', '')}",
            "",
            "## Interpretation",
            "",
            "The recovered legacy signal-centered RU outputs are crash `AREA_TYPE` context, not roadway-level urban/rural truth. Roadway Travelway/roads sources inspected here do not expose a direct urban/rural field. Jurisdiction, district, MPO, signal area, and functional-class fields remain proxies or require source-definition review before use.",
            "",
            "## QA",
            "",
            "- crash direction fields read or used: false",
            "- scaffold/catchment/crash-assignment/access/speed/AADT logic changed: false",
            "- combined directional-bin context table overwritten: false",
            "- crash AREA_TYPE labeled crash-level only: true",
            "",
            "## Files Created",
            "",
            *[f"- `{path}`" for path in outputs.values()],
            "",
        ]
    )


def build_urban_rural_source_recovery(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / OUTPUT_DIR
    log_lines: list[str] = []
    _append_log(log_lines, "urban/rural source recovery started")

    text_hits = _search_text(log_lines)
    artifact_schema_hits, artifact_fields = _inspect_artifacts(log_lines)
    gdb_layers, gdb_fields = _inspect_gdb_layers(log_lines)
    candidate_fields = pd.concat([artifact_fields, gdb_fields], ignore_index=True) if not artifact_fields.empty or not gdb_fields.empty else pd.DataFrame()
    ranking = _rank_candidates(candidate_fields)
    join_audit = _join_key_audit(ranking)
    coverage = _coverage_estimate(ranking)
    rejected = _rejected_candidates(ranking)
    summary = _summary(ranking, text_hits, artifact_schema_hits, gdb_layers)
    crash_preview, crash_bin_coverage, crash_signal_coverage = _crash_area_type_candidate_preview()

    outputs = {
        "summary_csv": out_dir / "urban_rural_source_recovery_summary.csv",
        "code_doc_search_hits_csv": out_dir / "urban_rural_code_doc_search_hits.csv",
        "artifact_schema_hits_csv": out_dir / "urban_rural_artifact_schema_hits.csv",
        "gdb_layer_inventory_csv": out_dir / "urban_rural_gdb_layer_inventory.csv",
        "candidate_field_inventory_csv": out_dir / "urban_rural_candidate_field_inventory.csv",
        "candidate_source_ranking_csv": out_dir / "urban_rural_candidate_source_ranking.csv",
        "candidate_join_key_audit_csv": out_dir / "urban_rural_candidate_join_key_audit.csv",
        "candidate_coverage_estimate_csv": out_dir / "urban_rural_candidate_coverage_estimate.csv",
        "rejected_candidates_csv": out_dir / "urban_rural_rejected_candidates.csv",
        "findings_md": out_dir / "urban_rural_source_recovery_findings.md",
        "manifest_json": out_dir / "urban_rural_source_recovery_manifest.json",
        "progress_log": out_dir / "urban_rural_source_recovery_progress.log",
    }

    for frame, key in [
        (summary, "summary_csv"),
        (text_hits, "code_doc_search_hits_csv"),
        (artifact_schema_hits, "artifact_schema_hits_csv"),
        (gdb_layers, "gdb_layer_inventory_csv"),
        (candidate_fields, "candidate_field_inventory_csv"),
        (ranking, "candidate_source_ranking_csv"),
        (join_audit, "candidate_join_key_audit_csv"),
        (coverage, "candidate_coverage_estimate_csv"),
        (rejected, "rejected_candidates_csv"),
    ]:
        _write_csv(frame, outputs[key])

    optional_outputs: dict[str, Path] = {}
    if not crash_preview.empty:
        optional_outputs["urban_rural_candidate_join_preview_csv"] = out_dir / "urban_rural_candidate_join_preview.csv"
        optional_outputs["urban_rural_candidate_bin_coverage_csv"] = out_dir / "urban_rural_candidate_bin_coverage.csv"
        optional_outputs["urban_rural_candidate_signal_coverage_csv"] = out_dir / "urban_rural_candidate_signal_coverage.csv"
        _write_csv(crash_preview, optional_outputs["urban_rural_candidate_join_preview_csv"])
        _write_csv(crash_bin_coverage, optional_outputs["urban_rural_candidate_bin_coverage_csv"])
        _write_csv(crash_signal_coverage, optional_outputs["urban_rural_candidate_signal_coverage_csv"])

    all_outputs = {**outputs, **optional_outputs}
    _write_text(_findings(summary, ranking, coverage, all_outputs), outputs["findings_md"])
    _append_log(log_lines, "urban/rural source recovery completed")
    _write_text("\n".join(log_lines) + "\n", outputs["progress_log"])
    _write_json(
        {
            "created_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "bounded_question": "diagnostic-only urban/rural source recovery for stable directional-bin context",
            "search_roots": {
                "text": [str(path) for path in TEXT_SEARCH_ROOTS],
                "artifacts": [str(path) for path in ARTIFACT_ROOTS],
                "geodatabases": str(GDB_ROOT),
            },
            "outputs": {key: str(path) for key, path in all_outputs.items()},
            "qa": {
                "crash_direction_fields_read_or_used": False,
                "scaffold_logic_changed": False,
                "catchment_logic_changed": False,
                "crash_assignment_logic_changed": False,
                "access_speed_aadt_context_logic_changed": False,
                "combined_context_table_overwritten": False,
                "crash_area_type_treated_as_roadway_truth": False,
            },
            "best_candidate": ranking.head(1).to_dict(orient="records"),
            "candidate_bin_context_file_created": False,
        },
        outputs["manifest_json"],
    )
    return {key: str(path) for key, path in all_outputs.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recover and rank possible urban/rural context sources without modifying context joins.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_urban_rural_source_recovery(output_root=args.output_root)
    for key, path in outputs.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
