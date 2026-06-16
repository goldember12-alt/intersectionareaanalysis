"""Patch staged distance_band_context with spatial fractional crash assignment.

This targeted patch uses source crash point geometry and staged bin geometry to
build 50 ft spatial candidates, applies within signal/approach/direction
distance-band exclusivity, and writes total-preserving equal fractional crash
numerators. Crash direction fields are inventoried only and are not used.
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
OUT = REPO / "work/roadway_graph/review/patch_distance_band_context_crash_assignment"
SIGNALS = STAGING / "signal_index.parquet"
BINS = STAGING / "bin_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
CONTEXT = STAGING / "distance_band_context.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"
MANIFEST = STAGING / "manifest.json"
SCHEMA = STAGING / "schema.json"
README = STAGING / "README.md"
TEMP = STAGING / "distance_band_context.crash_assignment_candidate.tmp.parquet"

BUILD_VERSION = "distance_band_context_crash_assignment_v1_2026-06-15"
TOL_FT = 50.0
FT_PER_M = 3.280839895
CRASH_DIRECTION_TOKENS = ("direction", "dir", "travel_direction", "veh_direction", "crash_direction", "bearing")
FORBIDDEN_OUTPUT_TOKENS = ("lookup_cells", "rate_distribution", "mvp_directional_rate_distribution")
BAND_ORDER = {
    "0_250ft": 0, "250_500ft": 1, "500_1000ft": 2, "1000_1500ft": 3, "1500_2000ft": 4, "2000_2500ft": 5,
    "0-250": 0, "250-500": 1, "500-1,000": 2, "1000-1500": 3, "1,000-1,500": 3,
    "1500-2000": 4, "1,500-2,000": 4, "2000-2500": 5, "2,000-2,500": 5,
}
IDENTITY_COLUMNS = ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]
CRASH_PATCH_FIELDS = [
    "crash_count_weighted", "crash_count_unweighted_candidate", "crash_assignment_pair_count",
    "crash_unique_count", "crash_assignment_method", "crash_weighting_method", "crash_weight_sum_status",
    "crash_context_status", "crash_source_match_method", "crash_route_measure_support_status",
    "crash_ambiguity_flag", "crash_multiplicity_status", "crash_nonadjacent_band_flag_count",
    "crash_assigned_any_flag", "crash_unassigned_source_count_reference", "crash_rate_ready_flag",
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
    log(f"BEGIN {name}{' ' + str(details) if details else ''}")
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = round(time.perf_counter() - start, 3)
        PHASE_TIMINGS.append({"phase": name, "elapsed_seconds": elapsed, **details})
        log(f"END {name}; elapsed_seconds={elapsed:.3f}")


def write_csv(name: str, rows: Any) -> pd.DataFrame:
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT / name, index=False)
    return frame


def write_json(name: str, payload: dict[str, Any]) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_series(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip()


def route_key(value: Any) -> str:
    text = "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value).strip().upper()
    text = text.replace("R-VA", " ").replace("S-VA", " ").replace("VA", " ")
    text = re.sub(r"[^A-Z0-9]", " ", text)
    joined = "".join(part for part in text.split() if part)
    match = re.search(r"(US|SR|IS|I)(0*)(\d+)(NB|SB|EB|WB|N|S|E|W)?(BUS\d+)?", joined)
    if match:
        prefix = "I" if match.group(1) in {"IS", "I"} else match.group(1)
        direction = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}.get(match.group(4) or "", match.group(4) or "")
        return f"{prefix}{int(match.group(3))}{direction}{match.group(5) or ''}"
    return joined


def parent_dependency_check() -> None:
    rows = []
    for path in [SIGNALS, BINS, UNITS, CONTEXT, CRASHES]:
        rows.append({"path": rel(path), "role": "staged_or_source_parent", "exists": path.exists(), "sha256": sha(path) if path.exists() else ""})
    write_csv("parent_dependency_check.csv", rows)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("load_inputs"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
        bin_cols = ["stable_bin_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "source_route_name", "source_measure_start", "source_measure_end", "geometry", "geometry_length_ft"]
        bins = pd.read_parquet(BINS, columns=bin_cols)
        crashes = pd.read_parquet(CRASHES)
        signals = pd.read_parquet(SIGNALS, columns=["stable_signal_id", "geometry"])
        return context, units, bins, crashes, signals


def prepare_geometry(units: pd.DataFrame, bins: pd.DataFrame, crashes: pd.DataFrame, signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("prepare_geometry"):
        c = crashes.loc[crashes["geometry"].notna(), ["DOCUMENT_NBR", "CRASH_YEAR", "CRASH_DT", "CRASH_SEVERITY", "geometry", "RTE_NM", "RNS_MP"]].copy()
        c["crash_id"] = clean_series(c["DOCUMENT_NBR"])
        c["route_key"] = clean_series(c["RTE_NM"]).map(route_key)
        c["rns_mp"] = pd.to_numeric(c["RNS_MP"], errors="coerce")
        c["route_measure_available"] = c["route_key"].ne("") & c["rns_mp"].notna()
        c["geometry_obj"] = from_wkb(c["geometry"].to_numpy())
        c = c.loc[~pd.isna(c["geometry_obj"]) & c["crash_id"].ne("")].reset_index(drop=True)
        b = bins.loc[bins["geometry"].notna()].copy()
        b["upstream_downstream"] = clean_series(b["upstream_downstream"])
        b.loc[~b["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        b = b.merge(units[IDENTITY_COLUMNS], on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left", validate="many_to_one")
        b = b.loc[b["distance_band_unit_id"].notna()].reset_index(drop=True)
        b["geometry_obj"] = from_wkb(b["geometry"].to_numpy())
        b = b.loc[~pd.isna(b["geometry_obj"])].reset_index(drop=True)
        s = signals.loc[signals["geometry"].notna(), ["stable_signal_id", "geometry"]].copy()
        s["signal_geometry_obj"] = from_wkb(s["geometry"].to_numpy())
        s = s.loc[~pd.isna(s["signal_geometry_obj"])].drop_duplicates("stable_signal_id")
        write_csv("crash_source_inventory_summary.csv", [
            {"metric": "source_crash_rows", "value": len(crashes)},
            {"metric": "crash_rows_with_valid_geometry", "value": len(c)},
            {"metric": "route_measure_available", "value": int(c["route_measure_available"].sum())},
            {"metric": "unique_crash_ids", "value": int(c["crash_id"].nunique())},
        ])
        return c, b, s


def reconstruct_candidates(crash_points: pd.DataFrame, bin_geom: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    with phase("reconstruct_spatial_crash_candidates", crash_points=len(crash_points), bin_rows=len(bin_geom)):
        tree = STRtree(bin_geom["geometry_obj"].to_numpy())
        cgeom = crash_points["geometry_obj"].to_numpy()
        bgeom = bin_geom["geometry_obj"].to_numpy()
        log("spatial candidates: STRtree query at 50 ft")
        found = tree.query(cgeom, predicate="dwithin", distance=TOL_FT / FT_PER_M)
        ci, bi = found[0].astype("int64"), found[1].astype("int64")
        log(f"spatial candidates: raw crash-bin pairs={len(ci)}")
        raw = pd.DataFrame({"crash_index": ci, "bin_index": bi})
        for col in ["crash_id", "route_key", "rns_mp", "route_measure_available", "CRASH_YEAR", "CRASH_SEVERITY"]:
            raw[col] = crash_points[col].to_numpy()[ci]
        for col in ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id"]:
            raw[col] = bin_geom[col].to_numpy()[bi]
        log("spatial candidates: exact point-to-bin distances")
        raw["distance_to_unit_geometry_ft"] = [cgeom[c].distance(bgeom[b]) * FT_PER_M for c, b in zip(ci, bi)]
        raw["band_order"] = clean_series(raw["distance_band"]).map(BAND_ORDER).fillna(999).astype(int)
        log("spatial candidates: aggregate to crash-unit pairs")
        pair = raw.groupby(["crash_id", "distance_band_unit_id"], as_index=False).agg(
            route_key=("route_key", "first"),
            rns_mp=("rns_mp", "first"),
            route_measure_available=("route_measure_available", "first"),
            stable_signal_id=("stable_signal_id", "first"),
            signal_approach_id=("signal_approach_id", "first"),
            upstream_downstream=("upstream_downstream", "first"),
            distance_band=("distance_band", "first"),
            band_order=("band_order", "first"),
            distance_to_unit_geometry_ft=("distance_to_unit_geometry_ft", "min"),
            matching_bin_count=("stable_bin_id", "nunique"),
            crash_year=("CRASH_YEAR", "first"),
            crash_severity=("CRASH_SEVERITY", "first"),
        )
        sig_geom = signals.set_index("stable_signal_id")["signal_geometry_obj"]
        crash_geom = crash_points.set_index("crash_id")["geometry_obj"]
        pair["distance_to_signal_ft"] = [crash_geom.loc[c].distance(sig_geom.loc[s]) * FT_PER_M if s in sig_geom.index else np.nan for c, s in zip(pair["crash_id"], pair["stable_signal_id"])]
        pc = pair.groupby("crash_id")["distance_band_unit_id"].nunique()
        write_csv("spatial_crash_candidate_reconstruction_summary.csv", [
            {"metric": "source_crashes_with_geometry", "value": len(crash_points)},
            {"metric": "spatial_tolerance_ft", "value": TOL_FT},
            {"metric": "candidate_assignment_pairs_before_exclusivity", "value": len(pair)},
            {"metric": "unique_assigned_crashes_before_exclusivity", "value": int(pair["crash_id"].nunique())},
            {"metric": "units_receiving_candidates_before_exclusivity", "value": int(pair["distance_band_unit_id"].nunique())},
            {"metric": "max_units_per_crash_before_exclusivity", "value": int(pc.max())},
        ])
        return pair


def apply_exclusivity(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("apply_band_exclusivity"):
        group_cols = ["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"]
        band_grp = pair.groupby(group_cols, as_index=False).agg(band_count=("distance_band", "nunique"), min_band_order=("band_order", "min"), max_band_order=("band_order", "max"))
        band_grp["has_non_adjacent"] = band_grp["band_count"].gt(1) & ((band_grp["max_band_order"] - band_grp["min_band_order"]) >= band_grp["band_count"])
        nonadj = band_grp.loc[band_grp["has_non_adjacent"]].copy()
        work = pair.sort_values(group_cols + ["distance_to_unit_geometry_ft", "matching_bin_count", "band_order", "distance_band_unit_id"], ascending=[True, True, True, True, True, False, True, True]).copy()
        keep_idx = work.drop_duplicates(group_cols, keep="first").index
        kept = work.loc[keep_idx].copy()
        dropped = work.loc[~work.index.isin(keep_idx)].copy()
        dropped["drop_reason"] = "within_crash_signal_approach_direction_band_exclusivity"
        write_csv("band_exclusivity_dropped_pair_ledger.csv", dropped.head(100000))
        write_csv("nonadjacent_band_crash_ledger.csv", nonadj.head(100000))
        pc_before = pair.groupby("crash_id")["distance_band_unit_id"].nunique()
        pc_after = kept.groupby("crash_id")["distance_band_unit_id"].nunique()
        post_groups = kept.groupby(group_cols)["distance_band"].nunique()
        write_csv("band_exclusivity_assignment_summary.csv", [
            {"scenario": "before_exclusivity", "assignment_pairs": len(pair), "unique_crashes": pair["crash_id"].nunique(), "units_receiving_crashes": pair["distance_band_unit_id"].nunique(), "max_units_per_crash": int(pc_before.max()), "same_group_multiband_groups": int(band_grp["band_count"].gt(1).sum()), "nonadjacent_groups": int(nonadj.shape[0])},
            {"scenario": "after_exclusivity", "assignment_pairs": len(kept), "unique_crashes": kept["crash_id"].nunique(), "units_receiving_crashes": kept["distance_band_unit_id"].nunique(), "max_units_per_crash": int(pc_after.max()), "same_group_multiband_groups": int(post_groups.gt(1).sum()), "nonadjacent_groups": 0},
        ])
        return kept, dropped, nonadj


def assign_weights(kept: pd.DataFrame) -> pd.DataFrame:
    with phase("assign_equal_fractional_weights"):
        out = kept.copy()
        n = out.groupby("crash_id")["distance_band_unit_id"].transform("nunique")
        out["crash_assignment_weight"] = 1.0 / n
        sums = out.groupby("crash_id")["crash_assignment_weight"].sum()
        write_csv("per_crash_weight_sum_check.csv", [{"check": "per_crash_weights_sum_to_one", "crashes_checked": len(sums), "min_sum": float(sums.min()), "max_sum": float(sums.max()), "mean_sum": float(sums.mean()), "passed": bool(np.allclose(sums.to_numpy(), 1.0, atol=1e-9))}])
        write_csv("crash_assignment_weight_summary.csv", [
            {"metric": "assignment_pairs_after_exclusivity", "value": len(out)},
            {"metric": "unique_assigned_crashes", "value": out["crash_id"].nunique()},
            {"metric": "total_weighted_crash_count", "value": float(out["crash_assignment_weight"].sum())},
            {"metric": "min_assignment_weight", "value": float(out["crash_assignment_weight"].min())},
            {"metric": "max_assignment_weight", "value": float(out["crash_assignment_weight"].max())},
            {"metric": "max_units_per_crash", "value": int(n.max())},
        ])
        high_ids = set(out.groupby("crash_id")["distance_band_unit_id"].nunique().loc[lambda s: s.ge(20)].index)
        write_csv("high_multiplicity_crash_ledger.csv", out.loc[out["crash_id"].isin(high_ids)].head(100000))
        return out


def build_route_measure_spans(bins: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    work = bins.copy()
    work["upstream_downstream"] = clean_series(work["upstream_downstream"])
    work.loc[~work["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
    work = work.merge(units[IDENTITY_COLUMNS], on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left", validate="many_to_one")
    work["route_key"] = clean_series(work["source_route_name"]).map(route_key)
    a = pd.to_numeric(work["source_measure_start"], errors="coerce")
    b = pd.to_numeric(work["source_measure_end"], errors="coerce")
    work["measure_min"] = np.minimum(a, b)
    work["measure_max"] = np.maximum(a, b)
    valid = work["distance_band_unit_id"].notna() & work["route_key"].ne("") & work["measure_min"].notna() & work["measure_max"].notna()
    return work.loc[valid].groupby(["distance_band_unit_id", "route_key"], as_index=False).agg(measure_min=("measure_min", "min"), measure_max=("measure_max", "max"))


def route_measure_overlay(crash_points: pd.DataFrame, weighted: pd.DataFrame, bins: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("route_measure_qa_overlay"):
        spans = build_route_measure_spans(bins, units)
        c = crash_points.loc[crash_points["route_measure_available"], ["crash_id", "route_key", "rns_mp"]].copy()
        c["measure_bucket_0p1mi"] = np.floor(c["rns_mp"] * 10).astype("int64")
        s = spans.copy()
        s["bucket_start"] = np.floor(s["measure_min"] * 10).astype("int64")
        s["bucket_end"] = np.floor(s["measure_max"] * 10).astype("int64")
        s["bucket_count"] = (s["bucket_end"] - s["bucket_start"] + 1).clip(lower=1, upper=200)
        repeated = np.repeat(s.index.to_numpy(), s["bucket_count"].to_numpy())
        exp = s.loc[repeated, ["distance_band_unit_id", "route_key", "measure_min", "measure_max"]].copy()
        exp["measure_bucket_0p1mi"] = np.concatenate([np.arange(a, a + n, dtype="int64") for a, n in zip(s["bucket_start"].to_numpy(), s["bucket_count"].to_numpy())])
        cand = c.merge(exp, on=["route_key", "measure_bucket_0p1mi"], how="inner")
        cand = cand.loc[cand["rns_mp"].ge(cand["measure_min"]) & cand["rns_mp"].le(cand["measure_max"]), ["crash_id", "distance_band_unit_id"]].drop_duplicates()
        spatial_ids = set(weighted["crash_id"])
        route_ids = set(cand["crash_id"])
        support_ids = spatial_ids & route_ids
        only_route_ids = route_ids - spatial_ids
        spatial_only_ids = spatial_ids - route_ids
        status = np.select(
            [weighted["crash_id"].isin(support_ids), weighted["route_measure_available"] & weighted["crash_id"].isin(spatial_only_ids), ~weighted["route_measure_available"]],
            ["route_measure_supports_spatial", "route_measure_conflicts_or_no_unit_overlap_spatial", "no_route_measure_evidence"],
            default="route_measure_missing_but_spatial_clear",
        )
        weighted = weighted.copy()
        weighted["route_measure_qa_status"] = status
        write_csv("route_measure_qa_overlay_summary.csv", [
            {"class": "route_measure_supports_spatial", "crash_count": len(support_ids), "weighted_crash_count": float(weighted.loc[weighted["crash_id"].isin(support_ids), "crash_assignment_weight"].sum())},
            {"class": "spatial_only_or_no_route_unit_overlap", "crash_count": len(spatial_only_ids), "weighted_crash_count": float(weighted.loc[weighted["crash_id"].isin(spatial_only_ids), "crash_assignment_weight"].sum())},
            {"class": "route_measure_only_not_counted", "crash_count": len(only_route_ids), "weighted_crash_count": 0.0},
            {"class": "no_candidate_assignment", "crash_count": int(len(crash_points) - len(spatial_ids | route_ids)), "weighted_crash_count": 0.0},
        ])
        conflicts = weighted.loc[weighted["route_measure_qa_status"].eq("route_measure_conflicts_or_no_unit_overlap_spatial")].head(100000)
        write_csv("route_measure_conflict_ledger.csv", conflicts)
        return weighted, cand


def aggregate_to_units(weighted: pd.DataFrame, context: pd.DataFrame, crash_points: pd.DataFrame, nonadj: pd.DataFrame) -> pd.DataFrame:
    with phase("aggregate_weighted_crashes_to_units"):
        log("aggregate_weighted_crashes_to_units: precomputing crash multiplicity")
        crash_multiplicity = weighted.groupby("crash_id")["distance_band_unit_id"].nunique().rename("crash_assigned_unit_count")
        work = weighted.merge(crash_multiplicity, on="crash_id", how="left")
        log("aggregate_weighted_crashes_to_units: grouping weighted assignments by unit")
        base = work.groupby("distance_band_unit_id").agg(
            crash_count_weighted=("crash_assignment_weight", "sum"),
            crash_count_unweighted_candidate=("crash_id", "nunique"),
            crash_assignment_pair_count=("crash_id", "size"),
            crash_unique_count=("crash_id", "nunique"),
            route_measure_status_summary=("route_measure_qa_status", lambda s: "|".join(sorted(set(s.astype(str))))),
            max_units_per_crash_touching_unit=("crash_assigned_unit_count", "max"),
        ).reset_index()
        base["crash_assignment_method"] = "spatial_primary_50ft_band_exclusive"
        base["crash_weighting_method"] = "equal_fractional_total_preserving"
        base["crash_weight_sum_status"] = "per_crash_weights_sum_to_one"
        base["crash_context_status"] = "assigned_spatial_fractional"
        base["crash_source_match_method"] = "spatial_50ft_bin_geometry_route_measure_qa_only"
        base["crash_route_measure_support_status"] = base["route_measure_status_summary"]
        base["crash_ambiguity_flag"] = base["max_units_per_crash_touching_unit"].gt(1)
        base["crash_multiplicity_status"] = np.where(base["max_units_per_crash_touching_unit"].gt(1), "fractional_multi_unit_assignment_present", "single_unit_crash_assignment")
        log("aggregate_weighted_crashes_to_units: computing non-adjacent flag counts")
        nonadj_unit_counts = weighted.merge(nonadj[["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"]], on=["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"], how="inner").groupby("distance_band_unit_id")["crash_id"].nunique()
        base["crash_nonadjacent_band_flag_count"] = base["distance_band_unit_id"].map(nonadj_unit_counts).fillna(0).astype(int)
        base["crash_assigned_any_flag"] = True
        base["crash_unassigned_source_count_reference"] = int(len(crash_points) - weighted["crash_id"].nunique())
        base = base.drop(columns=["route_measure_status_summary", "max_units_per_crash_touching_unit"])
        log("aggregate_weighted_crashes_to_units: assembling zero-crash units")
        zero_ids = sorted(set(context["distance_band_unit_id"]) - set(base["distance_band_unit_id"]))
        zero = pd.DataFrame({"distance_band_unit_id": zero_ids})
        for col, val in {
            "crash_count_weighted": 0.0, "crash_count_unweighted_candidate": 0, "crash_assignment_pair_count": 0, "crash_unique_count": 0,
            "crash_assignment_method": "spatial_primary_50ft_band_exclusive", "crash_weighting_method": "equal_fractional_total_preserving",
            "crash_weight_sum_status": "no_assigned_crashes", "crash_context_status": "no_assigned_crashes",
            "crash_source_match_method": "spatial_50ft_bin_geometry_route_measure_qa_only", "crash_route_measure_support_status": "no_spatial_crash_assignment",
            "crash_ambiguity_flag": False, "crash_multiplicity_status": "no_assigned_crashes", "crash_nonadjacent_band_flag_count": 0,
            "crash_assigned_any_flag": False, "crash_unassigned_source_count_reference": int(len(crash_points) - weighted["crash_id"].nunique()),
        }.items():
            zero[col] = val
        rollup = pd.concat([base, zero], ignore_index=True, sort=False)
        log("aggregate_weighted_crashes_to_units: writing unit summary")
        write_csv("unit_crash_count_summary.csv", [
            {"metric": "units_with_weighted_crash_gt0", "value": int(base["distance_band_unit_id"].nunique())},
            {"metric": "units_with_zero_crashes", "value": len(zero)},
            {"metric": "total_weighted_crash_count", "value": float(base["crash_count_weighted"].sum())},
            {"metric": "total_unweighted_candidate_count_sum", "value": int(base["crash_count_unweighted_candidate"].sum())},
        ])
        return rollup


def patch_context(context: pd.DataFrame, rollup: pd.DataFrame) -> pd.DataFrame:
    out = context.copy()
    for col in CRASH_PATCH_FIELDS:
        if col not in out:
            if col in {"crash_ambiguity_flag", "crash_assigned_any_flag", "crash_rate_ready_flag"}:
                out[col] = False
            elif col in {"crash_count_weighted", "crash_count_unweighted_candidate", "crash_assignment_pair_count", "crash_unique_count", "crash_nonadjacent_band_flag_count", "crash_unassigned_source_count_reference"}:
                out[col] = 0.0
            else:
                out[col] = ""
    patch = rollup[["distance_band_unit_id", *[c for c in CRASH_PATCH_FIELDS if c != "crash_rate_ready_flag"]]].set_index("distance_band_unit_id")
    ids = out["distance_band_unit_id"]
    for col in patch.columns:
        out[col] = ids.map(patch[col])
    out["crash_rate_ready_flag"] = False
    return out


def summaries(context: pd.DataFrame, candidate: pd.DataFrame, weighted: pd.DataFrame, crash_points: pd.DataFrame) -> None:
    for grain, key, name in [("signal", "stable_signal_id", "signal_crash_count_summary.csv"), ("approach", "signal_approach_id", "approach_crash_count_summary.csv")]:
        total = context.groupby(key)["distance_band_unit_id"].nunique().reset_index(name="unit_count")
        vals = candidate.groupby(key).agg(weighted_crash_count=("crash_count_weighted", "sum"), units_with_crashes=("crash_assigned_any_flag", "sum")).reset_index()
        out = total.merge(vals, on=key, how="left").fillna({"weighted_crash_count": 0, "units_with_crashes": 0})
        out["grain"] = grain
        write_csv(name, out)
    write_csv("zero_crash_signal_approach_unit_summary.csv", [
        {"grain": "signal", "total": context["stable_signal_id"].nunique(), "with_weighted_crash": int(candidate.groupby("stable_signal_id")["crash_count_weighted"].sum().gt(0).sum()), "zero_weighted_crash": int(context["stable_signal_id"].nunique() - candidate.groupby("stable_signal_id")["crash_count_weighted"].sum().gt(0).sum())},
        {"grain": "approach", "total": context["signal_approach_id"].nunique(), "with_weighted_crash": int(candidate.groupby("signal_approach_id")["crash_count_weighted"].sum().gt(0).sum()), "zero_weighted_crash": int(context["signal_approach_id"].nunique() - candidate.groupby("signal_approach_id")["crash_count_weighted"].sum().gt(0).sum())},
        {"grain": "unit", "total": len(candidate), "with_weighted_crash": int(pd.to_numeric(candidate["crash_count_weighted"], errors="coerce").gt(0).sum()), "zero_weighted_crash": int(pd.to_numeric(candidate["crash_count_weighted"], errors="coerce").eq(0).sum())},
    ])
    write_csv("crash_count_by_distance_band.csv", weighted.groupby("distance_band")["crash_assignment_weight"].sum().reset_index(name="weighted_crash_count"))
    write_csv("crash_count_by_upstream_downstream.csv", weighted.groupby("upstream_downstream")["crash_assignment_weight"].sum().reset_index(name="weighted_crash_count"))
    write_csv("crash_count_by_directionality_status.csv", candidate.groupby("directionality_status")["crash_count_weighted"].sum().reset_index(name="weighted_crash_count"))
    write_csv("unassigned_crash_summary.csv", [{"metric": "source_crashes_with_geometry", "value": len(crash_points)}, {"metric": "assigned_source_crashes", "value": weighted["crash_id"].nunique()}, {"metric": "unassigned_source_crashes", "value": len(crash_points) - weighted["crash_id"].nunique()}])


def qa_checks(before: pd.DataFrame, after: pd.DataFrame, units: pd.DataFrame, weighted: pd.DataFrame) -> bool:
    rows = [
        {"check": "row_count_unchanged", "passed": len(before) == len(after) == len(units), "before": len(before), "after": len(after), "expected": len(units)},
        {"check": "distance_band_unit_id_set_unchanged", "passed": set(before["distance_band_unit_id"]) == set(after["distance_band_unit_id"]) == set(units["distance_band_unit_id"]), "before": before["distance_band_unit_id"].nunique(), "after": after["distance_band_unit_id"].nunique(), "expected": units["distance_band_unit_id"].nunique()},
        {"check": "distance_band_unit_id_unique", "passed": after["distance_band_unit_id"].is_unique, "before": int(before["distance_band_unit_id"].duplicated().sum()), "after": int(after["distance_band_unit_id"].duplicated().sum()), "expected": 0},
    ]
    write_csv("row_identity_unchanged_check.csv", rows)
    write_csv("unit_grain_uniqueness_check.csv", [{"check": "unit_grain_unique", "passed": int(after.duplicated(IDENTITY_COLUMNS).sum()) == 0, "duplicate_count": int(after.duplicated(IDENTITY_COLUMNS).sum())}])
    d = before.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="before_count").merge(after.groupby(["upstream_downstream", "directionality_status"], dropna=False).size().reset_index(name="after_count"), on=["upstream_downstream", "directionality_status"], how="outer").fillna(0)
    d["passed"] = d["before_count"].astype(int).eq(d["after_count"].astype(int))
    write_csv("directionality_reconciliation.csv", d)
    lrows = []
    for col in ["bin_count", "unit_length_ft"]:
        b = pd.to_numeric(before[col], errors="coerce")
        a = pd.to_numeric(after[col], errors="coerce")
        lrows.append({"field": col, "passed": bool(b.fillna(-999).eq(a.fillna(-999)).all()), "changed_rows": int((~b.fillna(-999).eq(a.fillna(-999))).sum()), "before_sum": float(b.sum()), "after_sum": float(a.sum())})
    write_csv("length_bin_count_reconciliation.csv", lrows)
    allowed = set(CRASH_PATCH_FIELDS)
    # Existing deferred crash fields may be legitimately updated only if included above; keep legacy crash_count unchanged.
    nt = []
    for col in before.columns:
        if col not in after.columns or col in allowed:
            continue
        changed = int((before[col].astype("string").fillna("<NA>") != after[col].astype("string").fillna("<NA>")).sum())
        nt.append({"field": col, "passed": changed == 0, "changed_rows": changed})
    write_csv("unchanged_non_target_context_fields_check.csv", nt)
    crash_dir = []
    for path in [CRASHES, BINS, UNITS, CONTEXT]:
        cols = pq.read_schema(path).names
        found = [c for c in cols if any(tok in c.lower() for tok in CRASH_DIRECTION_TOKENS)]
        crash_dir.append({"path": rel(path), "direction_like_fields_detected": "|".join(found), "used_for_assignment": False, "passed": True})
    write_csv("no_crash_direction_field_check.csv", crash_dir)
    forb = []
    for path in OUT.iterdir():
        bad = False if path.name == "forbidden_mvp_lookup_product_check.csv" else any(tok in path.name.lower() for tok in FORBIDDEN_OUTPUT_TOKENS)
        forb.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": bad, "passed": not bad})
    write_csv("forbidden_mvp_lookup_product_check.csv", forb)
    weight_sums = weighted.groupby("crash_id")["crash_assignment_weight"].sum()
    total_weight = float(weighted["crash_assignment_weight"].sum())
    unique_assigned = int(weighted["crash_id"].nunique())
    weighted_le_unweighted = (pd.to_numeric(after["crash_count_weighted"], errors="coerce").fillna(0) <= pd.to_numeric(after["crash_count_unweighted_candidate"], errors="coerce").fillna(0) + 1e-9).all()
    readback_ok = pq.ParquetFile(TEMP).metadata.num_rows == len(after)
    return all(r["passed"] for r in rows) and all(r["passed"] for r in lrows) and all(r["passed"] for r in nt) and d["passed"].all() and np.allclose(weight_sums.to_numpy(), 1.0, atol=1e-9) and abs(total_weight - unique_assigned) < 1e-6 and weighted_le_unweighted and all(r["passed"] for r in forb) and readback_ok


def update_metadata(candidate: pd.DataFrame, decision: str) -> None:
    stamp = now()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["updated_utc"] = stamp
    manifest.setdefault("patch_history", []).append({"bounded_phase": "crash assignment", "build_version": BUILD_VERSION, "patched_utc": stamp, "row_count": int(len(candidate)), "script": "src.roadway_graph.patch.patch_distance_band_context_crash_assignment", "final_decision": decision})
    product = manifest.setdefault("products", {}).setdefault("distance_band_context", {})
    product.update({"row_count": int(len(candidate)), "updated_utc": stamp, "script": "src.roadway_graph.patch.patch_distance_band_context_crash_assignment", "final_decision": decision, "qa_review_path": rel(OUT), "crash_patch_status": "spatial_fractional_assignment_passed"})
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema["updated_utc"] = stamp
    schema.setdefault("tables", {})["distance_band_context.parquet"] = {"path": rel(CONTEXT), "grain": "one row per distance_band_unit_id", "row_count": int(len(candidate)), "columns": [{"name": c, "dtype": str(candidate[c].dtype)} for c in candidate.columns], "updated_utc": stamp, "build_version": BUILD_VERSION}
    SCHEMA.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    README.write_text(README.read_text(encoding="utf-8") + f"\n\n## Crash Assignment Patch ({stamp})\n\n- Final decision: `{decision}`.\n- Method: spatial-primary 50 ft candidates, within signal/approach/direction band exclusivity, equal fractional total-preserving weights.\n- QA outputs: `{rel(OUT)}`.\n", encoding="utf-8")


def findings(decision: str) -> None:
    spatial = pd.read_csv(OUT / "spatial_crash_candidate_reconstruction_summary.csv")
    band = pd.read_csv(OUT / "band_exclusivity_assignment_summary.csv")
    weights = pd.read_csv(OUT / "crash_assignment_weight_summary.csv")
    zero = pd.read_csv(OUT / "zero_crash_signal_approach_unit_summary.csv")
    route = pd.read_csv(OUT / "route_measure_qa_overlay_summary.csv")
    text = f"""# Crash Assignment Patch Findings

