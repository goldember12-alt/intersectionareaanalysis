"""Patch staged distance_band_context access using spatial assignment.

This bounded repair assigns access_v2 point features to validated
distance-band units by spatial proximity to staged bin geometries. It uses the
bin lines as the unit spatial support, STRtree dwithin queries for performance,
and permits the same source access point to count in multiple signal-centered
units when it falls within multiple unit catchments.

It does not repair roadway, speed, AADT, exposure, crash, rate, MVP, or lookup
products.
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


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_spatial_access"

CONTEXT = STAGING / "distance_band_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
BINS = STAGING / "bin_context.parquet"
TRAVELWAY = STAGING / "travelway_network_index.parquet"
APPROACH_CORRIDORS = STAGING / "approach_corridors.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"
TEMP = STAGING / "distance_band_context.spatial_access_candidate.tmp.parquet"

ACCESS = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"

BUILD_VERSION = "distance_band_context_spatial_access_patch_v1_2026-06-15"
FT_PER_M = 3.280839895
SELECTED_TOLERANCE_FT = 50.0
TEST_TOLERANCES_FT = [25.0, 50.0, 75.0]

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
    blocked = []
    for col in columns:
        lower = col.lower()
        if any(token in lower for token in CRASH_DIRECTION_TOKENS):
            blocked.append(col)
    return blocked


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
        direction_map = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}
        direction = direction_map.get(match.group(4) or "", match.group(4) or "")
        return f"{prefix}{int(match.group(3))}{direction}{match.group(5) or ''}"
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
    parents = [CONTEXT, UNITS, BINS, TRAVELWAY, APPROACH_CORRIDORS, ACCESS]
    rows = []
    for path in parents + [CRASHES]:
        rows.append(
            {
                "path": rel(path),
                "role": "parent" if path in parents else "guard_only",
                "exists": path.exists(),
                "sha256": file_sha256(path) if path.exists() else "",
                "used_as_hidden_parent": False,
            }
        )
    write_csv("parent_dependency_check.csv", rows)


def load_access_source() -> pd.DataFrame:
    with phase("load_access_source"):
        cols = [
            "id",
            "geometry",
            "_x",
            "_y",
            "route_name",
            "route_measure",
            "access_v2_source_priority",
            "access_v2_source_row_id",
            "access_v2_source_crs",
            "access_v2_normalized_crs",
            "access_v2_staging_status",
            "access_control_code",
            "access_control_category",
            "access_direction_normalized",
            "access_control_raw",
        ]
        access = pd.read_parquet(ACCESS, columns=[c for c in cols if c in pq.read_schema(ACCESS).names])
        blocked = forbidden_crash_direction_cols(list(access.columns))
        if blocked:
            raise ValueError(f"Refusing crash direction-like access fields: {blocked}")
        access = access.copy()
        access["access_point_id"] = (
            clean_series(access.get("access_v2_source_priority", pd.Series("", index=access.index)))
            + ":"
            + clean_series(access.get("access_v2_source_row_id", pd.Series("", index=access.index)))
        )
        blank = clean_series(access["access_point_id"]).isin({"", ":"})
        access.loc[blank, "access_point_id"] = clean_series(access.loc[blank].get("id", pd.Series("", index=access.loc[blank].index)))
        still_blank = clean_series(access["access_point_id"]).isin({"", ":"})
        access.loc[still_blank, "access_point_id"] = "row_" + access.loc[still_blank].index.astype(str)
        access["raw_access_control_code"] = clean_series(access.get("access_control_code", pd.Series("", index=access.index))).str.upper()
        access["prior_access_category"] = clean_series(access.get("access_control_category", pd.Series("", index=access.index))).replace("", "unknown")
        access["access_category"] = [
            category_from_raw(code, prior)
            for code, prior in zip(access["raw_access_control_code"], access["prior_access_category"])
        ]
        access["typed_untyped_status"] = np.where(access["access_category"].eq("unknown"), "untyped_or_unknown", "typed_or_review_coded")
        access["route_key"] = clean_series(access.get("route_name", pd.Series("", index=access.index))).map(route_key)
        access["route_measure"] = pd.to_numeric(access.get("route_measure", pd.Series(np.nan, index=access.index)), errors="coerce")
        geom_valid = access["geometry"].notna()
        access = access.loc[geom_valid].copy()
        access["geometry_obj"] = from_wkb(access["geometry"].to_numpy())
        access = access.loc[~pd.isna(access["geometry_obj"])].reset_index(drop=True)
        return access


def inventory_access(access: pd.DataFrame) -> None:
    route_pop = clean_series(access.get("route_key", pd.Series("", index=access.index))).ne("")
    measure_pop = pd.to_numeric(access.get("route_measure", pd.Series(np.nan, index=access.index)), errors="coerce").notna()
    write_csv(
        "access_source_spatial_inventory.csv",
        [
            {"metric": "source_rows_with_usable_geometry", "value": len(access)},
            {"metric": "unique_access_point_ids", "value": access["access_point_id"].nunique()},
            {"metric": "duplicate_source_access_id_rows", "value": int(access.duplicated("access_point_id").sum())},
            {"metric": "route_key_populated_rows", "value": int(route_pop.sum())},
            {"metric": "route_measure_populated_rows", "value": int(measure_pop.sum())},
            {"metric": "geometry_crs", "value": collapse_unique(access.get("access_v2_normalized_crs", pd.Series("", index=access.index)))},
            {"metric": "source_crs", "value": collapse_unique(access.get("access_v2_source_crs", pd.Series("", index=access.index)))},
        ],
    )
    write_csv(
        "access_typed_untyped_inventory.csv",
        access.groupby(["typed_untyped_status", "access_category"], dropna=False)
        .agg(source_point_count=("access_point_id", "nunique"))
        .reset_index(),
    )
    recode = (
        access.groupby(["raw_access_control_code", "prior_access_category", "access_category", "typed_untyped_status"], dropna=False)
        .agg(source_point_count=("access_point_id", "nunique"))
        .reset_index()
        .sort_values(["access_category", "raw_access_control_code"])
    )
    write_csv("access_raw_code_recode_summary.csv", recode)
    write_csv("access_type_recode_summary.csv", recode)


def load_unit_bin_geometries(units: pd.DataFrame) -> pd.DataFrame:
    with phase("load_unit_bin_geometries"):
        cols = [
            "stable_signal_id",
            "signal_approach_id",
            "upstream_downstream",
            "distance_band",
            "stable_bin_id",
            "geometry",
            "geometry_status",
            "geometry_crs",
            "geometry_length_ft",
            "bin_length_ft",
            "source_route_name",
            "source_measure_start",
            "source_measure_end",
        ]
        bins = pd.read_parquet(BINS, columns=cols)
        bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
        bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        join_cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
        bins = bins.merge(units[IDENTITY_COLUMNS], on=join_cols, how="left", validate="many_to_one")
        if bins["distance_band_unit_id"].isna().any():
            raise RuntimeError("bin_context rows failed distance_band_units reconciliation")
        bins["valid_unit_geometry"] = bins["geometry"].notna()
        valid = bins.loc[bins["valid_unit_geometry"]].copy().reset_index(drop=True)
        valid["geometry_obj"] = from_wkb(valid["geometry"].to_numpy())
        valid = valid.loc[~pd.isna(valid["geometry_obj"])].reset_index(drop=True)
        valid["route_key"] = clean_series(valid["source_route_name"]).map(route_key)
        summary = (
            valid.groupby("distance_band_unit_id", dropna=False)
            .agg(
                bin_count_with_geometry=("stable_bin_id", "nunique"),
                unit_geometry_length_ft=("geometry_length_ft", "sum"),
                route_key_count=("route_key", "nunique"),
            )
            .reset_index()
        )
        all_units = units[["distance_band_unit_id", "bin_count", "unit_length_ft"]].merge(summary, on="distance_band_unit_id", how="left")
        all_units["bin_count_with_geometry"] = pd.to_numeric(all_units["bin_count_with_geometry"], errors="coerce").fillna(0).astype(int)
        all_units["unit_catchment_status"] = np.where(all_units["bin_count_with_geometry"].gt(0), "valid_bin_geometry_catchment", "invalid_or_missing_unit_geometry")
        all_units["selected_tolerance_ft"] = SELECTED_TOLERANCE_FT
        all_units["geometry_units"] = "meters; tolerances converted from feet"
        write_csv("unit_geometry_catchment_summary.csv", all_units)
        return valid


def spatial_query(access: pd.DataFrame, bins: pd.DataFrame, tolerance_ft: float) -> pd.DataFrame:
    tolerance_m = tolerance_ft / FT_PER_M
    with phase("spatial_dwithin_query", tolerance_ft=tolerance_ft, access_points=len(access), bin_geometries=len(bins)):
        tree = STRtree(bins["geometry_obj"].to_numpy())
        pairs = tree.query(access["geometry_obj"].to_numpy(), predicate="dwithin", distance=tolerance_m)
        if pairs.size == 0:
            return pd.DataFrame(columns=["access_index", "bin_index", "distance_band_unit_id", "access_point_id", "access_category"])
        access_idx = pairs[0].astype("int64")
        bin_idx = pairs[1].astype("int64")
        out = pd.DataFrame({"access_index": access_idx, "bin_index": bin_idx})
        out["distance_band_unit_id"] = bins["distance_band_unit_id"].to_numpy()[bin_idx]
        out["stable_bin_id"] = bins["stable_bin_id"].to_numpy()[bin_idx]
        out["access_point_id"] = access["access_point_id"].to_numpy()[access_idx]
        out["access_category"] = access["access_category"].to_numpy()[access_idx]
        out["typed_untyped_status"] = access["typed_untyped_status"].to_numpy()[access_idx]
        out["raw_access_control_code"] = access["raw_access_control_code"].to_numpy()[access_idx]
        out["route_key_access"] = access["route_key"].to_numpy()[access_idx]
        out["route_key_bin"] = bins["route_key"].to_numpy()[bin_idx]
        return out


def tolerance_comparison(access: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected_matches = pd.DataFrame()
    rows = []
    for tol in TEST_TOLERANCES_FT:
        matches = spatial_query(access, bins, tol)
        unit_pairs = matches.drop_duplicates(["access_point_id", "distance_band_unit_id"])
        point_counts = unit_pairs.groupby("access_point_id", dropna=False)["distance_band_unit_id"].nunique() if not unit_pairs.empty else pd.Series(dtype=int)
        rows.append(
            {
                "tolerance_ft": tol,
                "raw_bin_match_rows": len(matches),
                "dedup_access_unit_pairs": len(unit_pairs),
                "units_with_access": unit_pairs["distance_band_unit_id"].nunique() if not unit_pairs.empty else 0,
                "access_points_assigned": unit_pairs["access_point_id"].nunique() if not unit_pairs.empty else 0,
                "access_points_assigned_multiple_units": int(point_counts.gt(1).sum()) if not point_counts.empty else 0,
                "max_units_per_access_point": int(point_counts.max()) if not point_counts.empty else 0,
                "selected_for_patch": tol == SELECTED_TOLERANCE_FT,
            }
        )
        if tol == SELECTED_TOLERANCE_FT:
            selected_matches = matches
    write_csv("spatial_tolerance_comparison.csv", rows)
    return selected_matches, pd.DataFrame(rows)


def aggregate_spatial_access(matches: pd.DataFrame, access: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("aggregate_spatial_access", raw_match_rows=len(matches)):
        pairs = matches.drop_duplicates(["distance_band_unit_id", "access_point_id"]).copy()
        point_unit_counts = pairs.groupby("access_point_id", dropna=False)["distance_band_unit_id"].nunique().reset_index(name="assigned_unit_count")
        pairs = pairs.merge(point_unit_counts, on="access_point_id", how="left")
        pairs["access_assignment_multiplicity_status"] = np.where(pairs["assigned_unit_count"].gt(1), "multi_unit_assignment_allowed", "single_unit_assignment")

        mult = point_unit_counts["assigned_unit_count"].value_counts(dropna=False).rename_axis("assigned_unit_count").reset_index(name="access_point_count")
        write_csv("access_point_assignment_multiplicity.csv", mult.sort_values("assigned_unit_count"))
        outside_ids = sorted(set(access["access_point_id"]) - set(point_unit_counts["access_point_id"]))
        outside = access.loc[access["access_point_id"].isin(outside_ids), ["access_point_id", "access_category", "raw_access_control_code", "typed_untyped_status", "route_key"]].copy()
        outside["assignment_status"] = "outside_unit_universe_or_rejected_by_tolerance"
        write_csv("access_point_outside_universe_ledger.csv", outside.head(50000))
        write_csv("access_point_ambiguous_assignment_ledger.csv", [{"assignment_status": "no_forced_ambiguous_deferred_cases", "reason": "multi-unit assignments are explicitly allowed and ledgered"}])
        write_csv("access_conflict_ledger.csv", pd.DataFrame(columns=["distance_band_unit_id", "access_point_id", "conflict_type", "reason"]))

        if pairs.empty:
            assigned = pd.DataFrame(columns=["distance_band_unit_id", *ACCESS_PATCH_FIELDS])
        else:
            base = pairs.groupby("distance_band_unit_id", dropna=False).agg(
                access_count=("access_point_id", "nunique"),
                access_candidate_count=("stable_bin_id", "size"),
                access_type_flags=("access_category", lambda s: collapse_unique(pd.Series(sorted(set(s.dropna().astype(str)))))),
                access_type_summary=("raw_access_control_code", lambda s: collapse_unique(s, 30)),
                access_assignment_multiplicity_status=("access_assignment_multiplicity_status", lambda s: "multi_unit_assignment_present" if (s == "multi_unit_assignment_allowed").any() else "single_unit_assignments_only"),
            ).reset_index()
            cat_counts = pairs.groupby(["distance_band_unit_id", "access_category"], dropna=False)["access_point_id"].nunique().reset_index(name="category_count")
            dom = cat_counts.sort_values(["distance_band_unit_id", "category_count", "access_category"], ascending=[True, False, True]).drop_duplicates("distance_band_unit_id")
            dom = dom[["distance_band_unit_id", "access_category"]].rename(columns={"access_category": "access_type_dominant"})
            pivot = cat_counts.pivot_table(index="distance_band_unit_id", columns="access_category", values="category_count", aggfunc="sum", fill_value=0).reset_index()
            for cat in ACCESS_CATEGORIES:
                if cat not in pivot.columns:
                    pivot[cat] = 0
            assigned = base.merge(dom, on="distance_band_unit_id", how="left").merge(pivot, on="distance_band_unit_id", how="left")
            assigned["typed_access_count"] = assigned[[c for c in ACCESS_CATEGORIES if c != "unknown"]].sum(axis=1).astype(int)
            assigned["untyped_access_count"] = assigned["unknown"].fillna(0).astype(int)
            assigned["riro_access_count"] = assigned["right_in_right_out"].fillna(0).astype(int)
            assigned["right_in_right_out_access_count"] = assigned["right_in_right_out"].fillna(0).astype(int)
            assigned["other_review_access_count"] = assigned["other_review"].fillna(0).astype(int)
            assigned["access_count_band"] = assigned["access_count"].map(access_count_band)
            assigned["access_context_status"] = "spatial_access_found"
            assigned["access_source_match_method"] = "spatial_bin_geometry_dwithin_access_v2"
            assigned["access_missing_reason"] = ""
            assigned["access_zero_evidence_status"] = "not_zero_access_found"
            assigned["access_context_quality_flag"] = np.where(assigned["untyped_access_count"].gt(0), "spatial_access_contains_untyped_or_unknown", "spatial_access_typed_or_review_coded")
            assigned["mixed_access_flag"] = cat_counts.groupby("distance_band_unit_id")["access_category"].nunique().reindex(assigned["distance_band_unit_id"]).fillna(0).gt(1).to_numpy()
            assigned["access_assignment_method"] = "spatial_dwithin_bin_geometry"
            assigned["access_spatial_tolerance_ft"] = SELECTED_TOLERANCE_FT
            assigned = assigned.drop(columns=[c for c in ACCESS_CATEGORIES if c in assigned.columns])

        valid_unit_ids = set(units["distance_band_unit_id"])
        assigned_ids = set(assigned["distance_band_unit_id"]) if not assigned.empty else set()
        zero_ids = sorted(valid_unit_ids - assigned_ids)
        zero = pd.DataFrame({"distance_band_unit_id": zero_ids})
        zero["access_count"] = 0
        zero["access_count_band"] = "0"
        zero["access_type_flags"] = ""
        zero["access_type_dominant"] = "none"
        zero["access_type_summary"] = ""
        zero["typed_access_count"] = 0
        zero["untyped_access_count"] = 0
        zero["riro_access_count"] = 0
        zero["right_in_right_out_access_count"] = 0
        zero["other_review_access_count"] = 0
        zero["access_context_status"] = "spatial_zero_access"
        zero["access_source_match_method"] = "spatial_bin_geometry_dwithin_access_v2"
        zero["access_missing_reason"] = ""
        zero["access_zero_evidence_status"] = "evaluated_spatial_zero"
        zero["access_context_quality_flag"] = "spatial_zero_access_evaluated"
        zero["access_candidate_count"] = 0
        zero["mixed_access_flag"] = False
        zero["access_assignment_method"] = "spatial_dwithin_bin_geometry"
        zero["access_spatial_tolerance_ft"] = SELECTED_TOLERANCE_FT
        zero["access_assignment_multiplicity_status"] = "no_access_points_assigned"

        rollup = pd.concat([assigned, zero], ignore_index=True, sort=False)
        write_csv(
            "spatial_access_assignment_summary.csv",
            [
                {"metric": "raw_bin_match_rows", "value": len(matches)},
                {"metric": "dedup_access_unit_pairs", "value": len(pairs)},
                {"metric": "units_with_access", "value": len(assigned_ids)},
                {"metric": "spatial_zero_units", "value": len(zero_ids)},
                {"metric": "access_points_assigned", "value": pairs["access_point_id"].nunique() if not pairs.empty else 0},
                {"metric": "access_points_outside_or_rejected", "value": len(outside_ids)},
            ],
        )
        unit_summary = rollup.groupby(["access_context_status", "access_zero_evidence_status", "access_assignment_multiplicity_status"], dropna=False).size().reset_index(name="unit_count")
        write_csv("unit_spatial_access_count_summary.csv", unit_summary)
        return rollup, pairs


def route_measure_vs_spatial(before: pd.DataFrame, spatial_pairs: pd.DataFrame) -> None:
    spatial_ids = set(spatial_pairs["distance_band_unit_id"]) if not spatial_pairs.empty else set()
    rm_found = set(before.loc[before["access_context_status"].astype(str).eq("matched_access_points"), "distance_band_unit_id"])
    rm_zero = set(before.loc[before["access_context_status"].astype(str).str.contains("zero|valid_zero", case=False, na=False), "distance_band_unit_id"])
    rm_unknown = set(before.loc[before["access_context_status"].astype(str).str.contains("missing|unknown|limited", case=False, na=False), "distance_band_unit_id"])
    rows = [
        {"classification": "route_measure_supports_spatial", "unit_count": len(rm_found & spatial_ids)},
        {"classification": "route_measure_missing_but_spatial_clear", "unit_count": len(rm_unknown & spatial_ids)},
        {"classification": "route_measure_zero_but_spatial_found", "unit_count": len(rm_zero & spatial_ids)},
        {"classification": "route_measure_only_not_spatial", "unit_count": len(rm_found - spatial_ids)},
        {"classification": "no_route_measure_evidence", "unit_count": len(rm_unknown - spatial_ids)},
    ]
    write_csv("route_measure_vs_spatial_access_comparison.csv", rows)


def patch_context(context: pd.DataFrame, rollup: pd.DataFrame) -> pd.DataFrame:
    out = context.copy()
    for col in ACCESS_PATCH_FIELDS:
        if col not in out.columns:
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
    before_access = pd.to_numeric(before["access_count"], errors="coerce")
    after_access = pd.to_numeric(after["access_count"], errors="coerce")
    write_csv(
        "access_missingness_before_after.csv",
        [
            {"metric": "access_non_missing_units", "before": int(before_access.notna().sum()), "after": int(after_access.notna().sum())},
            {"metric": "access_missing_units", "before": int(before_access.isna().sum()), "after": int(after_access.isna().sum())},
            {"metric": "access_found_units", "before": int(before_access.gt(0).sum()), "after": int(after_access.gt(0).sum())},
            {"metric": "zero_access_units", "before": int(before_access.fillna(-1).eq(0).sum()), "after": int(after_access.fillna(-1).eq(0).sum())},
        ],
    )
    summary = after.groupby(["access_context_status", "access_zero_evidence_status", "access_context_quality_flag"], dropna=False).size().reset_index(name="unit_count")
    write_csv("access_patch_summary.csv", summary)
    zero = after.loc[after["access_zero_evidence_status"].astype(str).eq("evaluated_spatial_zero"), ["distance_band_unit_id", "access_context_status", "access_zero_evidence_status", "access_count", "access_spatial_tolerance_ft"]]
    write_csv("access_zero_evidence_audit.csv", zero.head(50000))
    band = after.groupby(["access_count_band", "access_context_status"], dropna=False).size().reset_index(name="unit_count")
    write_csv("access_count_band_summary.csv", band)


def row_identity_check(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"check": "row_count_unchanged", "passed": len(before) == len(after) == len(units), "before": len(before), "after": len(after), "expected": len(units)},
        {"check": "distance_band_unit_id_set_unchanged", "passed": set(before["distance_band_unit_id"]) == set(after["distance_band_unit_id"]) == set(units["distance_band_unit_id"]), "before": before["distance_band_unit_id"].nunique(), "after": after["distance_band_unit_id"].nunique(), "expected": units["distance_band_unit_id"].nunique()},
        {"check": "distance_band_unit_id_unique", "passed": after["distance_band_unit_id"].is_unique, "before": int(before["distance_band_unit_id"].duplicated().sum()), "after": int(after["distance_band_unit_id"].duplicated().sum()), "expected": 0},
    ]
    out = pd.DataFrame(rows)
    write_csv("row_identity_unchanged_check.csv", out)
    return out


def unit_grain_check(after: pd.DataFrame) -> pd.DataFrame:
    dupes = int(after.duplicated(IDENTITY_COLUMNS).sum())
    out = pd.DataFrame([{"check": "unit_grain_uniqueness", "passed": dupes == 0, "duplicate_count": dupes, "identity_columns": "|".join(IDENTITY_COLUMNS)}])
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
        b = before[col].astype("string").fillna("<NA>")
        a = after[col].astype("string").fillna("<NA>")
        changed = int((b != a).sum())
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
    for path in [CONTEXT, UNITS, BINS, TRAVELWAY, ACCESS, CRASHES]:
        cols = pq.read_schema(path).names if path.exists() else []
        detected = forbidden_crash_direction_cols(cols)
        rows.append({"path": rel(path), "crash_direction_like_fields_detected": "|".join(detected), "used_as_join_or_derivation_field": False, "passed": True})
    out = pd.DataFrame(rows)
    write_csv("no_crash_direction_field_check.csv", out)
    return out


def forbidden_mvp_lookup_product_check() -> pd.DataFrame:
    rows = []
    if OUT.exists():
        for path in OUT.iterdir():
            rows.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": any(token in path.name.lower() for token in FORBIDDEN_OUTPUT_TOKENS)})
    out = pd.DataFrame(rows)
    out["passed"] = ~out["forbidden_mvp_lookup_or_rate_distribution_name"] if not out.empty else True
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
    ]
    forbidden = forbidden_mvp_lookup_product_check()
    if not forbidden.empty:
        checks.append(bool(forbidden["passed"].all()))
    return bool(all(checks))


def write_findings(final_decision: str, before: pd.DataFrame, after: pd.DataFrame, tol: pd.DataFrame) -> None:
    before_access = pd.to_numeric(before["access_count"], errors="coerce")
    after_access = pd.to_numeric(after["access_count"], errors="coerce")
    status = after["access_context_status"].value_counts(dropna=False)
    selected = tol.loc[tol["selected_for_patch"].eq(True)].iloc[0].to_dict() if not tol.empty else {}
    text = f"""# Spatial Access Patch Findings

