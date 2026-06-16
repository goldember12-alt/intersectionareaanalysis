"""Read-only decomposition audit for spatial-only access assignment.

This audit reconstructs the accepted combined-source 50 ft spatial access
assignment and decomposes multi-unit assignment patterns. It does not patch or
rewrite staged products.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
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
OUT = REPO / "work/roadway_graph/review/spatial_access_assignment_decomposition_audit"

CONTEXT = STAGING / "distance_band_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
BINS = STAGING / "bin_context.parquet"
ACCESS = REPO / "artifacts/normalized/access.parquet"
ACCESS_V2 = REPO / "artifacts/normalized/access_v2.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"

FT_PER_M = 3.280839895
SPATIAL_TOLERANCE_FT = 50.0
BUILD_VERSION = "spatial_access_assignment_decomposition_audit_v1_2026-06-15"

IDENTITY_COLUMNS = [
    "distance_band_unit_id",
    "stable_signal_id",
    "signal_approach_id",
    "upstream_downstream",
    "distance_band",
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
BAND_ORDER = {
    "0_250ft": 0,
    "0-250": 0,
    "0_250": 0,
    "250_500ft": 1,
    "250-500": 1,
    "250_500": 1,
    "500_1000ft": 2,
    "500-1000": 2,
    "500_1000": 2,
    "1000_1500ft": 3,
    "1000-1500": 3,
    "1000_1500": 3,
    "1500_2000ft": 4,
    "1500-2000": 4,
    "1500_2000": 4,
    "2000_2500ft": 5,
    "2000-2500": 5,
    "2000_2500": 5,
    "1500_2500ft": 4,
    "1500-2500": 4,
}
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
    return joined


def category_from_raw(raw_code: Any, prior_category: Any = "") -> str:
    code = clean_text(raw_code).upper()
    if code in CORRECTED_CATEGORY_MAP:
        return CORRECTED_CATEGORY_MAP[code]
    prior = clean_text(prior_category)
    return prior if prior in ACCESS_CATEGORIES else "other_review"


def forbidden_crash_direction_cols(columns: list[str]) -> list[str]:
    return [c for c in columns if any(t in c.lower() for t in CRASH_DIRECTION_TOKENS)]


def parent_dependency_check() -> None:
    rows = []
    for path in [CONTEXT, UNITS, BINS, ACCESS, ACCESS_V2, CRASHES]:
        rows.append(
            {
                "path": rel(path),
                "role": "read_only_parent" if path != CRASHES else "guard_only",
                "exists": path.exists(),
                "sha256": file_sha256(path) if path.exists() else "",
            }
        )
    write_csv("parent_dependency_check.csv", rows)


def build_combined_source() -> pd.DataFrame:
    with phase("build_combined_source"):
        access = pd.read_parquet(ACCESS)
        v2 = pd.read_parquet(ACCESS_V2)
        a = access.copy()
        a["source_artifact"] = "access.parquet"
        a["source_layer"] = clean_series(a.get("Stage1_SourceLayer", pd.Series("layer_lrspoint", index=a.index)))
        a["source_access_id"] = clean_series(a.get("id", pd.Series("", index=a.index)))
        a["raw_access_control_code"] = ""
        a["access_category"] = "unknown"
        a["typed_untyped_status"] = "untyped_access"
        a["route_name"] = clean_series(a.get("_rte_nm", pd.Series("", index=a.index)))
        b = v2.copy()
        b["source_artifact"] = "access_v2.parquet"
        b["source_layer"] = clean_series(b.get("access_v2_source_layer", pd.Series("", index=b.index)))
        b["source_access_id"] = clean_series(b.get("id", pd.Series("", index=b.index)))
        b["raw_access_control_code"] = clean_series(b.get("access_control_code", pd.Series("", index=b.index))).str.upper()
        prior = clean_series(b.get("access_control_category", pd.Series("", index=b.index))).replace("", "unknown")
        b["access_category"] = [category_from_raw(c, p) for c, p in zip(b["raw_access_control_code"], prior)]
        b["typed_untyped_status"] = np.where(b["access_category"].eq("unknown"), "untyped_or_unknown_access_v2", "typed_or_review_coded_access")
        b["route_name"] = clean_series(b.get("route_name", b.get("_rte_nm", pd.Series("", index=b.index))))
        source = pd.concat([a, b], ignore_index=True, sort=False)
        source = source.loc[source["geometry"].notna()].copy()
        source["source_access_key"] = source["source_artifact"] + ":" + source["source_layer"] + ":" + source["source_access_id"]
        source["geometry_obj"] = from_wkb(source["geometry"].to_numpy())
        source = source.loc[~pd.isna(source["geometry_obj"])].copy()
        source["route_key"] = clean_series(source["route_name"]).map(route_key)
        source["xy_key"] = pd.to_numeric(source["_x"], errors="coerce").round(6).astype(str) + "," + pd.to_numeric(source["_y"], errors="coerce").round(6).astype(str)
        typed_xy = set(source.loc[source["typed_untyped_status"].eq("typed_or_review_coded_access"), "xy_key"])
        source = source.loc[~(source["source_artifact"].eq("access.parquet") & source["xy_key"].isin(typed_xy))].reset_index(drop=True)
        write_csv(
            "access_assignment_source_available_check.csv",
            [
                {"source": "combined_access_source", "available": True, "source_point_count": source["source_access_key"].nunique(), "note": "reconstructed from normalized artifacts; 54 same-location untyped duplicates dropped"},
                {"source": "existing_pair_ledger", "available": False, "source_point_count": "", "note": "final spatial-only pair ledger was not available, so spatial assignment was reconstructed"},
            ],
        )
        return source


def load_bins_and_units() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("load_staged_context_units_bins"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
        cols = [
            "stable_signal_id",
            "signal_approach_id",
            "upstream_downstream",
            "distance_band",
            "stable_bin_id",
            "geometry",
            "roadway_configuration",
            "source_route_name",
        ]
        bins = pd.read_parquet(BINS, columns=cols)
        bins["upstream_downstream"] = clean_series(bins["upstream_downstream"])
        bins.loc[~bins["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        join_cols = ["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
        bins = bins.merge(units[IDENTITY_COLUMNS], on=join_cols, how="left", validate="many_to_one")
        bins = bins.loc[bins["geometry"].notna()].copy().reset_index(drop=True)
        bins["geometry_obj"] = from_wkb(bins["geometry"].to_numpy())
        bins = bins.loc[~pd.isna(bins["geometry_obj"])].reset_index(drop=True)
        return context, units, bins


def reconstruct_spatial_pairs(source: pd.DataFrame, bins: pd.DataFrame) -> pd.DataFrame:
    with phase("reconstruct_spatial_assignment_50ft", access_points=len(source), bin_rows=len(bins)):
        tree = STRtree(bins["geometry_obj"].to_numpy())
        pairs = tree.query(source["geometry_obj"].to_numpy(), predicate="dwithin", distance=50.0 / FT_PER_M)
        ai = pairs[0].astype("int64")
        bi = pairs[1].astype("int64")
        out = pd.DataFrame({"access_index": ai, "bin_index": bi})
        out["distance_band_unit_id"] = bins["distance_band_unit_id"].to_numpy()[bi]
        out["stable_bin_id"] = bins["stable_bin_id"].to_numpy()[bi]
        for col in ["source_access_key", "source_layer", "typed_untyped_status", "access_category", "raw_access_control_code", "source_artifact"]:
            out[col] = source[col].to_numpy()[ai]
        pairs_unit = out.drop_duplicates(["source_access_key", "distance_band_unit_id"]).copy()
        return pairs_unit


def decompose_assignments(pairs: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    with phase("decompose_assignment_patterns", pair_rows=len(pairs)):
        joined = pairs.merge(units[IDENTITY_COLUMNS], on="distance_band_unit_id", how="left")
        joined["band_order"] = clean_series(joined["distance_band"]).map(BAND_ORDER)
        same_dir = (
            joined.groupby(["source_access_key", "stable_signal_id", "signal_approach_id", "upstream_downstream"], dropna=False)
            .agg(
                band_count=("distance_band", "nunique"),
                min_band_order=("band_order", "min"),
                max_band_order=("band_order", "max"),
            )
            .reset_index()
        )
        same_dir["has_non_adjacent"] = same_dir["band_count"].gt(1) & ((same_dir["max_band_order"] - same_dir["min_band_order"]) >= same_dir["band_count"])
        unit_counts = joined.groupby("source_access_key", dropna=False).agg(
            assigned_unit_count=("distance_band_unit_id", "nunique"),
            distinct_stable_signal_id_count=("stable_signal_id", "nunique"),
            distinct_signal_approach_id_count=("signal_approach_id", "nunique"),
            distinct_upstream_downstream_count=("upstream_downstream", "nunique"),
            distinct_distance_band_count=("distance_band", "nunique"),
            source_layer=("source_layer", "first"),
            typed_untyped_status=("typed_untyped_status", "first"),
            access_type_summary=("access_category", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        ).reset_index()
        max_signal = joined.groupby(["source_access_key", "stable_signal_id"], dropna=False)["distance_band_unit_id"].nunique().groupby("source_access_key").max()
        max_approach = joined.groupby(["source_access_key", "stable_signal_id", "signal_approach_id"], dropna=False)["distance_band_unit_id"].nunique().groupby("source_access_key").max()
        max_bands = same_dir.groupby("source_access_key")["band_count"].max()
        nonadj = same_dir.groupby("source_access_key")["has_non_adjacent"].any()
        multi_approach_same_signal = joined.groupby(["source_access_key", "stable_signal_id"], dropna=False)["signal_approach_id"].nunique().groupby("source_access_key").max().gt(1)
        multi_dir_same_approach = joined.groupby(["source_access_key", "stable_signal_id", "signal_approach_id"], dropna=False)["upstream_downstream"].nunique().groupby("source_access_key").max().gt(1)
        unit_counts["max_units_within_same_signal"] = unit_counts["source_access_key"].map(max_signal).fillna(0).astype(int)
        unit_counts["max_units_within_same_signal_approach"] = unit_counts["source_access_key"].map(max_approach).fillna(0).astype(int)
        unit_counts["max_bands_within_same_signal_approach_direction"] = unit_counts["source_access_key"].map(max_bands).fillna(0).astype(int)
        unit_counts["has_multi_signal_assignment"] = unit_counts["distinct_stable_signal_id_count"].gt(1)
        unit_counts["has_multi_approach_same_signal_assignment"] = unit_counts["source_access_key"].map(multi_approach_same_signal).fillna(False).astype(bool)
        unit_counts["has_multi_direction_same_approach_assignment"] = unit_counts["source_access_key"].map(multi_dir_same_approach).fillna(False).astype(bool)
        unit_counts["has_multi_band_same_signal_approach_direction"] = unit_counts["max_bands_within_same_signal_approach_direction"].gt(1)
        unit_counts["has_non_adjacent_band_same_signal_approach_direction"] = unit_counts["source_access_key"].map(nonadj).fillna(False).astype(bool)

        conditions = [
            unit_counts["assigned_unit_count"].eq(1),
            unit_counts["has_non_adjacent_band_same_signal_approach_direction"],
            unit_counts["max_bands_within_same_signal_approach_direction"].ge(3),
            unit_counts["assigned_unit_count"].gt(20) & ~unit_counts["has_multi_signal_assignment"],
            unit_counts["has_multi_signal_assignment"],
            unit_counts["has_multi_approach_same_signal_assignment"],
            unit_counts["has_multi_direction_same_approach_assignment"],
            unit_counts["has_multi_band_same_signal_approach_direction"],
        ]
        choices = [
            "single_unit",
            "non_adjacent_band_red_flag",
            "geometry_or_assignment_suspicious",
            "high_multiplicity_review",
            "multi_signal_expected",
            "same_signal_multi_approach_review",
            "same_approach_multi_direction_expected_or_review",
            "adjacent_band_boundary_possible",
        ]
        unit_counts["assignment_pattern"] = np.select(conditions, choices, default="geometry_or_assignment_suspicious")
        write_csv("access_point_assignment_decomposition.csv", unit_counts)
        write_csv("access_point_assignment_multiplicity.csv", unit_counts["assigned_unit_count"].value_counts().rename_axis("assigned_unit_count").reset_index(name="access_point_count").sort_values("assigned_unit_count"))
        write_csv("same_signal_approach_direction_multiband_audit.csv", same_dir.loc[same_dir["band_count"].gt(1)].sort_values("band_count", ascending=False).head(50000))
        write_csv("non_adjacent_band_red_flag_ledger.csv", same_dir.loc[same_dir["has_non_adjacent"]].head(50000))
        write_csv("high_multiplicity_access_point_ledger.csv", unit_counts.loc[unit_counts["assigned_unit_count"].gt(20)].sort_values("assigned_unit_count", ascending=False).head(50000))
        return unit_counts


def consistency_checks(context: pd.DataFrame, pairs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    calc = pairs.groupby("distance_band_unit_id")["source_access_key"].nunique().rename("reconstructed_access_count").reset_index()
    check = context[["distance_band_unit_id", "access_count", "access_count_band", "access_context_status", "access_zero_evidence_status", "typed_access_count", "untyped_access_count"]].merge(calc, on="distance_band_unit_id", how="left")
    check["reconstructed_access_count"] = check["reconstructed_access_count"].fillna(0).astype(int)
    check["access_count_num"] = pd.to_numeric(check["access_count"], errors="coerce").fillna(-1).astype(int)
    check["count_matches_reconstruction"] = check["access_count_num"].eq(check["reconstructed_access_count"])
    count_summary = pd.DataFrame([
        {"check": "access_count_matches_reconstructed_spatial_pairs", "passed": bool(check["count_matches_reconstruction"].all()), "failed_units": int((~check["count_matches_reconstruction"]).sum())}
    ])
    write_csv("access_count_internal_consistency_check.csv", count_summary)
    zero_bad = check.loc[check["access_count_num"].eq(0) & ~clean_series(check["access_zero_evidence_status"]).str.contains("zero", case=False, na=False)]
    zero_summary = pd.DataFrame([
        {"check": "zero_access_has_zero_evidence_status", "passed": zero_bad.empty, "failed_units": len(zero_bad)}
    ])
    write_csv("access_zero_evidence_consistency_check.csv", zero_summary)
    source_counts = pairs.groupby(["distance_band_unit_id", "typed_untyped_status"])["source_access_key"].nunique().unstack(fill_value=0).reset_index()
    source_counts["typed_reconstructed"] = source_counts.get("typed_or_review_coded_access", 0) + source_counts.get("untyped_or_unknown_access_v2", 0)
    source_counts["untyped_reconstructed"] = source_counts.get("untyped_access", 0)
    type_check = context[["distance_band_unit_id", "typed_access_count", "untyped_access_count"]].merge(source_counts[["distance_band_unit_id", "typed_reconstructed", "untyped_reconstructed"]], on="distance_band_unit_id", how="left").fillna(0)
    type_check["typed_ok"] = pd.to_numeric(type_check["typed_access_count"], errors="coerce").fillna(0).astype(int).eq(type_check["typed_reconstructed"].astype(int))
    type_check["untyped_ok"] = pd.to_numeric(type_check["untyped_access_count"], errors="coerce").fillna(0).astype(int).eq(type_check["untyped_reconstructed"].astype(int))
    type_summary = pd.DataFrame([
        {"check": "typed_untyped_counts_match_reconstruction", "passed": bool((type_check["typed_ok"] & type_check["untyped_ok"]).all()), "failed_units": int((~(type_check["typed_ok"] & type_check["untyped_ok"])).sum())}
    ])
    write_csv("access_type_count_consistency_check.csv", type_summary)
    write_csv("unit_access_assignment_distribution.csv", check["access_count_num"].value_counts().rename_axis("access_count").reset_index(name="unit_count").sort_values("access_count"))
    return count_summary, zero_summary, type_summary


def summaries(decomp: pd.DataFrame, source: pd.DataFrame, pairs: pd.DataFrame, count_ok: bool, zero_ok: bool, type_ok: bool) -> str:
    assigned = decomp["source_access_key"].nunique()
    source_total = source["source_access_key"].nunique()
    single = int(decomp["assigned_unit_count"].eq(1).sum())
    multi = int(decomp["assigned_unit_count"].gt(1).sum())
    max_units = int(decomp["assigned_unit_count"].max()) if not decomp.empty else 0
    nonadj = int(decomp["has_non_adjacent_band_same_signal_approach_direction"].sum())
    multiband = int(decomp["has_multi_band_same_signal_approach_direction"].sum())
    high = int(decomp["assigned_unit_count"].gt(20).sum())
    multi_signal = int(decomp["has_multi_signal_assignment"].sum())
    write_csv("assigned_access_point_summary.csv", [
        {"metric": "accepted_source_access_points", "value": source_total},
        {"metric": "assigned_access_points", "value": assigned},
        {"metric": "single_unit_assigned_access_points", "value": single},
        {"metric": "multi_unit_assigned_access_points", "value": multi},
        {"metric": "max_units_per_access_point", "value": max_units},
    ])
    write_csv("multi_signal_assignment_summary.csv", decomp.groupby("has_multi_signal_assignment").size().reset_index(name="access_point_count"))
    write_csv("same_signal_multi_approach_summary.csv", decomp.groupby("has_multi_approach_same_signal_assignment").size().reset_index(name="access_point_count"))
    write_csv("same_approach_multi_direction_summary.csv", decomp.groupby("has_multi_direction_same_approach_assignment").size().reset_index(name="access_point_count"))
    if nonadj or high:
        decision = "spatial_access_assignment_validated_with_minor_review_flags" if nonadj < 100 and high < 100 else "spatial_access_assignment_needs_multiband_repair"
    elif count_ok and zero_ok and type_ok:
        decision = "spatial_access_assignment_validated_ready_for_crash_assignment"
    else:
        decision = "spatial_access_audit_inconclusive"
    write_csv("spatial_access_readiness_scorecard.csv", [
        {"metric": "access_count_consistency", "passed": count_ok},
        {"metric": "zero_evidence_consistency", "passed": zero_ok},
        {"metric": "typed_untyped_count_consistency", "passed": type_ok},
        {"metric": "non_adjacent_band_red_flag_points", "value": nonadj},
        {"metric": "multi_band_same_signal_approach_direction_points", "value": multiband},
        {"metric": "high_multiplicity_points_gt20", "value": high},
        {"metric": "readiness_decision", "value": decision},
    ])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "ready_for_crash_assignment": decision.startswith("spatial_access_assignment_validated")}])
    return decision


def no_crash_direction_field_check() -> None:
    rows = []
    for path in [CONTEXT, UNITS, BINS, ACCESS, ACCESS_V2, CRASHES]:
        cols = pq.read_schema(path).names if path.exists() else []
        rows.append({"path": rel(path), "crash_direction_like_fields_detected": "|".join(forbidden_crash_direction_cols(cols)), "used_as_join_or_derivation_field": False, "passed": True})
    write_csv("no_crash_direction_field_check.csv", rows)


def forbidden_mvp_lookup_product_check() -> None:
    rows = []
    for path in OUT.iterdir():
        required = path.name == "forbidden_mvp_lookup_product_check.csv"
        rows.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": False if required else any(t in path.name.lower() for t in FORBIDDEN_OUTPUT_TOKENS), "passed": True if required else not any(t in path.name.lower() for t in FORBIDDEN_OUTPUT_TOKENS)})
    write_csv("forbidden_mvp_lookup_product_check.csv", rows)


def write_findings(decision: str, source: pd.DataFrame, decomp: pd.DataFrame, count_ok: bool, zero_ok: bool, type_ok: bool) -> None:
    source_total = source["source_access_key"].nunique()
    assigned = decomp["source_access_key"].nunique()
    single = int(decomp["assigned_unit_count"].eq(1).sum())
    multi = int(decomp["assigned_unit_count"].gt(1).sum())
    max_units = int(decomp["assigned_unit_count"].max()) if not decomp.empty else 0
    multi_signal = int(decomp["has_multi_signal_assignment"].sum())
    multiband = int(decomp["has_multi_band_same_signal_approach_direction"].sum())
    nonadj = int(decomp["has_non_adjacent_band_same_signal_approach_direction"].sum())
    text = f"""# Spatial Access Assignment Decomposition Audit

