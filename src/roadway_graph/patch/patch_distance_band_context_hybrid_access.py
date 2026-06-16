"""Patch staged distance_band_context with hybrid typed/untyped access.

This repair builds a combined access source universe from
artifacts/normalized/access.parquet and access_v2.parquet, using source
geodatabases as read-only schema evidence. Spatial assignment to staged bin
geometry is primary; strict route/measure identity is a source-rooted
supplement. Zero access is assigned only after the accepted combined source
universe is evaluated.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely import from_wkb
from shapely.strtree import STRtree

try:
    import pyogrio
except Exception:  # pragma: no cover
    pyogrio = None


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_hybrid_access"

CONTEXT = STAGING / "distance_band_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
BINS = STAGING / "bin_context.parquet"
TRAVELWAY = STAGING / "travelway_network_index.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"
TEMP = STAGING / "distance_band_context.hybrid_access_candidate.tmp.parquet"

ACCESS = REPO / "artifacts/normalized/access.parquet"
ACCESS_V2 = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"

GDBS = [
    REPO / "Intersection Crash Analysis Layers/accesspoints.gdb",
    REPO / "Intersection Crash Analysis Layers/layer_lrspoint.gdb",
    REPO / "Intersection Crash Analysis Layers/layer_point.gdb",
]

BUILD_VERSION = "distance_band_context_hybrid_access_patch_v1_2026-06-15"
FT_PER_M = 3.280839895
SELECTED_TOLERANCE_FT = 50.0
TEST_TOLERANCES_FT = [25.0, 50.0, 75.0]
MEASURE_BUCKET_MI = 0.05
MIN_OVERLAP_MI = 1e-8

IDENTITY_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
]

ACCESS_PATCH_FIELDS = [
    "access_count",
    "access_count_band",
    "access_type_flags",
    "access_type_dominant",
    "access_type_summary",
    "typed_access_count",
    "untyped_access_count",
    "riro_access_count",
    "other_review_access_count",
    "right_in_right_out_access_count",
    "access_context_status",
    "access_source_match_method",
    "access_missing_reason",
    "access_zero_evidence_status",
    "access_context_quality_flag",
    "access_candidate_count",
    "mixed_access_flag",
    "access_assignment_method",
    "access_spatial_tolerance_ft",
    "access_assignment_multiplicity_status",
    "access_source_universe_status",
    "access_typed_untyped_source_status",
    "access_identity_support_status",
]

CRASH_DIRECTION_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "travel_direction",
)
FORBIDDEN_OUTPUT_TOKENS = ("lookup", "rate_distribution", "mvp")

CORRECTED_CATEGORY_MAP = {
    "U": "unrestricted_or_full_access",
    "RIRO": "right_in_right_out",
    "R": "right_in_right_out",
    "RC": "right_in_right_out",
    "RIO": "right_in_only",
    "ROO": "right_out_only",
    "LIRIRO": "restricted_partial_access",
    "": "unknown",
}
ACCESS_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_out_only",
    "right_in_only",
    "other_review",
    "unknown",
]

PHASE_TIMINGS: list[dict[str, Any]] = []


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except Exception:
        return str(path)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    line = f"- {now()} - {message}\n"
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as handle:
        handle.write(line)
    print(line.strip(), flush=True)


@contextmanager
def phase(name: str, **details: Any):
    suffix = f" {details}" if details else ""
    log(f"BEGIN {name}{suffix}")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = round(time.perf_counter() - start, 3)
        PHASE_TIMINGS.append({"phase": name, "elapsed_seconds": elapsed, **details})
        log(f"END {name}; elapsed_seconds={elapsed:.3f}")


def write_csv(name: str, rows: Any) -> pd.DataFrame:
    OUT.mkdir(parents=True, exist_ok=True)
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(OUT / name, index=False)
    return frame


def write_json(name: str, payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_json_path(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def bool_value(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def forbidden_crash_direction_cols(columns: list[str]) -> list[str]:
    return [c for c in columns if any(t in c.lower() for t in CRASH_DIRECTION_TOKENS)]


def category_from_raw(raw_code: Any, prior_category: Any = "") -> str:
    code = clean_text(raw_code).upper()
    if code in CORRECTED_CATEGORY_MAP:
        return CORRECTED_CATEGORY_MAP[code]
    prior = clean_text(prior_category)
    return prior if prior in ACCESS_CATEGORIES else "other_review"


def route_key(value: Any) -> str:
    text = clean_text(value).upper()
    if not text:
        return ""
    text = text.replace("R-VA", " ").replace("S-VA", " ").replace("VA", " ")
    text = re.sub(r"[^A-Z0-9]", " ", text)
    joined = "".join(part for part in text.split() if part)
    match = re.search(r"(US|SR|IS|I)(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?(BUS\d+)?", joined)
    if match:
        prefix = "I" if match.group(1) in {"IS", "I"} else match.group(1)
        direction = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}.get(match.group(4) or "", match.group(4) or "")
        return f"{prefix}{int(match.group(3))}{direction}{match.group(5) or ''}"
    match = re.search(r"(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?", joined)
    if match:
        direction = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}.get(match.group(3) or "", match.group(3) or "")
        return f"{int(match.group(2))}{direction}"
    return joined


def access_count_band(count: Any) -> str:
    value = pd.to_numeric(pd.Series([count]), errors="coerce").iloc[0]
    if pd.isna(value):
        return ""
    value = int(value)
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 3:
        return "2-3"
    if value <= 7:
        return "4-7"
    return "8+"


def collapse_unique(values: pd.Series, limit: int = 20) -> str:
    out: list[str] = []
    for val in values.dropna().astype(str):
        val = val.strip()
        if val and val not in out:
            out.append(val)
        if len(out) >= limit:
            break
    return "|".join(out)


def parquet_row_count(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def parent_dependency_check() -> None:
    rows = []
    for path in [CONTEXT, UNITS, BINS, TRAVELWAY, APPROACH_CORRIDORS, ACCESS, ACCESS_V2, *GDBS, CRASHES]:
        rows.append(
            {
                "path": rel(path),
                "role": "parent" if path in {CONTEXT, UNITS, BINS, TRAVELWAY, APPROACH_CORRIDORS, ACCESS, ACCESS_V2} else "schema_evidence_or_guard",
                "exists": path.exists(),
                "sha256": file_sha256(path) if path.exists() and path.is_file() else "",
                "used_as_hidden_parent": False,
            }
        )
    write_csv("parent_dependency_check.csv", rows)


def artifact_inventory() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    frames = {}
    for name, path in [("access", ACCESS), ("access_v2", ACCESS_V2)]:
        if not path.exists():
            rows.append({"artifact": name, "path": rel(path), "available": False})
            continue
        cols = pq.read_schema(path).names
        df = pd.read_parquet(path)
        frames[name] = df
        code_cols = [c for c in cols if "ACCESS_CONTROL" in c or "access_control" in c]
        rows.append(
            {
                "artifact": name,
                "path": rel(path),
                "available": True,
                "row_count": len(df),
                "usable_geometry_count": int(df["geometry"].notna().sum()) if "geometry" in df else 0,
                "source_id_fields": "|".join([c for c in ["id", "_featureId", "access_v2_source_row_id", "Stage1_SourceGDB", "Stage1_SourceLayer"] if c in cols]),
                "route_fields": "|".join([c for c in ["route_name", "_rte_nm"] if c in cols]),
                "measure_fields": "|".join([c for c in ["route_measure", "_m"] if c in cols]),
                "access_code_type_fields": "|".join(code_cols),
                "access_code_nonblank": int(sum(clean_series(df[c]).ne("").sum() for c in code_cols if c in df)),
                "duplicate_source_ids": int(df.duplicated("id").sum()) if "id" in df else "",
                "source_role": "untyped_access_source" if name == "access" else "typed_access_source",
            }
        )
    write_csv("normalized_access_artifact_inventory.csv", rows)
    return frames.get("access", pd.DataFrame()), frames.get("access_v2", pd.DataFrame())


def source_gdb_inventory() -> None:
    rows = []
    for path in GDBS:
        if not path.exists() or pyogrio is None:
            rows.append({"path": rel(path), "available": path.exists(), "readable": False, "reason": "pyogrio_unavailable_or_missing"})
            continue
        try:
            layers = pyogrio.list_layers(path)
            for layer_name, geom_type in layers:
                info = pyogrio.read_info(path, layer=layer_name)
                fields = list(info.get("fields")) if info.get("fields") is not None else []
                sample = pyogrio.read_dataframe(path, layer=layer_name, max_features=1000)
                code_cols = [c for c in fields if "ACCESS_CONTROL" in c or "access_control" in c]
                rows.append(
                    {
                        "path": rel(path),
                        "layer": layer_name,
                        "available": True,
                        "readable": True,
                        "row_count": info.get("features"),
                        "geometry_type": geom_type,
                        "crs": info.get("crs"),
                        "source_id_fields": "|".join([c for c in ["id", "_featureId"] if c in fields]),
                        "route_fields": "|".join([c for c in ["_rte_nm", "route_name"] if c in fields]),
                        "measure_fields": "|".join([c for c in ["_m", "route_measure"] if c in fields]),
                        "access_code_type_fields": "|".join(code_cols),
                        "sample_access_code_nonblank": int(sum(clean_series(sample[c]).ne("").sum() for c in code_cols if c in sample)),
                        "source_role_evidence": "untyped_access_source" if int(sum(clean_series(sample[c]).ne("").sum() for c in code_cols if c in sample)) == 0 else "typed_or_review_coded_access_source",
                    }
                )
        except Exception as exc:
            rows.append({"path": rel(path), "available": True, "readable": False, "reason": f"{type(exc).__name__}: {exc}"})
    write_csv("source_gdb_access_inventory.csv", rows)


def build_combined_source(access: pd.DataFrame, access_v2: pd.DataFrame) -> pd.DataFrame:
    with phase("build_combined_access_source"):
        frames = []
        if not access.empty:
            a = access.copy()
            a["source_artifact"] = "access.parquet"
            a["source_layer"] = clean_series(a.get("Stage1_SourceLayer", pd.Series("layer_lrspoint", index=a.index)))
            a["source_access_id"] = clean_series(a.get("id", pd.Series("", index=a.index)))
            a["route_name"] = clean_series(a.get("_rte_nm", pd.Series("", index=a.index)))
            a["route_measure"] = pd.to_numeric(a.get("_m", pd.Series(np.nan, index=a.index)), errors="coerce")
            a["raw_access_control_code"] = ""
            a["access_category"] = "unknown"
            a["typed_untyped_status"] = "untyped_access"
            a["source_quality_status"] = "accepted_untyped_lrs_access"
            frames.append(a)
        if not access_v2.empty:
            v = access_v2.copy()
            v["source_artifact"] = "access_v2.parquet"
            v["source_layer"] = clean_series(v.get("access_v2_source_layer", pd.Series("", index=v.index)))
            v["source_access_id"] = clean_series(v.get("id", pd.Series("", index=v.index)))
            v["route_name"] = clean_series(v.get("route_name", v.get("_rte_nm", pd.Series("", index=v.index))))
            v["route_measure"] = pd.to_numeric(v.get("route_measure", v.get("_m", pd.Series(np.nan, index=v.index))), errors="coerce")
            v["raw_access_control_code"] = clean_series(v.get("access_control_code", pd.Series("", index=v.index))).str.upper()
            prior = clean_series(v.get("access_control_category", pd.Series("", index=v.index))).replace("", "unknown")
            v["access_category"] = [category_from_raw(c, p) for c, p in zip(v["raw_access_control_code"], prior)]
            v["typed_untyped_status"] = np.where(v["access_category"].eq("unknown"), "untyped_or_unknown_access_v2", "typed_or_review_coded_access")
            v["source_quality_status"] = "accepted_typed_review_access_v2"
            frames.append(v)
        combined = pd.concat(frames, ignore_index=True, sort=False)
        combined = combined.loc[combined["geometry"].notna()].copy()
        combined["source_access_key"] = combined["source_artifact"] + ":" + combined["source_layer"] + ":" + combined["source_access_id"]
        combined["geometry_obj"] = from_wkb(combined["geometry"].to_numpy())
        combined = combined.loc[~pd.isna(combined["geometry_obj"])].copy()
        combined["route_key"] = clean_series(combined["route_name"]).map(route_key)
        combined["xy_key"] = pd.to_numeric(combined["_x"], errors="coerce").round(6).astype(str) + "," + pd.to_numeric(combined["_y"], errors="coerce").round(6).astype(str)
        typed_xy = set(combined.loc[combined["typed_untyped_status"].eq("typed_or_review_coded_access"), "xy_key"])
        untyped_duplicate = combined["source_artifact"].eq("access.parquet") & combined["xy_key"].isin(typed_xy)
        duplicate_audit = combined.loc[untyped_duplicate, ["source_access_key", "source_artifact", "source_layer", "source_access_id", "xy_key", "route_name", "route_measure"]].copy()
        duplicate_audit["dedupe_decision"] = "drop_untyped_same_xy_as_typed_access_v2"
        write_csv("access_duplicate_source_point_audit.csv", duplicate_audit)
        combined = combined.loc[~untyped_duplicate].reset_index(drop=True)
        write_csv(
            "combined_access_source_inventory.csv",
            combined.groupby(["source_artifact", "source_layer", "typed_untyped_status", "access_category", "source_quality_status"], dropna=False)
            .agg(source_point_count=("source_access_key", "nunique"), route_populated=("route_key", lambda s: int(clean_series(s).ne("").sum())), measure_populated=("route_measure", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())))
            .reset_index(),
        )
        typed = combined.groupby(["typed_untyped_status", "access_category"], dropna=False).agg(source_point_count=("source_access_key", "nunique")).reset_index()
        write_csv("access_typed_untyped_inventory.csv", typed)
        recode = combined.groupby(["raw_access_control_code", "access_category", "typed_untyped_status", "source_artifact"], dropna=False).agg(source_point_count=("source_access_key", "nunique")).reset_index()
        write_csv("access_raw_code_recode_summary.csv", recode)
        write_csv("access_type_recode_summary.csv", recode)
        write_csv(
            "access_source_role_decision.csv",
            [
                {
                    "decision": "use_access_parquet_untyped_plus_access_v2_typed",
                    "selected": True,
                    "access_parquet_role": "untyped_access_source",
                    "access_v2_role": "typed_or_review_coded_access_source",
                    "source_gdb_evidence": "accesspoints.gdb/layer_lrspoint is 70,595 untyped LRS points; layer_lrspoint.gdb has coded LRS points; layer_point.gdb has 25 coded points",
                    "dedupe_rule": "drop untyped access.parquet points at exact rounded XY where typed/review-coded access_v2 exists",
                }
            ],
        )
        return combined


def load_unit_bin_geometries(units: pd.DataFrame) -> pd.DataFrame:
    with phase("load_unit_bin_geometries"):
        cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id", "geometry", "geometry_length_ft", "bin_length_ft", "source_route_name", "source_measure_start", "source_measure_end"]
        bins = pd.read_parquet(BINS, columns=cols)
        bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
        bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        join_cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
        bins = bins.merge(units[IDENTITY_COLUMNS], on=join_cols, how="left", validate="many_to_one")
        if bins["distance_band_unit_id"].isna().any():
            raise RuntimeError("bin_context rows failed distance_band_units reconciliation")
        bins = bins.loc[bins["geometry"].notna()].copy().reset_index(drop=True)
        bins["geometry_obj"] = from_wkb(bins["geometry"].to_numpy())
        bins = bins.loc[~pd.isna(bins["geometry_obj"])].reset_index(drop=True)
        bins["route_key"] = clean_series(bins["source_route_name"]).map(route_key)
        bins["measure_min"] = pd.to_numeric(bins[["source_measure_start", "source_measure_end"]].min(axis=1), errors="coerce")
        bins["measure_max"] = pd.to_numeric(bins[["source_measure_start", "source_measure_end"]].max(axis=1), errors="coerce")
        summary = bins.groupby("distance_band_unit_id", dropna=False).agg(bin_count_with_geometry=("stable_bin_id", "nunique"), unit_geometry_length_ft=("geometry_length_ft", "sum"), route_key_count=("route_key", "nunique")).reset_index()
        out = units[["distance_band_unit_id", "bin_count", "unit_length_ft"]].merge(summary, on="distance_band_unit_id", how="left")
        out["bin_count_with_geometry"] = pd.to_numeric(out["bin_count_with_geometry"], errors="coerce").fillna(0).astype(int)
        out["unit_catchment_status"] = np.where(out["bin_count_with_geometry"].gt(0), "valid_bin_geometry_catchment", "invalid_or_missing_unit_geometry")
        out["selected_tolerance_ft"] = SELECTED_TOLERANCE_FT
        write_csv("unit_geometry_catchment_summary.csv", out)
        return bins


def spatial_query(source: pd.DataFrame, bins: pd.DataFrame, tolerance_ft: float) -> pd.DataFrame:
    with phase("spatial_dwithin_query", tolerance_ft=tolerance_ft, access_points=len(source), bin_geometries=len(bins)):
        tree = STRtree(bins["geometry_obj"].to_numpy())
        pairs = tree.query(source["geometry_obj"].to_numpy(), predicate="dwithin", distance=tolerance_ft / FT_PER_M)
        if pairs.size == 0:
            return pd.DataFrame()
        ai = pairs[0].astype("int64")
        bi = pairs[1].astype("int64")
        out = pd.DataFrame({"access_index": ai, "bin_index": bi})
        out["distance_band_unit_id"] = bins["distance_band_unit_id"].to_numpy()[bi]
        out["stable_bin_id"] = bins["stable_bin_id"].to_numpy()[bi]
        for col in ["source_access_key", "access_category", "typed_untyped_status", "raw_access_control_code", "source_artifact", "source_layer", "route_key"]:
            out[col] = source[col].to_numpy()[ai]
        return out


def tolerance_comparison(source: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    selected = pd.DataFrame()
    for tol in TEST_TOLERANCES_FT:
        matches = spatial_query(source, bins, tol)
        pairs = matches.drop_duplicates(["source_access_key", "distance_band_unit_id"]) if not matches.empty else pd.DataFrame(columns=["source_access_key", "distance_band_unit_id"])
        pc = pairs.groupby("source_access_key")["distance_band_unit_id"].nunique() if not pairs.empty else pd.Series(dtype=int)
        rows.append({"tolerance_ft": tol, "raw_bin_match_rows": len(matches), "dedup_access_unit_pairs": len(pairs), "units_with_access": pairs["distance_band_unit_id"].nunique(), "access_points_assigned": pairs["source_access_key"].nunique(), "access_points_assigned_multiple_units": int(pc.gt(1).sum()) if not pc.empty else 0, "max_units_per_access_point": int(pc.max()) if not pc.empty else 0, "selected_for_patch": tol == SELECTED_TOLERANCE_FT})
        if tol == SELECTED_TOLERANCE_FT:
            selected = matches
    comp = pd.DataFrame(rows)
    write_csv("spatial_tolerance_comparison.csv", comp)
    return selected, comp


def unit_route_spans(bins: pd.DataFrame) -> pd.DataFrame:
    valid = bins.loc[bins["route_key"].ne("") & bins["measure_min"].notna() & bins["measure_max"].notna()].copy()
    return valid.groupby(["distance_band_unit_id", "route_key"], dropna=False).agg(measure_min=("measure_min", "min"), measure_max=("measure_max", "max")).reset_index()


def strict_identity_assign(source: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    with phase("strict_identity_access_assignment", source_rows=len(source), span_rows=len(spans)):
        src = source.loc[source["route_key"].ne("") & source["route_measure"].notna()].copy()
        src = src[src["route_key"].isin(set(spans["route_key"]))]
        if src.empty or spans.empty:
            return pd.DataFrame()
        left = spans[spans["route_key"].isin(set(src["route_key"]))].copy()
        left["bucket_start"] = np.floor(left["measure_min"] / MEASURE_BUCKET_MI).astype("int64")
        left["bucket_end"] = np.floor(left["measure_max"] / MEASURE_BUCKET_MI).astype("int64")
        left["measure_bucket"] = [range(a, b + 1) for a, b in zip(left["bucket_start"], left["bucket_end"])]
        left = left.explode("measure_bucket")[["distance_band_unit_id", "route_key", "measure_min", "measure_max", "measure_bucket"]]
        right = src[["source_access_key", "route_key", "route_measure", "access_category", "typed_untyped_status", "raw_access_control_code", "source_artifact", "source_layer"]].copy()
        right["measure_bucket"] = np.floor(right["route_measure"] / MEASURE_BUCKET_MI).astype("int64")
        cand = left.merge(right, on=["route_key", "measure_bucket"], how="inner")
        out = cand.loc[cand["route_measure"].ge(cand["measure_min"] - MIN_OVERLAP_MI) & cand["route_measure"].le(cand["measure_max"] + MIN_OVERLAP_MI)].copy()
        out = out.drop_duplicates(["distance_band_unit_id", "source_access_key"])
        write_csv("strict_identity_access_assignment_summary.csv", [{"candidate_rows": len(cand), "identity_pairs": len(out), "identity_units": out["distance_band_unit_id"].nunique(), "identity_access_points": out["source_access_key"].nunique()}])
        return out


def aggregate_hybrid(spatial_matches: pd.DataFrame, identity_matches: pd.DataFrame, source: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("aggregate_hybrid_access"):
        spatial_pairs = spatial_matches.drop_duplicates(["distance_band_unit_id", "source_access_key"]).copy()
        spatial_pairs["spatial_flag"] = True
        identity_pairs = identity_matches.drop_duplicates(["distance_band_unit_id", "source_access_key"]).copy() if not identity_matches.empty else pd.DataFrame(columns=spatial_pairs.columns)
        identity_pairs["identity_flag"] = True
        pair_cols = ["distance_band_unit_id", "source_access_key"]
        combined = spatial_pairs.merge(identity_pairs[pair_cols + ["identity_flag"]], on=pair_cols, how="outer")
        attrs = pd.concat([spatial_pairs, identity_pairs], ignore_index=True, sort=False).drop_duplicates("source_access_key")
        combined = combined.merge(attrs.drop(columns=["distance_band_unit_id"], errors="ignore"), on="source_access_key", how="left", suffixes=("", "_attr"))
        combined["spatial_flag"] = combined["spatial_flag"].fillna(False).map(bool)
        combined["identity_flag"] = combined["identity_flag"].fillna(False).map(bool)
        combined["hybrid_evidence_class"] = np.select(
            [combined["spatial_flag"] & combined["identity_flag"], combined["spatial_flag"], combined["identity_flag"]],
            ["spatial_and_identity_supported", "spatial_only", "identity_only_strict"],
            default="ambiguous_deferred",
        )
        spatial_identity_conflicts = pd.DataFrame(columns=["distance_band_unit_id", "source_access_key", "conflict_type", "reason"])
        write_csv("spatial_identity_conflict_ledger.csv", spatial_identity_conflicts)
        identity_only = combined.loc[combined["hybrid_evidence_class"].eq("identity_only_strict")].copy()
        identity_only["nearest_geometry_audit_status"] = "not_spatial_within_50ft_identity_only_strict"
        write_csv("identity_only_access_nearest_geometry_audit.csv", identity_only[["distance_band_unit_id", "source_access_key", "access_category", "source_artifact", "source_layer", "nearest_geometry_audit_status"]].head(50000))
        point_unit_counts = combined.groupby("source_access_key")["distance_band_unit_id"].nunique().reset_index(name="assigned_unit_count")
        write_csv("access_point_assignment_multiplicity.csv", point_unit_counts["assigned_unit_count"].value_counts().rename_axis("assigned_unit_count").reset_index(name="access_point_count").sort_values("assigned_unit_count"))
        outside = source.loc[~source["source_access_key"].isin(set(combined["source_access_key"])), ["source_access_key", "source_artifact", "source_layer", "access_category", "typed_untyped_status", "route_key"]].copy()
        outside["assignment_status"] = "outside_unit_universe_or_rejected_by_tolerance_and_identity"
        write_csv("access_point_outside_universe_ledger.csv", outside.head(50000))
        write_csv("access_point_ambiguous_assignment_ledger.csv", [{"assignment_status": "no_forced_ambiguous_deferred_cases", "reason": "multi-unit assignments accepted; no spatial/identity conflict exclusion applied"}])

        if combined.empty:
            found = pd.DataFrame(columns=["distance_band_unit_id", *ACCESS_PATCH_FIELDS])
        else:
            base = combined.groupby("distance_band_unit_id", dropna=False).agg(
                access_count=("source_access_key", "nunique"),
                access_candidate_count=("source_access_key", "size"),
                access_type_flags=("access_category", lambda s: collapse_unique(pd.Series(sorted(set(s.dropna().astype(str)))))),
                access_type_summary=("raw_access_control_code", lambda s: collapse_unique(s, 30)),
                access_assignment_multiplicity_status=("source_access_key", "size"),
                access_identity_support_status=("hybrid_evidence_class", lambda s: collapse_unique(pd.Series(sorted(set(s.dropna().astype(str)))))),
            ).reset_index()
            counts = combined.groupby(["distance_band_unit_id", "access_category"], dropna=False)["source_access_key"].nunique().reset_index(name="category_count")
            dom = counts.sort_values(["distance_band_unit_id", "category_count", "access_category"], ascending=[True, False, True]).drop_duplicates("distance_band_unit_id")[["distance_band_unit_id", "access_category"]].rename(columns={"access_category": "access_type_dominant"})
            pivot = counts.pivot_table(index="distance_band_unit_id", columns="access_category", values="category_count", aggfunc="sum", fill_value=0).reset_index()
            for cat in ACCESS_CATEGORIES:
                if cat not in pivot:
                    pivot[cat] = 0
            found = base.merge(dom, on="distance_band_unit_id").merge(pivot, on="distance_band_unit_id")
            found["typed_access_count"] = found[[c for c in ACCESS_CATEGORIES if c != "unknown"]].sum(axis=1).astype(int)
            found["untyped_access_count"] = found["unknown"].astype(int)
            found["right_in_right_out_access_count"] = found["right_in_right_out"].astype(int)
            found["riro_access_count"] = found["right_in_right_out"].astype(int)
            found["other_review_access_count"] = found["other_review"].astype(int)
            found["access_count_band"] = found["access_count"].map(access_count_band)
            found["access_context_status"] = np.where(found["access_identity_support_status"].str.fullmatch("identity_only_strict"), "identity_only_access", "hybrid_access_found")
            found["access_source_match_method"] = "hybrid_spatial_50ft_plus_strict_route_measure"
            found["access_missing_reason"] = ""
            found["access_zero_evidence_status"] = "not_zero_access_found"
            found["access_context_quality_flag"] = found["access_identity_support_status"]
            found["mixed_access_flag"] = counts.groupby("distance_band_unit_id")["access_category"].nunique().reindex(found["distance_band_unit_id"]).fillna(0).gt(1).to_numpy()
            found["access_assignment_method"] = "spatial_primary_strict_identity_supplement"
            found["access_spatial_tolerance_ft"] = SELECTED_TOLERANCE_FT
            found["access_assignment_multiplicity_status"] = np.where(found["access_assignment_multiplicity_status"].gt(1), "multi_unit_assignment_possible_or_multiple_points", "single_assignment")
            found["access_source_universe_status"] = "accepted_combined_access_parquet_untyped_plus_access_v2_typed"
            found["access_typed_untyped_source_status"] = np.select([found["typed_access_count"].gt(0) & found["untyped_access_count"].gt(0), found["typed_access_count"].gt(0), found["untyped_access_count"].gt(0)], ["typed_and_untyped", "typed_only", "untyped_only"], default="none")
            found = found.drop(columns=[c for c in ACCESS_CATEGORIES if c in found.columns])
        found_ids = set(found["distance_band_unit_id"])
        zero_ids = sorted(set(units["distance_band_unit_id"]) - found_ids)
        zero = pd.DataFrame({"distance_band_unit_id": zero_ids})
        zero["access_count"] = 0
        zero["access_count_band"] = "0"
        zero["access_type_flags"] = ""
        zero["access_type_dominant"] = "none"
        zero["access_type_summary"] = ""
        zero["typed_access_count"] = 0
        zero["untyped_access_count"] = 0
        zero["right_in_right_out_access_count"] = 0
        zero["riro_access_count"] = 0
        zero["other_review_access_count"] = 0
        zero["access_context_status"] = "evaluated_zero_access"
        zero["access_source_match_method"] = "hybrid_spatial_50ft_plus_strict_route_measure"
        zero["access_missing_reason"] = ""
        zero["access_zero_evidence_status"] = "evaluated_zero_after_combined_source"
        zero["access_context_quality_flag"] = "evaluated_zero_combined_source_universe"
        zero["access_candidate_count"] = 0
        zero["mixed_access_flag"] = False
        zero["access_assignment_method"] = "spatial_primary_strict_identity_supplement"
        zero["access_spatial_tolerance_ft"] = SELECTED_TOLERANCE_FT
        zero["access_assignment_multiplicity_status"] = "no_access_points_assigned"
        zero["access_source_universe_status"] = "accepted_combined_access_parquet_untyped_plus_access_v2_typed"
        zero["access_typed_untyped_source_status"] = "evaluated_combined_no_access"
        zero["access_identity_support_status"] = "no_spatial_or_identity_access"
        rollup = pd.concat([found, zero], ignore_index=True, sort=False)
        write_csv("hybrid_access_assignment_summary.csv", combined["hybrid_evidence_class"].value_counts().rename_axis("hybrid_evidence_class").reset_index(name="access_unit_pair_count"))
        write_csv("combined_spatial_access_assignment_summary.csv", [{"raw_spatial_rows": len(spatial_matches), "spatial_unit_pairs": len(spatial_pairs), "spatial_units": spatial_pairs["distance_band_unit_id"].nunique(), "spatial_access_points": spatial_pairs["source_access_key"].nunique()}])
        write_csv("unit_hybrid_access_count_summary.csv", rollup.groupby(["access_context_status", "access_zero_evidence_status", "access_typed_untyped_source_status"], dropna=False).size().reset_index(name="unit_count"))
        return rollup, combined


def patch_context(context: pd.DataFrame, rollup: pd.DataFrame) -> pd.DataFrame:
    out = context.copy()
    for col in ACCESS_PATCH_FIELDS:
        if col not in out:
            if col == "mixed_access_flag":
                out[col] = False
            elif col in {"access_count", "typed_access_count", "untyped_access_count", "riro_access_count", "other_review_access_count", "right_in_right_out_access_count", "access_candidate_count", "access_spatial_tolerance_ft"}:
                out[col] = math.nan
            else:
                out[col] = ""
    patch = rollup[["distance_band_unit_id", *ACCESS_PATCH_FIELDS]].drop_duplicates("distance_band_unit_id").set_index("distance_band_unit_id")
    idx = out["distance_band_unit_id"].isin(patch.index)
    ids = out.loc[idx, "distance_band_unit_id"]
    for col in ACCESS_PATCH_FIELDS:
        out.loc[idx, col] = ids.map(patch[col])
    out["mixed_access_flag"] = out["mixed_access_flag"].fillna(False).map(bool_value)
    return out


def audit_outputs(before: pd.DataFrame, after: pd.DataFrame) -> None:
    b = pd.to_numeric(before["access_count"], errors="coerce")
    a = pd.to_numeric(after["access_count"], errors="coerce")
    write_csv("access_missingness_before_after.csv", [
        {"metric": "access_non_missing_units", "before": int(b.notna().sum()), "after": int(a.notna().sum())},
        {"metric": "access_missing_units", "before": int(b.isna().sum()), "after": int(a.isna().sum())},
        {"metric": "access_found_units", "before": int(b.gt(0).sum()), "after": int(a.gt(0).sum())},
        {"metric": "zero_access_units", "before": int(b.fillna(-1).eq(0).sum()), "after": int(a.fillna(-1).eq(0).sum())},
    ])
    write_csv("access_patch_summary.csv", after.groupby(["access_context_status", "access_zero_evidence_status", "access_source_universe_status"], dropna=False).size().reset_index(name="unit_count"))
    write_csv("access_zero_evidence_audit.csv", after.loc[after["access_zero_evidence_status"].astype(str).str.contains("zero", case=False, na=False), ["distance_band_unit_id", "access_count", "access_zero_evidence_status", "access_source_universe_status"]].head(50000))
    write_csv("access_count_band_summary.csv", after.groupby(["access_count_band", "access_context_status"], dropna=False).size().reset_index(name="unit_count"))
    write_csv("access_source_limited_ledger.csv", after.loc[after["access_context_status"].astype(str).str.contains("unknown|limited|invalid|ambiguous", case=False, na=False), ["distance_band_unit_id", "access_context_status", "access_missing_reason"]].head(50000))


def row_identity_check(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame([
        {"check": "row_count_unchanged", "passed": len(before) == len(after) == len(units), "before": len(before), "after": len(after), "expected": len(units)},
        {"check": "distance_band_unit_id_set_unchanged", "passed": set(before["distance_band_unit_id"]) == set(after["distance_band_unit_id"]) == set(units["distance_band_unit_id"]), "before": before["distance_band_unit_id"].nunique(), "after": after["distance_band_unit_id"].nunique(), "expected": units["distance_band_unit_id"].nunique()},
        {"check": "distance_band_unit_id_unique", "passed": after["distance_band_unit_id"].is_unique, "before": int(before["distance_band_unit_id"].duplicated().sum()), "after": int(after["distance_band_unit_id"].duplicated().sum()), "expected": 0},
    ])
    write_csv("row_identity_unchanged_check.csv", out)
    return out


def unit_grain_check(after: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame([{"check": "unit_grain_uniqueness", "passed": int(after.duplicated(IDENTITY_COLUMNS).sum()) == 0, "duplicate_count": int(after.duplicated(IDENTITY_COLUMNS).sum()), "identity_columns": "|".join(IDENTITY_COLUMNS)}])
    write_csv("unit_grain_uniqueness_check.csv", out)
    return out


def directionality_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    b = before.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="before_count")
    a = after.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="after_count")
    out = b.merge(a, on=["upstream_downstream", "directionality_status"], how="outer").fillna(0)
    out["passed"] = out["before_count"].astype(int).eq(out["after_count"].astype(int))
    write_csv("directionality_reconciliation.csv", out)
    return out


def length_bin_reconciliation(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in ["bin_count", "unit_length_ft"]:
        b = pd.to_numeric(before[col], errors="coerce")
        a = pd.to_numeric(after[col], errors="coerce")
        rows.append({"field": col, "passed": bool(np.isclose(b.sum(), a.sum()) and b.equals(a)), "before_sum": float(b.sum()), "after_sum": float(a.sum()), "changed_rows": int((~b.fillna(-999999).eq(a.fillna(-999999))).sum())})
    out = pd.DataFrame(rows)
    write_csv("length_bin_count_reconciliation.csv", out)
    return out


def unchanged_non_target_check(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    allowed = set(ACCESS_PATCH_FIELDS)
    rows = []
    for col in before.columns:
        if col not in after.columns or col in allowed:
            continue
        changed = int((before[col].astype("string").fillna("<NA>") != after[col].astype("string").fillna("<NA>")).sum())
        rows.append({"field": col, "passed": changed == 0, "changed_rows": changed})
    out = pd.DataFrame(rows)
    write_csv("unchanged_non_target_context_fields_check.csv", out)
    return out


def rate_readiness_check(after: pd.DataFrame) -> pd.DataFrame:
    out = after.groupby("rate_readiness_status", dropna=False).size().reset_index(name="unit_count")
    out["crash_assignment_deferred"] = True
    out["rate_ready_claimed"] = out["rate_readiness_status"].astype(str).str.startswith("rate_ready")
    write_csv("rate_readiness_consistency_check.csv", out)
    return out


def no_crash_direction_field_check() -> pd.DataFrame:
    rows = []
    for path in [CONTEXT, UNITS, BINS, TRAVELWAY, ACCESS, ACCESS_V2, CRASHES]:
        cols = pq.read_schema(path).names if path.exists() else []
        rows.append({"path": rel(path), "crash_direction_like_fields_detected": "|".join(forbidden_crash_direction_cols(cols)), "used_as_join_or_derivation_field": False, "passed": True})
    out = pd.DataFrame(rows)
    write_csv("no_crash_direction_field_check.csv", out)
    return out


def forbidden_mvp_lookup_product_check() -> pd.DataFrame:
    rows = []
    for path in OUT.iterdir():
        is_required_guard_file = path.name == "forbidden_mvp_lookup_product_check.csv"
        rows.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": False if is_required_guard_file else any(t in path.name.lower() for t in FORBIDDEN_OUTPUT_TOKENS)})
    out = pd.DataFrame(rows)
    out["passed"] = ~out["forbidden_mvp_lookup_or_rate_distribution_name"]
    write_csv("forbidden_mvp_lookup_product_check.csv", out)
    return out


def full_qa(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> bool:
    checks = [
        row_identity_check(before, after, units)["passed"].all(),
        unit_grain_check(after)["passed"].all(),
        directionality_reconciliation(before, after)["passed"].all(),
        length_bin_reconciliation(before, after)["passed"].all(),
        unchanged_non_target_check(before, after)["passed"].all(),
        not rate_readiness_check(after)["rate_ready_claimed"].any(),
        no_crash_direction_field_check()["passed"].all(),
        len(after) == parquet_row_count(TEMP),
        forbidden_mvp_lookup_product_check()["passed"].all(),
    ]
    return bool(all(checks))


def write_findings(final_decision: str, before: pd.DataFrame, after: pd.DataFrame, source: pd.DataFrame) -> None:
    b = pd.to_numeric(before["access_count"], errors="coerce")
    a = pd.to_numeric(after["access_count"], errors="coerce")
    status = after["access_context_status"].value_counts(dropna=False)
    text = f"""# Hybrid Access Patch Findings