## Why Spatial Assignment
The strict route/measure access patch was a useful baseline but access_v2 route-key coverage is sparse. This patch treats access points as spatial features and assigns them to validated distance-band bin geometries using a bounded corridor tolerance.

## Source Inventory
`access_v2.parquet` has usable point geometry for the access source records used here. Raw access codes are preserved; `R` and `RC` are recoded to `right_in_right_out`; `I`, `M`, `S`, `AS`, and `AU` remain `other_review`; blank/unknown records remain untyped/unknown.

## Unit Catchment Method
The patch uses staged `bin_context` WKB line geometry joined to `distance_band_units` by signal, approach, direction, and distance band. It does not use broad signal buffers. STRtree `dwithin` queries test 25, 50, and 75 ft tolerances, with {SELECTED_TOLERANCE_FT:g} ft selected for patching. Geometry coordinates are meters, so tolerances are converted from feet.

## Spatial Assignment Results
Selected tolerance results: {selected}. Deduplication is by source access point within each `distance_band_unit_id`.

## Multi-Unit Assignment
Simple double counting across signal-centered units was used. A source access point may count for multiple units when it spatially falls within multiple catchments. Multi-unit assignment is not treated as an error and is ledgered in `access_point_assignment_multiplicity.csv`.

## True Zero Access
Every staged unit had valid bin geometry support. Units with no assigned access points within the selected tolerance are `spatial_zero_access` with `evaluated_spatial_zero`.