Implemented spatial-primary crash assignment using source crash point geometry and staged bin geometry with a 50 ft tolerance. Full double-counting was not used because crashes are event outcomes; assigned crashes receive total-preserving equal fractional weights across accepted post-exclusivity unit candidates.

## Candidate And Exclusivity Counts
{spatial.to_string(index=False)}

{band.to_string(index=False)}

## Weighting QA
{weights.to_string(index=False)}

Per-crash weight sums are documented in `per_crash_weight_sum_check.csv`. Total weighted crash count equals the unique assigned crash count within tolerance.

## Zero Crash Summary
{zero.to_string(index=False)}

## Route/Measure QA
{route.to_string(index=False)}

Route/measure evidence was used only as QA/support evidence and not as a count source.

Roadway, speed, AADT/exposure, access, and unit-grain fields were preserved unchanged. Crash direction fields were inventoried only and were not used. No MVP, lookup, rate-distribution, or crash-rate product was built.

Distance-band context is ready for the final validation and MVP-readiness audit.

## Final Decision
`{decision}`

## Recommended Next Task
Run the final `distance_band_context` validation and MVP-readiness pass.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started crash assignment patch.\n", encoding="utf-8")
    parent_dependency_check()
    context, units, bins, crashes, signals = load_inputs()
    crash_points, bin_geom, signal_geom = prepare_geometry(units, bins, crashes, signals)
    pair = reconstruct_candidates(crash_points, bin_geom, signal_geom)
    kept, dropped, nonadj = apply_exclusivity(pair)
    weighted = assign_weights(kept)
    weighted, route_pairs = route_measure_overlay(crash_points, weighted, bins, units)
    rollup = aggregate_to_units(weighted, context, crash_points, nonadj)
    candidate = patch_context(context, rollup)
    summaries(context, candidate, weighted, crash_points)
    write_csv("recommended_next_actions.csv", [{"priority": 1, "recommended_next_action": "Run final distance_band_context validation and MVP-readiness pass", "reason": "Crash assignment patch completed with weighted total-preserving numerators."}])
    write_csv("remaining_context_patch_queue.csv", [{"sequence": 1, "task": "Final distance_band_context validation and MVP-readiness pass", "scope": "validate all context families; finalize rate readiness statuses; verify crash weighting; verify access/spatial exclusivity; only then proceed to MVP analytical product / lookup-cell build"}])
    decision = "crash_assignment_patch_passed_ready_for_final_context_validation"
    with phase("write_temp_candidate_parquet"):
        if TEMP.exists():
            TEMP.unlink()
        candidate.to_parquet(TEMP, index=False)
    qa_passed = qa_checks(context, candidate, units, weighted)
    if not qa_passed:
        decision = "crash_assignment_patch_failed_no_replacement"
        write_csv("distance_band_context_patch_readiness_decision.csv", [{"passed": False, "replacement_performed": False, "final_decision": decision}])
        findings(decision)
        write_json("manifest.json", {"created_utc": now(), "final_decision": decision, "replacement_performed": False})
        write_json("qa_manifest.json", {"created_utc": now(), "final_decision": decision, "replacement_performed": False, "phase_timings": PHASE_TIMINGS})
        raise SystemExit("QA failed; staged distance_band_context was not replaced.")
    with phase("replace_staged_distance_band_context_after_qa"):
        shutil.move(str(TEMP), str(CONTEXT))
    update_metadata(candidate, decision)
    write_csv("distance_band_context_patch_readiness_decision.csv", [{"passed": True, "replacement_performed": True, "final_decision": decision, "weighted_crash_count_total": float(weighted["crash_assignment_weight"].sum()), "unique_assigned_crashes": int(weighted["crash_id"].nunique())}])
    findings(decision)
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.patch.patch_distance_band_context_crash_assignment", "build_version": BUILD_VERSION, "final_decision": decision, "replacement_performed": True})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": decision, "replacement_performed": True, "phase_timings": PHASE_TIMINGS, "outputs": sorted(p.name for p in OUT.glob("*"))})
    log(f"Completed crash assignment patch with final decision: {decision}.")


if __name__ == "__main__":
    main()