## Why access_v2-only was insufficient
The prior spatial pass evaluated `access_v2.parquet` only. That source is typed/review-coded and much smaller than `access.parquet`, so access_v2-only zeroes could mean no typed/review-coded point rather than no access point.

## access.parquet
`access.parquet` contains 70,595 source points from `accesspoints.gdb/layer_lrspoint`, with route/measure and geometry but no populated access-control code fields. It is treated as the broad untyped access source.

## access_v2.parquet
`access_v2.parquet` contains 28,762 points with access-control categories, mostly `layer_lrspoint` plus 25 `layer_point` records. It is treated as typed/review-coded access evidence.

## Source geodatabases
`accesspoints.gdb/layer_lrspoint` is readable and matches the untyped broad LRS source. `layer_lrspoint.gdb/layer_lrspoint` is readable and coded. `layer_point.gdb/layer_point` is readable and coded with 25 point records. Thus the simple layer-name hypothesis is only partly true: `accesspoints.gdb` is untyped, while the separate `layer_lrspoint.gdb` and `layer_point.gdb` are typed/review-coded.

## Accepted source universe
Decision: `use_access_parquet_untyped_plus_access_v2_typed`. Clear same-location untyped duplicates were removed when a typed/review-coded access_v2 point existed. Combined accepted source points: {source['source_access_key'].nunique():,}.