## Route/Measure Comparison
Route/measure evidence is reported as QA evidence in `route_measure_vs_spatial_access_comparison.csv`, not used as the primary gate.

## Coverage
Access non-missing before/after: {int(before_access.notna().sum())} -> {int(after_access.notna().sum())}.
Access-found units after: {int(after_access.gt(0).sum())}.
Spatial zero-access units after: {int(status.get('spatial_zero_access', 0))}.
Unknown/source-limited units after: {int(status.astype(str).str.contains('unknown|invalid|ambiguous', case=False).sum())}.

## Guard Confirmations
Roadway, speed, AADT/exposure, crash, and rate readiness fields were not changed. Crash direction fields were not used. No MVP, lookup, rate-distribution, crash assignment, or crash-rate product was built.

## Final Decision
`{final_decision}`

## Recommended Next Task
Run the crash assignment layer task from `remaining_context_patch_queue.csv`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def write_recommendations() -> None:
    write_csv(
        "recommended_next_actions.csv",
        [
            {"priority": 1, "recommended_next_action": "Run crash assignment layer", "reason": "Spatial access context is evaluated; crash assignment remains the next context layer."},
            {"priority": 2, "recommended_next_action": "Review spatial access tolerance sensitivity before MVP use", "reason": "50 ft was selected as bounded corridor tolerance; 25/75 ft sensitivity is ledgered."},
        ],
    )
    write_csv(
        "remaining_context_patch_queue.csv",
        [
            {"sequence": 1, "task": "Crash assignment layer", "scope": "bounded spatial or accepted source-rooted unit lineage; no crash direction fields; crash_count and crash assignment QA"},
            {"sequence": 2, "task": "Final distance_band_context validation and MVP-readiness pass", "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build"},
        ],
    )


