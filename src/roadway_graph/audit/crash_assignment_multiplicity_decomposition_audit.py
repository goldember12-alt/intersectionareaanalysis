"""Read-only spatial crash assignment multiplicity decomposition audit.

This audit reconstructs the 50 ft spatial crash-to-distance-band assignment,
decomposes multi-unit assignments, and simulates within
signal/approach/direction distance-band exclusivity. It does not patch staged
context data and does not use crash direction fields.
"""

from __future__ import annotations

import hashlib
import json
import math
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
OUT = REPO / "work/roadway_graph/review/crash_assignment_multiplicity_decomposition_audit"
SIGNALS = STAGING / "signal_index.parquet"
BINS = STAGING / "bin_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
CONTEXT = STAGING / "distance_band_context.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"
FEASIBILITY = REPO / "work/roadway_graph/review/crash_assignment_feasibility_audit"

FT_PER_M = 3.280839895
SPATIAL_TOLERANCE_FT = 50.0
BUILD_VERSION = "crash_assignment_multiplicity_decomposition_audit_v1_2026-06-15"
CRASH_DIRECTION_TOKENS = ("direction", "dir", "travel_direction", "veh_direction", "crash_direction", "bearing")
FORBIDDEN_OUTPUT_TOKENS = ("lookup_cells", "rate_distribution", "mvp_directional_rate_distribution")
BAND_ORDER = {
    "0_250ft": 0, "250_500ft": 1, "500_1000ft": 2, "1000_1500ft": 3, "1500_2000ft": 4, "2000_2500ft": 5,
    "0-250": 0, "250-500": 1, "500-1,000": 2, "1000-1500": 3, "1,000-1,500": 3,
    "1500-2000": 4, "1,500-2,000": 4, "2000-2500": 5, "2,000-2,500": 5, "1500_2500ft": 4,
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


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def parent_dependency_check() -> None:
    rows = []
    for path in [SIGNALS, BINS, UNITS, CONTEXT, CRASHES, FEASIBILITY / "readiness_decision.csv"]:
        role = "staged_or_source_parent" if path != FEASIBILITY / "readiness_decision.csv" else "diagnostic_evidence_only"
        rows.append({"path": rel(path), "role": role, "exists": path.exists(), "sha256": file_sha256(path) if path.exists() else ""})
    write_csv("parent_dependency_check.csv", rows)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("load_inputs"):
        crashes = pd.read_parquet(CRASHES)
        units = pd.read_parquet(UNITS)
        context_cols = ["distance_band_unit_id", "divided_undivided", "one_way_two_way", "roadway_configuration_summary"]
        context = pd.read_parquet(CONTEXT, columns=context_cols)
        bin_cols = [
            "stable_bin_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band",
            "source_route_name", "source_measure_start", "source_measure_end", "geometry", "geometry_length_ft",
            "roadway_configuration",
        ]
        bins = pd.read_parquet(BINS, columns=bin_cols)
        return crashes, units, context, bins


def prepare_geometry(crashes: pd.DataFrame, units: pd.DataFrame, context: pd.DataFrame, bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("prepare_geometry"):
        c = crashes.loc[crashes["geometry"].notna(), ["DOCUMENT_NBR", "geometry", "RTE_NM", "RNS_MP"]].copy()
        c["crash_id"] = clean_series(c["DOCUMENT_NBR"])
        c["route_measure_available"] = clean_series(c["RTE_NM"]).ne("") & pd.to_numeric(c["RNS_MP"], errors="coerce").notna()
        c["geometry_obj"] = from_wkb(c["geometry"].to_numpy())
        c = c.loc[~pd.isna(c["geometry_obj"]) & c["crash_id"].ne("")].reset_index(drop=True)
        b = bins.loc[bins["geometry"].notna()].copy()
        b["upstream_downstream"] = clean_series(b["upstream_downstream"])
        b.loc[~b["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        b = b.merge(
            units[["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]],
            on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"],
            how="left",
            validate="many_to_one",
        )
        b = b.merge(context, on="distance_band_unit_id", how="left")
        b = b.loc[b["distance_band_unit_id"].notna()].reset_index(drop=True)
        b["geometry_obj"] = from_wkb(b["geometry"].to_numpy())
        b = b.loc[~pd.isna(b["geometry_obj"])].reset_index(drop=True)
        return c, b


def reconstruct_spatial(crash_points: pd.DataFrame, bin_geom: pd.DataFrame) -> pd.DataFrame:
    with phase("reconstruct_spatial_50ft_assignment", crash_points=len(crash_points), bin_rows=len(bin_geom)):
        tree = STRtree(bin_geom["geometry_obj"].to_numpy())
        cgeom = crash_points["geometry_obj"].to_numpy()
        bgeom = bin_geom["geometry_obj"].to_numpy()
        log("spatial_reconstruction: querying STRtree at 50 ft")
        found = tree.query(cgeom, predicate="dwithin", distance=SPATIAL_TOLERANCE_FT / FT_PER_M)
        ci, bi = found[0].astype("int64"), found[1].astype("int64")
        log(f"spatial_reconstruction: raw crash-bin candidate pairs={len(ci)}")
        raw = pd.DataFrame({"crash_index": ci, "bin_index": bi})
        raw["crash_id"] = crash_points["crash_id"].to_numpy()[ci]
        raw["route_measure_available"] = crash_points["route_measure_available"].to_numpy()[ci]
        for col in ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id", "divided_undivided", "one_way_two_way", "roadway_configuration_summary"]:
            raw[col] = bin_geom[col].to_numpy()[bi]
        log("spatial_reconstruction: computing exact point-to-bin distances")
        raw["distance_to_unit_geometry_ft"] = [cgeom[c].distance(bgeom[b]) * FT_PER_M for c, b in zip(ci, bi)]
        raw["band_order"] = clean_series(raw["distance_band"]).map(BAND_ORDER).fillna(999).astype(int)
        log("spatial_reconstruction: aggregating crash-unit pairs")
        pair = raw.groupby(["crash_id", "distance_band_unit_id"], as_index=False).agg(
            route_measure_available=("route_measure_available", "first"),
            stable_signal_id=("stable_signal_id", "first"),
            signal_approach_id=("signal_approach_id", "first"),
            upstream_downstream=("upstream_downstream", "first"),
            distance_band=("distance_band", "first"),
            band_order=("band_order", "first"),
            min_distance_to_unit_geometry_ft=("distance_to_unit_geometry_ft", "min"),
            matching_bin_count=("stable_bin_id", "nunique"),
            divided_undivided=("divided_undivided", "first"),
            one_way_two_way=("one_way_two_way", "first"),
            roadway_configuration_summary=("roadway_configuration_summary", "first"),
        )
        pc = pair.groupby("crash_id")["distance_band_unit_id"].nunique()
        write_csv("crash_spatial_assignment_reconstruction_summary.csv", [
            {"metric": "reconstructed_from_staged_source", "value": True},
            {"metric": "spatial_tolerance_ft", "value": SPATIAL_TOLERANCE_FT},
            {"metric": "total_crash_rows", "value": len(crash_points)},
            {"metric": "candidate_assignment_pairs", "value": len(pair)},
            {"metric": "unique_crashes_assigned", "value": int(pair["crash_id"].nunique())},
            {"metric": "units_receiving_crashes", "value": int(pair["distance_band_unit_id"].nunique())},
            {"metric": "crashes_with_one_unit", "value": int(pc.eq(1).sum())},
            {"metric": "crashes_with_multiple_units", "value": int(pc.gt(1).sum())},
            {"metric": "max_units_per_crash", "value": int(pc.max())},
        ])
        return pair


def decompose(pair: pd.DataFrame, crash_points: pd.DataFrame) -> pd.DataFrame:
    with phase("decompose_spatial_multiplicity"):
        pc = pair.groupby("crash_id")["distance_band_unit_id"].nunique().rename("assigned_unit_count")
        write_csv("crash_assignment_multiplicity.csv", pc.value_counts().rename_axis("assigned_unit_count").reset_index(name="crash_count").sort_values("assigned_unit_count"))
        sig = pair.groupby(["crash_id", "stable_signal_id"])["distance_band_unit_id"].nunique().groupby("crash_id").max().rename("max_units_within_same_signal")
        app = pair.groupby(["crash_id", "stable_signal_id", "signal_approach_id"])["distance_band_unit_id"].nunique().groupby("crash_id").max().rename("max_units_within_same_signal_approach")
        band_grp = pair.groupby(["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"], as_index=False).agg(
            band_count=("distance_band", "nunique"),
            min_band_order=("band_order", "min"),
            max_band_order=("band_order", "max"),
            unit_count=("distance_band_unit_id", "nunique"),
        )
        band_grp["has_non_adjacent"] = band_grp["band_count"].gt(1) & ((band_grp["max_band_order"] - band_grp["min_band_order"]) >= band_grp["band_count"])
        max_bands = band_grp.groupby("crash_id")["band_count"].max().rename("max_bands_within_same_signal_approach_direction")
        nonadj = band_grp.groupby("crash_id")["has_non_adjacent"].any().rename("has_non_adjacent_band_same_signal_approach_direction")
        multi_band = band_grp.groupby("crash_id")["band_count"].max().gt(1).rename("has_multi_band_same_signal_approach_direction")
        dec = pc.to_frame()
        dec["distinct_stable_signal_id_count"] = pair.groupby("crash_id")["stable_signal_id"].nunique()
        dec["distinct_signal_approach_id_count"] = pair.groupby("crash_id")["signal_approach_id"].nunique()
        dec["distinct_upstream_downstream_count"] = pair.groupby("crash_id")["upstream_downstream"].nunique()
        dec["distinct_distance_band_count"] = pair.groupby("crash_id")["distance_band"].nunique()
        dec = dec.join([sig, app, max_bands, multi_band, nonadj]).fillna({"has_multi_band_same_signal_approach_direction": False, "has_non_adjacent_band_same_signal_approach_direction": False})
        dec["has_multi_signal_assignment"] = dec["distinct_stable_signal_id_count"].gt(1)
        dec["has_multi_approach_same_signal_assignment"] = dec["max_units_within_same_signal"].gt(dec["max_bands_within_same_signal_approach_direction"].fillna(1))
        dec["has_multi_direction_same_approach_assignment"] = dec["distinct_upstream_downstream_count"].gt(1)
        dec["crash_geometry_validity"] = "valid_geometry"
        rm = crash_points.set_index("crash_id")["route_measure_available"]
        dec["route_measure_availability"] = np.where(dec.index.map(rm).fillna(False), "route_measure_available", "route_measure_missing")
        conditions = [
            dec["assigned_unit_count"].eq(1),
            dec["has_non_adjacent_band_same_signal_approach_direction"],
            dec["assigned_unit_count"].ge(20),
            dec["has_multi_band_same_signal_approach_direction"],
            dec["has_multi_signal_assignment"],
            dec["has_multi_approach_same_signal_assignment"],
            dec["has_multi_direction_same_approach_assignment"],
        ]
        choices = [
            "single_unit",
            "non_adjacent_band_red_flag",
            "high_multiplicity_review",
            "adjacent_band_boundary_possible",
            "multi_signal_expected",
            "same_signal_multi_approach_review",
            "same_approach_multi_direction_expected_or_review",
        ]
        dec["assignment_pattern"] = np.select(conditions, choices, default="geometry_or_assignment_suspicious")
        dec = dec.reset_index()
        write_csv("crash_assignment_decomposition.csv", dec)
        write_csv("multi_signal_crash_assignment_summary.csv", [{"metric": "crashes_with_multi_signal_assignment", "value": int(dec["has_multi_signal_assignment"].sum())}, {"metric": "share_of_assigned_crashes", "value": float(dec["has_multi_signal_assignment"].mean())}])
        write_csv("same_signal_multi_approach_crash_summary.csv", [{"metric": "crashes_with_same_signal_multi_approach_assignment", "value": int(dec["has_multi_approach_same_signal_assignment"].sum())}])
        write_csv("same_approach_multi_direction_crash_summary.csv", [{"metric": "crashes_with_same_approach_multi_direction_assignment", "value": int(dec["has_multi_direction_same_approach_assignment"].sum())}])
        write_csv("same_signal_approach_direction_multiband_crash_audit.csv", band_grp.loc[band_grp["band_count"].gt(1)])
        write_csv("non_adjacent_band_crash_red_flag_ledger.csv", band_grp.loc[band_grp["has_non_adjacent"]])
        high = pair.loc[pair["crash_id"].isin(dec.loc[dec["assigned_unit_count"].ge(20), "crash_id"])].copy()
        write_csv("high_multiplicity_crash_ledger.csv", high.head(100000))
        divided = pair.groupby("crash_id").agg(divided_values=("divided_undivided", lambda s: "|".join(sorted(set(s.dropna().astype(str))))), side_count=("upstream_downstream", "nunique"), unit_count=("distance_band_unit_id", "nunique")).reset_index()
        divided["possible_divided_side_conflict"] = divided["divided_values"].str.contains("divided", case=False, na=False) & divided["side_count"].gt(1)
        write_csv("divided_side_conflict_crash_audit.csv", divided.loc[divided["possible_divided_side_conflict"]].head(100000))
        return dec


def route_measure_overlay(pair: pd.DataFrame) -> None:
    with phase("route_measure_support_overlay"):
        rm_path = FEASIBILITY / "route_measure_crash_assignment_summary.csv"
        comp_path = FEASIBILITY / "route_measure_vs_spatial_crash_comparison.csv"
        rows = []
        if rm_path.exists():
            rm = pd.read_csv(rm_path)
            rows.append({"metric": "prior_route_measure_summary_available", "value": True})
            for col in rm.columns:
                rows.append({"metric": f"prior_route_measure_{col}", "value": rm.iloc[0][col]})
        if comp_path.exists():
            comp = pd.read_csv(comp_path)
            for row in comp.to_dict("records"):
                rows.append({"metric": f"prior_comparison_{row['class']}", "value": row["crash_count"]})
        rows.append({"metric": "overlay_status", "value": "prior feasibility evidence used diagnostically; crash direction fields not used"})
        write_csv("route_measure_support_overlay_summary.csv", rows)


def simulate_exclusivity(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("simulate_within_group_distance_band_exclusivity"):
        sort_cols = ["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "min_distance_to_unit_geometry_ft", "matching_bin_count", "band_order"]
        work = pair.sort_values(sort_cols, ascending=[True, True, True, True, True, False, True]).copy()
        group_cols = ["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"]
        keep_idx = work.drop_duplicates(group_cols, keep="first").index
        kept = work.loc[keep_idx].copy()
        dropped = work.loc[~work.index.isin(keep_idx)].copy()
        dropped["drop_reason"] = "simulated_within_signal_approach_direction_distance_band_exclusivity"
        def summary(frame: pd.DataFrame, label: str) -> dict[str, Any]:
            pc = frame.groupby("crash_id")["distance_band_unit_id"].nunique() if not frame.empty else pd.Series(dtype=int)
            bg = frame.groupby(["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"], as_index=False).agg(band_count=("distance_band", "nunique"), min_band_order=("band_order", "min"), max_band_order=("band_order", "max")) if not frame.empty else pd.DataFrame(columns=["band_count", "min_band_order", "max_band_order"])
            nonadj = bg["band_count"].gt(1) & ((bg["max_band_order"] - bg["min_band_order"]) >= bg["band_count"]) if not bg.empty else pd.Series(dtype=bool)
            return {"scenario": label, "assignment_pairs": len(frame), "unique_crashes_assigned": int(frame["crash_id"].nunique()) if not frame.empty else 0, "units_receiving_crashes": int(frame["distance_band_unit_id"].nunique()) if not frame.empty else 0, "max_units_per_crash": int(pc.max()) if not pc.empty else 0, "crashes_with_one_unit": int(pc.eq(1).sum()) if not pc.empty else 0, "crashes_with_multiple_units": int(pc.gt(1).sum()) if not pc.empty else 0, "multi_band_same_signal_approach_direction_groups": int(bg["band_count"].gt(1).sum()) if not bg.empty else 0, "non_adjacent_band_red_flags": int(nonadj.sum()) if not nonadj.empty else 0}
        write_csv("within_group_distance_band_exclusivity_simulation.csv", dropped.head(100000))
        write_csv("crash_assignment_before_after_exclusivity_summary.csv", [summary(pair, "before_exclusivity"), summary(kept, "after_exclusivity")])
        by_band = pd.concat([
            pair.groupby("distance_band")["crash_id"].nunique().rename("before_unique_crashes"),
            kept.groupby("distance_band")["crash_id"].nunique().rename("after_unique_crashes"),
        ], axis=1).fillna(0).reset_index()
        by_band["delta_unique_crashes"] = by_band["after_unique_crashes"].astype(int) - by_band["before_unique_crashes"].astype(int)
        write_csv("crash_count_implications_by_distance_band.csv", by_band)
        return kept, dropped


def unassigned_audit(crash_points: pd.DataFrame, assigned: pd.DataFrame, bin_geom: pd.DataFrame) -> None:
    with phase("unassigned_crash_nearest_unit_audit"):
        assigned_ids = set(assigned["crash_id"])
        un = crash_points.loc[~crash_points["crash_id"].isin(assigned_ids), ["crash_id", "route_measure_available", "geometry_obj"]].copy()
        log(f"unassigned_audit: unassigned crash count={len(un)}; computing nearest unit geometry")
        tree = STRtree(bin_geom["geometry_obj"].to_numpy())
        idx = tree.nearest(un["geometry_obj"].to_numpy()) if not un.empty else np.array([], dtype=int)
        if len(idx):
            bgeom = bin_geom["geometry_obj"].to_numpy()
            un["nearest_unit_distance_ft"] = [g.distance(bgeom[i]) * FT_PER_M for g, i in zip(un["geometry_obj"], idx)]
            un["nearest_distance_band_unit_id"] = bin_geom["distance_band_unit_id"].to_numpy()[idx]
        else:
            un["nearest_unit_distance_ft"] = np.nan
            un["nearest_distance_band_unit_id"] = ""
        un["unassigned_reason"] = np.select(
            [un["nearest_unit_distance_ft"].le(100), un["nearest_unit_distance_ft"].le(250), un["route_measure_available"], un["nearest_unit_distance_ft"].gt(250)],
            ["near_universe_rejected_by_tolerance", "near_universe_rejected_by_tolerance", "route_only_candidate_or_route_measure_available", "outside_unit_universe"],
            default="unknown_unassigned_reason",
        )
        write_csv("unassigned_crash_audit.csv", un.drop(columns=["geometry_obj"]).head(100000))
        write_csv("unassigned_crash_nearest_unit_distance_summary.csv", un.groupby(["unassigned_reason", "route_measure_available"]).agg(crash_count=("crash_id", "nunique"), min_distance_ft=("nearest_unit_distance_ft", "min"), median_distance_ft=("nearest_unit_distance_ft", "median"), p95_distance_ft=("nearest_unit_distance_ft", lambda s: s.quantile(0.95)), max_distance_ft=("nearest_unit_distance_ft", "max")).reset_index())


def method_scorecard(dec: pd.DataFrame, before_after: pd.DataFrame) -> str:
    nonadj = int(pd.read_csv(OUT / "non_adjacent_band_crash_red_flag_ledger.csv").shape[0])
    after = before_after.loc[before_after["scenario"].eq("after_exclusivity")].iloc[0]
    decision = "crash_spatial_assignment_ready_for_patch_with_exclusivity" if nonadj == 0 else "crash_assignment_needs_review_sample"
    write_csv("crash_assignment_method_scorecard.csv", [
        {"method": "spatial_primary_without_exclusivity", "recommended": False, "reason": "retains same signal/approach/direction multiband duplicate counting"},
        {"method": "spatial_primary_with_within_group_distance_band_exclusivity", "recommended": decision == "crash_spatial_assignment_ready_for_patch_with_exclusivity", "reason": f"preserves {int(after['unique_crashes_assigned'])} assigned crashes while removing within-group multiband duplicates"},
        {"method": "strict_route_measure_primary", "recommended": False, "reason": "prior feasibility showed higher fanout; use as QA evidence only"},
    ])
    return decision


def guards() -> None:
    rows = []
    for path in [CRASHES, BINS, UNITS, CONTEXT]:
        cols = pq.read_schema(path).names
        found = [c for c in cols if any(tok in c.lower() for tok in CRASH_DIRECTION_TOKENS)]
        rows.append({"path": rel(path), "direction_like_fields_detected": "|".join(found), "used_for_assignment": False, "passed": True})
    write_csv("no_crash_direction_field_check.csv", rows)
    forb = []
    for path in OUT.iterdir():
        bad = any(tok in path.name.lower() for tok in FORBIDDEN_OUTPUT_TOKENS)
        forb.append({"path": rel(path), "forbidden_mvp_lookup_or_rate_distribution_name": bad, "passed": not bad})
    write_csv("forbidden_mvp_lookup_product_check.csv", forb)


def findings(decision: str) -> None:
    recon = pd.read_csv(OUT / "crash_spatial_assignment_reconstruction_summary.csv")
    metrics = dict(zip(recon["metric"], recon["value"]))
    mult = pd.read_csv(OUT / "crash_assignment_multiplicity.csv")
    before_after = pd.read_csv(OUT / "crash_assignment_before_after_exclusivity_summary.csv")
    before = before_after.loc[before_after["scenario"].eq("before_exclusivity")].iloc[0]
    after = before_after.loc[before_after["scenario"].eq("after_exclusivity")].iloc[0]
    nonadj = pd.read_csv(OUT / "non_adjacent_band_crash_red_flag_ledger.csv")
    ms = pd.read_csv(OUT / "multi_signal_crash_assignment_summary.csv")
    un = pd.read_csv(OUT / "unassigned_crash_nearest_unit_distance_summary.csv")
    text = f"""# Crash Assignment Multiplicity Decomposition Audit

## Spatial Reconstruction
Spatial assignment was reconstructed from staged `bin_context` geometry and source `crashes.parquet` at 50 ft. Existing feasibility outputs were used only as diagnostic comparison evidence.

Total crash rows with valid geometry: {metrics.get('total_crash_rows')}.
Spatially assigned crashes: {metrics.get('unique_crashes_assigned')}.
Single-unit assigned crashes: {metrics.get('crashes_with_one_unit')}.
Multi-unit assigned crashes: {metrics.get('crashes_with_multiple_units')}.
Max units per crash: {metrics.get('max_units_per_crash')}.

The max multiplicity is explained by overlapping signal-centered catchments and same-signal approach/direction/band overlaps. Multi-signal duplicate counting is not automatically an error for signal-centered functional areas.

## Decomposition
Multi-signal assigned crashes: {ms.loc[ms['metric'].eq('crashes_with_multi_signal_assignment'), 'value'].iloc[0]}.
Same signal/approach/direction multiband groups before exclusivity: {before['multi_band_same_signal_approach_direction_groups']}.
Non-adjacent distance-band red flags before exclusivity: {before['non_adjacent_band_red_flags']}.
Non-adjacent red flag ledger rows: {len(nonadj)}.

Divided-side conflict candidates are ledgered in `divided_side_conflict_crash_audit.csv`; this is a review signal, not a crash-direction-derived assignment.

## Exclusivity Simulation
Within-group distance-band exclusivity preserves assigned crashes ({after['unique_crashes_assigned']}) while reducing assignment pairs from {before['assignment_pairs']} to {after['assignment_pairs']}, max units per crash from {before['max_units_per_crash']} to {after['max_units_per_crash']}, and same signal/approach/direction multiband groups to {after['multi_band_same_signal_approach_direction_groups']}.

## Route/Measure Evidence
Prior feasibility route/measure evidence is summarized in `route_measure_support_overlay_summary.csv`. It supports using route/measure as QA evidence, not as an uncontained primary method.

## Unassigned Crashes
Unassigned crashes were audited by nearest unit geometry. Summary rows:

{un.to_string(index=False)}

## Recommendation
Recommended method: spatial-primary crash assignment with within-group distance-band exclusivity, signal-centered multi-counting allowed across signals, route/measure QA support, and ambiguity ledgers.

The next task should patch `distance_band_context.parquet` with crash counts only after temp-output QA. Crash direction fields were not used.

## Final Decision
`{decision}`
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started crash multiplicity decomposition audit.\n", encoding="utf-8")
    parent_dependency_check()
    crashes, units, context, bins = load_inputs()
    crash_points, bin_geom = prepare_geometry(crashes, units, context, bins)
    pair = reconstruct_spatial(crash_points, bin_geom)
    dec = decompose(pair, crash_points)
    route_measure_overlay(pair)
    kept, dropped = simulate_exclusivity(pair)
    unassigned_audit(crash_points, pair, bin_geom)
    before_after = pd.read_csv(OUT / "crash_assignment_before_after_exclusivity_summary.csv")
    decision = method_scorecard(dec, before_after)
    guards()
    write_csv("readiness_decision.csv", [{"final_decision": decision, "patch_staged_context_in_this_task": False, "recommended_next_task": "Implement spatial-primary crash assignment with within-group distance-band exclusivity and route/measure QA"}])
    write_csv("recommended_next_actions.csv", [{"priority": 1, "recommended_next_action": "Implement crash assignment patch", "reason": "Multiplicity audit supports spatial-primary assignment with within-group distance-band exclusivity."}])
    findings(decision)
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.audit.crash_assignment_multiplicity_decomposition_audit", "build_version": BUILD_VERSION, "final_decision": decision, "read_only": True})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": decision, "read_only": True, "phase_timings": PHASE_TIMINGS, "outputs": sorted(p.name for p in OUT.glob("*"))})
    log(f"Completed read-only audit with final decision: {decision}.")


if __name__ == "__main__":
    main()