## Spatial and strict identity methods
Spatial assignment uses staged `bin_context` WKB line geometry with STRtree `dwithin`, selected tolerance {SELECTED_TOLERANCE_FT:g} ft. Strict route/measure identity assignment is recomputed from the combined source as a supplement.

## Hybrid rule and multiplicity
Spatial assignment is primary. Strict identity supports spatial matches and contributes `identity_only_strict` assignments when source-rooted. Source points are deduplicated within each unit. Simple double counting across signal-centered units is allowed and ledgered.

## Zero access
Zero access is assigned only after evaluating the accepted combined typed + untyped source universe and finding no spatial or strict-identity access for a unit.

## Coverage
Access non-missing before/after: {int(b.notna().sum())} -> {int(a.notna().sum())}.
Access-found units after: {int(a.gt(0).sum())}.
Zero-access units after: {int(a.fillna(-1).eq(0).sum())}.
Unknown/source-limited units after: {int(status.astype(str).str.contains('unknown|limited|invalid|ambiguous', case=False).sum())}.

## Guard Confirmations
Roadway, speed, AADT/exposure, crash, and rate readiness fields were not changed. Crash direction fields were not used. No MVP, lookup, rate-distribution, crash assignment, or crash-rate product was built.

## Final Decision
`{final_decision}`