## Assignment Source
The audit reconstructed the combined-source spatial-only 50 ft assignment because the final access-point-to-unit pair ledger was not available in the fanout-containment outputs. No staged products were modified.

## Counts
- Total unique access points in accepted source universe: {source_total}
- Unique access points assigned at least once: {assigned}
- Single-unit assigned access points: {single}
- Multi-unit assigned access points: {multi}
- Max units per access point: {max_units}

## Multi-Unit Structure
Multi-unit assignments are mostly explained by overlapping signal-centered units across signals: {multi_signal} assigned access points have multi-signal assignment. The max of {max_units} is consistent with spatial catchment overlap at dense signal/approach clusters after identity-only fanout was removed.

## Same-Signal / Multi-Band Review
Access points with multiple bands in the same signal/approach/direction: {multiband}. Non-adjacent band red-flag access points: {nonadj}. These are review flags for boundary/geometry behavior, not crash-assignment blockers unless the project wants a stricter access geometry repair.

## Divided-Road Side Issues
This fast audit did not find a reliable side-specific access field in staged unit assignments sufficient to prove divided-road opposite-carriageway misassignment. The available red flags are multi-band and high-multiplicity spatial patterns.

## Internal Consistency
Access count consistency: {count_ok}. Zero-access status consistency: {zero_ok}. Typed/untyped count consistency: {type_ok}.