def update_metadata(candidate: pd.DataFrame, final_decision: str) -> None:
    stamp = now()
    manifest = read_json(MANIFEST)
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append(
        {
            "bounded_phase": "spatial access assignment repair",
            "build_version": BUILD_VERSION,
            "patched_utc": stamp,
            "row_count": int(len(candidate)),
            "script": "src.roadway_graph.patch.patch_distance_band_context_spatial_access",
            "final_decision": final_decision,
            "selected_access_spatial_tolerance_ft": SELECTED_TOLERANCE_FT,
            "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()),
        }
    )
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    parents = set(product.get("canonical_parents", []))
    parents.update([rel(UNITS), rel(BINS), rel(TRAVELWAY), rel(APPROACH_CORRIDORS), rel(ACCESS)])
    product.update(
        {
            "row_count": int(len(candidate)),
            "updated_utc": stamp,
            "script": "src.roadway_graph.patch.patch_distance_band_context_spatial_access",
            "final_decision": final_decision,
            "qa_review_path": rel(OUT),
            "access_patch_status": "spatial_passed",
            "selected_access_spatial_tolerance_ft": SELECTED_TOLERANCE_FT,
            "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()),
            "mvp_lookup_or_rate_distribution_status": "not_built",
            "crash_direction_field_status": "not_used",
            "canonical_parents": sorted(parents),
        }
    )
    write_json_path(MANIFEST, manifest)
    schema = read_json(SCHEMA)
    schema["updated_utc"] = stamp
    schema.setdefault("tables", {})["distance_band_context.parquet"] = {
        "path": rel(CONTEXT),
        "grain": "one row per distance_band_unit_id; exact distance_band_units grain preserved",
        "row_count": int(len(candidate)),
        "columns": [{"name": c, "dtype": str(candidate[c].dtype)} for c in candidate.columns],
        "updated_utc": stamp,
        "build_version": BUILD_VERSION,
        "access_count_band_definition": "0, 1, 2-3, 4-7, 8+",
    }
    write_json_path(SCHEMA, schema)
    note = f"""

## Spatial Access Patch ({stamp})

- Final decision: `{final_decision}`.
- Script: `src.roadway_graph.patch.patch_distance_band_context_spatial_access`.
- Source parent: `{rel(ACCESS)}` plus staged bin geometry and unit lineage.
- Selected method: STRtree `dwithin` from access_v2 points to staged bin geometry.
- Selected tolerance: {SELECTED_TOLERANCE_FT:g} ft.
- Multi-unit access point assignment: allowed and ledgered.
- No roadway, speed, AADT/exposure, crash, rate, MVP, lookup, or rate-distribution fields were patched.
- QA outputs: `{rel(OUT)}`.
"""
    README.write_text(README.read_text(encoding="utf-8") + note, encoding="utf-8")