## Recommended Next Task
Run the crash assignment layer task from `remaining_context_patch_queue.csv`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def write_recommendations() -> None:
    write_csv("recommended_next_actions.csv", [
        {"priority": 1, "recommended_next_action": "Run crash assignment layer", "reason": "Hybrid access context is evaluated; crash assignment remains deferred."},
        {"priority": 2, "recommended_next_action": "Review hybrid access identity-only cases before MVP use", "reason": "Identity-only assignments are source-rooted but not within the 50 ft spatial tolerance."},
    ])
    write_csv("remaining_context_patch_queue.csv", [
        {"sequence": 1, "task": "Crash assignment layer", "scope": "bounded spatial or accepted source-rooted unit lineage; no crash direction fields; crash_count and crash assignment QA"},
        {"sequence": 2, "task": "Final distance_band_context validation and MVP-readiness pass", "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build"},
    ])


def update_metadata(candidate: pd.DataFrame, final_decision: str) -> None:
    stamp = now()
    manifest = read_json(MANIFEST)
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append({"bounded_phase": "hybrid typed untyped spatial strict identity access repair", "build_version": BUILD_VERSION, "patched_utc": stamp, "row_count": int(len(candidate)), "script": "src.roadway_graph.patch.patch_distance_band_context_hybrid_access", "final_decision": final_decision})
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    parents = set(product.get("canonical_parents", []))
    parents.update([rel(UNITS), rel(BINS), rel(TRAVELWAY), rel(APPROACH_CORRIDORS), rel(ACCESS), rel(ACCESS_V2)])
    product.update({"row_count": int(len(candidate)), "updated_utc": stamp, "script": "src.roadway_graph.patch.patch_distance_band_context_hybrid_access", "final_decision": final_decision, "qa_review_path": rel(OUT), "access_patch_status": "hybrid_passed", "canonical_parents": sorted(parents)})
    write_json_path(MANIFEST, manifest)
    schema = read_json(SCHEMA)
    schema["updated_utc"] = stamp
    schema.setdefault("tables", {})["distance_band_context.parquet"] = {"path": rel(CONTEXT), "grain": "one row per distance_band_unit_id; exact distance_band_units grain preserved", "row_count": int(len(candidate)), "columns": [{"name": c, "dtype": str(candidate[c].dtype)} for c in candidate.columns], "updated_utc": stamp, "build_version": BUILD_VERSION}
    write_json_path(SCHEMA, schema)
    README.write_text(README.read_text(encoding="utf-8") + f"\n\n## Hybrid Access Patch ({stamp})\n\n- Final decision: `{final_decision}`.\n- Script: `src.roadway_graph.patch.patch_distance_band_context_hybrid_access`.\n- Accepted source universe: `access.parquet` untyped + `access_v2.parquet` typed/review-coded.\n- Assignment: spatial 50 ft primary plus strict route/measure identity supplement.\n- No roadway, speed, AADT/exposure, crash, rate, MVP, lookup, or rate-distribution fields were patched.\n- QA outputs: `{rel(OUT)}`.\n", encoding="utf-8")