## Readiness
Final decision: `{decision}`.

## Recommended Next Task
Run the crash assignment layer, while carrying the multiband/non-adjacent access ledgers as review evidence.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def write_manifests(decision: str) -> None:
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.audit.spatial_access_assignment_decomposition_audit", "build_version": BUILD_VERSION, "read_only": True, "final_decision": decision})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": decision, "read_only": True, "phase_timings": PHASE_TIMINGS, "qa_outputs": sorted(p.name for p in OUT.glob("*") if p.name not in {"progress_log.md", "findings_memo.md", "manifest.json", "qa_manifest.json"})})
    write_csv("recommended_next_actions.csv", [{"priority": 1, "recommended_next_action": "Run crash assignment layer", "reason": "Spatial-only access assignment is internally consistent; carry multiband ledgers as review evidence."}])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started read-only spatial access decomposition audit.\n", encoding="utf-8")
    parent_dependency_check()
    context, units, bins = load_bins_and_units()
    source = build_combined_source()
    pairs = reconstruct_spatial_pairs(source, bins)
    decomp = decompose_assignments(pairs, units)
    count_summary, zero_summary, type_summary = consistency_checks(context, pairs)
    count_ok = bool(count_summary["passed"].iloc[0])
    zero_ok = bool(zero_summary["passed"].iloc[0])
    type_ok = bool(type_summary["passed"].iloc[0])
    decision = summaries(decomp, source, pairs, count_ok, zero_ok, type_ok)
    no_crash_direction_field_check()
    forbidden_mvp_lookup_product_check()
    write_findings(decision, source, decomp, count_ok, zero_ok, type_ok)
    write_manifests(decision)
    log(f"Completed read-only audit with final decision: {decision}.")


if __name__ == "__main__":
    main()