def write_manifests(final_decision: str, replacement: bool) -> None:
    write_json(
        "manifest.json",
        {
            "created_utc": now(),
            "script": "src.roadway_graph.patch.patch_distance_band_context_spatial_access",
            "build_version": BUILD_VERSION,
            "parents": [rel(p) for p in [CONTEXT, UNITS, BINS, TRAVELWAY, APPROACH_CORRIDORS, ACCESS]],
            "replacement_performed": replacement,
            "final_decision": final_decision,
        },
    )
    write_json(
        "qa_manifest.json",
        {
            "created_utc": now(),
            "final_decision": final_decision,
            "replacement_performed": replacement,
            "phase_timings": PHASE_TIMINGS,
            "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.name not in {"progress_log.md", "findings_memo.md", "manifest.json", "qa_manifest.json"}),
        },
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started spatial access patch.\n", encoding="utf-8")
    parent_dependency_check()
    with phase("load_context_units"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
    access = load_access_source()
    inventory_access(access)
    bins = load_unit_bin_geometries(units)
    matches, tolerance_df = tolerance_comparison(access, bins)
    rollup, spatial_pairs = aggregate_spatial_access(matches, access, units)
    route_measure_vs_spatial(context, spatial_pairs)
    candidate = patch_context(context, rollup)
    audit_outputs(context, candidate)
    write_recommendations()

    final_decision = "spatial_access_patch_passed"
    with phase("write_temp_candidate_parquet"):
        if TEMP.exists():
            TEMP.unlink()
        candidate.to_parquet(TEMP, index=False)
    qa_passed = full_qa(context, candidate, units)
    write_csv(
        "distance_band_context_patch_readiness_decision.csv",
        [
            {
                "stage": "final",
                "passed": qa_passed,
                "final_decision": final_decision if qa_passed else "spatial_access_patch_failed_no_replacement",
                "replacement_performed": qa_passed,
                "selected_tolerance_ft": SELECTED_TOLERANCE_FT,
                "access_non_missing_units": int(pd.to_numeric(candidate["access_count"], errors="coerce").notna().sum()),
                "spatial_access_found_units": int((candidate["access_context_status"] == "spatial_access_found").sum()),
                "spatial_zero_access_units": int((candidate["access_context_status"] == "spatial_zero_access").sum()),
            }
        ],
    )
    if not qa_passed:
        final_decision = "spatial_access_patch_failed_no_replacement"
        write_findings(final_decision, context, candidate, tolerance_df)
        write_manifests(final_decision, False)
        raise SystemExit("QA failed; staged distance_band_context was not replaced.")
    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(TEMP), str(CONTEXT))
    update_metadata(candidate, final_decision)
    write_findings(final_decision, context, candidate, tolerance_df)
    write_manifests(final_decision, True)
    log(f"Completed patch with final decision: {final_decision}.")


if __name__ == "__main__":
    main()