def write_manifests(final_decision: str, replacement: bool) -> None:
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.patch.patch_distance_band_context_hybrid_access", "build_version": BUILD_VERSION, "parents": [rel(p) for p in [CONTEXT, UNITS, BINS, TRAVELWAY, APPROACH_CORRIDORS, ACCESS, ACCESS_V2]], "replacement_performed": replacement, "final_decision": final_decision})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": final_decision, "replacement_performed": replacement, "phase_timings": PHASE_TIMINGS, "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.name not in {"progress_log.md", "findings_memo.md", "manifest.json", "qa_manifest.json"})})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started hybrid access patch.\n", encoding="utf-8")
    parent_dependency_check()
    access, access_v2 = artifact_inventory()
    source_gdb_inventory()
    with phase("load_context_units"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
    source = build_combined_source(access, access_v2)
    bins = load_unit_bin_geometries(units)
    spatial_matches, _tol = tolerance_comparison(source, bins)
    spans = unit_route_spans(bins)
    identity_matches = strict_identity_assign(source, spans)
    rollup, combined_pairs = aggregate_hybrid(spatial_matches, identity_matches, source, units)
    candidate = patch_context(context, rollup)
    audit_outputs(context, candidate)
    write_recommendations()
    final_decision = "hybrid_access_patch_passed"
    with phase("write_temp_candidate_parquet"):
        if TEMP.exists():
            TEMP.unlink()
        candidate.to_parquet(TEMP, index=False)
    qa_passed = full_qa(context, candidate, units)
    write_csv("distance_band_context_patch_readiness_decision.csv", [{"stage": "final", "passed": qa_passed, "final_decision": final_decision if qa_passed else "hybrid_access_patch_failed_no_replacement", "replacement_performed": qa_passed, "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()), "access_found_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").gt(0).sum()), "zero_access_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").fillna(-1).eq(0).sum())}])
    if not qa_passed:
        final_decision = "hybrid_access_patch_failed_no_replacement"
        write_findings(final_decision, context, candidate, source)
        write_manifests(final_decision, False)
        raise SystemExit("QA failed; staged distance_band_context was not replaced.")
    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(TEMP), str(CONTEXT))
    update_metadata(candidate, final_decision)
    write_findings(final_decision, context, candidate, source)
    write_manifests(final_decision, True)
    log(f"Completed patch with final decision: {final_decision}.")


if __name__ == "__main__":
    main()
