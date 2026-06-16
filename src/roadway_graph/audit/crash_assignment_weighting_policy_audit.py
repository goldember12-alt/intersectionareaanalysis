"""Read-only crash assignment weighting policy audit.

This audit compares crash numerator policies after reconstructing 50 ft spatial
candidate assignments and simulating within signal/approach/direction
distance-band exclusivity. It does not patch staged context products.
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
OUT = REPO / "work/roadway_graph/review/crash_assignment_weighting_policy_audit"
SIGNALS = STAGING / "signal_index.parquet"
BINS = STAGING / "bin_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
CONTEXT = STAGING / "distance_band_context.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"
FEASIBILITY = REPO / "work/roadway_graph/review/crash_assignment_feasibility_audit"

FT_PER_M = 3.280839895
TOL_FT = 50.0
BUILD_VERSION = "crash_assignment_weighting_policy_audit_v1_2026-06-15"
CRASH_DIRECTION_TOKENS = ("direction", "dir", "travel_direction", "veh_direction", "crash_direction", "bearing")
FORBIDDEN_OUTPUT_TOKENS = ("lookup_cells", "rate_distribution", "mvp_directional_rate_distribution")
BAND_ORDER = {
    "0_250ft": 0, "250_500ft": 1, "500_1000ft": 2, "1000_1500ft": 3, "1500_2000ft": 4, "2000_2500ft": 5,
    "0-250": 0, "250-500": 1, "500-1,000": 2, "1000-1500": 3, "1,000-1,500": 3,
    "1500-2000": 4, "1,500-2,000": 4, "2000-2500": 5, "2,000-2,500": 5,
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


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_series(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.strip()


def parent_dependency_check() -> None:
    rows = []
    for path in [SIGNALS, BINS, UNITS, CONTEXT, CRASHES, FEASIBILITY / "route_measure_vs_spatial_crash_comparison.csv"]:
        role = "staged_or_source_parent" if path != FEASIBILITY / "route_measure_vs_spatial_crash_comparison.csv" else "diagnostic_evidence_only"
        rows.append({"path": rel(path), "role": role, "exists": path.exists(), "sha256": sha(path) if path.exists() else ""})
    write_csv("parent_dependency_check.csv", rows)


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("load_inputs"):
        crashes = pd.read_parquet(CRASHES)
        units = pd.read_parquet(UNITS)
        context_cols = ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "divided_undivided", "one_way_two_way"]
        context = pd.read_parquet(CONTEXT, columns=context_cols)
        bin_cols = ["stable_bin_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "geometry", "geometry_length_ft"]
        bins = pd.read_parquet(BINS, columns=bin_cols)
        signals = pd.read_parquet(SIGNALS, columns=["stable_signal_id", "geometry"])
        return crashes, units, context, bins, signals


def prepare_geometry(crashes: pd.DataFrame, units: pd.DataFrame, context: pd.DataFrame, bins: pd.DataFrame, signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("prepare_geometry"):
        c = crashes.loc[crashes["geometry"].notna(), ["DOCUMENT_NBR", "geometry", "RTE_NM", "RNS_MP"]].copy()
        c["crash_id"] = clean_series(c["DOCUMENT_NBR"])
        c["route_measure_available"] = clean_series(c["RTE_NM"]).ne("") & pd.to_numeric(c["RNS_MP"], errors="coerce").notna()
        c["geometry_obj"] = from_wkb(c["geometry"].to_numpy())
        c = c.loc[~pd.isna(c["geometry_obj"]) & c["crash_id"].ne("")].reset_index(drop=True)
        b = bins.loc[bins["geometry"].notna()].copy()
        b["upstream_downstream"] = clean_series(b["upstream_downstream"])
        b.loc[~b["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        b = b.merge(units[["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]], on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"], how="left", validate="many_to_one")
        b = b.merge(context[["distance_band_unit_id", "divided_undivided", "one_way_two_way"]], on="distance_band_unit_id", how="left")
        b = b.loc[b["distance_band_unit_id"].notna()].reset_index(drop=True)
        b["geometry_obj"] = from_wkb(b["geometry"].to_numpy())
        b = b.loc[~pd.isna(b["geometry_obj"])].reset_index(drop=True)
        s = signals.loc[signals["geometry"].notna(), ["stable_signal_id", "geometry"]].copy()
        s["signal_geometry_obj"] = from_wkb(s["geometry"].to_numpy())
        s = s.loc[~pd.isna(s["signal_geometry_obj"])].drop_duplicates("stable_signal_id")
        return c, b, s


def reconstruct_candidates(crash_points: pd.DataFrame, bin_geom: pd.DataFrame, signals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("reconstruct_spatial_candidates", crash_points=len(crash_points), bin_rows=len(bin_geom)):
        tree = STRtree(bin_geom["geometry_obj"].to_numpy())
        cgeom = crash_points["geometry_obj"].to_numpy()
        bgeom = bin_geom["geometry_obj"].to_numpy()
        log("spatial candidates: STRtree query at 50 ft")
        found = tree.query(cgeom, predicate="dwithin", distance=TOL_FT / FT_PER_M)
        ci, bi = found[0].astype("int64"), found[1].astype("int64")
        log(f"spatial candidates: raw crash-bin pairs={len(ci)}")
        raw = pd.DataFrame({"crash_index": ci, "bin_index": bi})
        raw["crash_id"] = crash_points["crash_id"].to_numpy()[ci]
        raw["route_measure_available"] = crash_points["route_measure_available"].to_numpy()[ci]
        for col in ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id", "divided_undivided", "one_way_two_way"]:
            raw[col] = bin_geom[col].to_numpy()[bi]
        log("spatial candidates: exact unit distances")
        raw["distance_to_unit_geometry_ft"] = [cgeom[c].distance(bgeom[b]) * FT_PER_M for c, b in zip(ci, bi)]
        raw["band_order"] = clean_series(raw["distance_band"]).map(BAND_ORDER).fillna(999).astype(int)
        pair = raw.groupby(["crash_id", "distance_band_unit_id"], as_index=False).agg(
            route_measure_available=("route_measure_available", "first"),
            stable_signal_id=("stable_signal_id", "first"),
            signal_approach_id=("signal_approach_id", "first"),
            upstream_downstream=("upstream_downstream", "first"),
            distance_band=("distance_band", "first"),
            band_order=("band_order", "first"),
            distance_to_unit_geometry_ft=("distance_to_unit_geometry_ft", "min"),
            matching_bin_count=("stable_bin_id", "nunique"),
            divided_undivided=("divided_undivided", "first"),
            one_way_two_way=("one_way_two_way", "first"),
        )
        log("spatial candidates: signal distances on reduced pairs")
        crash_geom_map = crash_points.set_index("crash_id")["geometry_obj"]
        sig_geom_map = signals.set_index("stable_signal_id")["signal_geometry_obj"]
        pair["distance_to_signal_ft"] = [
            crash_geom_map.loc[c].distance(sig_geom_map.loc[s]) * FT_PER_M if s in sig_geom_map.index else np.nan
            for c, s in zip(pair["crash_id"], pair["stable_signal_id"])
        ]
        pc = pair.groupby("crash_id")["distance_band_unit_id"].nunique()
        write_csv("spatial_crash_candidate_reconstruction_summary.csv", [
            {"metric": "total_crash_rows_with_geometry", "value": len(crash_points)},
            {"metric": "raw_crash_bin_pairs", "value": len(raw)},
            {"metric": "candidate_unit_pairs", "value": len(pair)},
            {"metric": "unique_crashes_assigned", "value": int(pair["crash_id"].nunique())},
            {"metric": "units_receiving_candidates", "value": int(pair["distance_band_unit_id"].nunique())},
            {"metric": "max_units_per_crash", "value": int(pc.max())},
        ])
        return pair, raw


def apply_band_exclusivity(pair: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("apply_band_exclusivity_simulation"):
        group_cols = ["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"]
        work = pair.sort_values(group_cols + ["distance_to_unit_geometry_ft", "matching_bin_count", "band_order", "distance_band_unit_id"], ascending=[True, True, True, True, True, False, True, True]).copy()
        keep_idx = work.drop_duplicates(group_cols, keep="first").index
        kept = work.loc[keep_idx].copy()
        dropped = work.loc[~work.index.isin(keep_idx)].copy()
        dropped["simulated_drop_reason"] = "within_signal_approach_direction_band_exclusivity"
        bg = pair.groupby(group_cols, as_index=False).agg(band_count=("distance_band", "nunique"), min_band_order=("band_order", "min"), max_band_order=("band_order", "max"))
        bg["has_non_adjacent"] = bg["band_count"].gt(1) & ((bg["max_band_order"] - bg["min_band_order"]) >= bg["band_count"])
        pc_before = pair.groupby("crash_id")["distance_band_unit_id"].nunique()
        pc_after = kept.groupby("crash_id")["distance_band_unit_id"].nunique()
        write_csv("band_exclusivity_simulation_summary.csv", [
            {"scenario": "raw_spatial", "assignment_pairs": len(pair), "unique_crashes": pair["crash_id"].nunique(), "max_units_per_crash": int(pc_before.max()), "same_group_multiband_groups": int(bg["band_count"].gt(1).sum()), "non_adjacent_groups": int(bg["has_non_adjacent"].sum())},
            {"scenario": "after_band_exclusivity", "assignment_pairs": len(kept), "unique_crashes": kept["crash_id"].nunique(), "max_units_per_crash": int(pc_after.max()), "same_group_multiband_groups": 0, "non_adjacent_groups": 0},
        ])
        return kept, dropped


def zero_crash_audit(context: pd.DataFrame, raw_pair: pd.DataFrame, kept: pd.DataFrame) -> None:
    with phase("zero_crash_signal_approach_unit_audit"):
        rows = []
        for label, frame in [("raw_spatial", raw_pair), ("after_band_exclusivity", kept)]:
            sigs = set(frame["stable_signal_id"])
            apps = set(frame["signal_approach_id"])
            units = set(frame["distance_band_unit_id"])
            rows.extend([
                {"scenario": label, "grain": "signal", "total": context["stable_signal_id"].nunique(), "with_candidate_crash": len(sigs), "zero_candidate_crash": context["stable_signal_id"].nunique() - len(sigs)},
                {"scenario": label, "grain": "approach", "total": context["signal_approach_id"].nunique(), "with_candidate_crash": len(apps), "zero_candidate_crash": context["signal_approach_id"].nunique() - len(apps)},
                {"scenario": label, "grain": "unit", "total": context["distance_band_unit_id"].nunique(), "with_candidate_crash": len(units), "zero_candidate_crash": context["distance_band_unit_id"].nunique() - len(units)},
            ])
        by = []
        for cols in [["distance_band"], ["upstream_downstream"], ["distance_band", "upstream_downstream"]]:
            total = context.groupby(cols)["distance_band_unit_id"].nunique().reset_index(name="total_units")
            got = kept.groupby(cols)["distance_band_unit_id"].nunique().reset_index(name="with_candidate_crash_units")
            cur = total.merge(got, on=cols, how="left").fillna(0)
            cur["zero_candidate_crash_units"] = cur["total_units"] - cur["with_candidate_crash_units"]
            by.append(cur)
        write_csv("zero_crash_signal_approach_unit_audit.csv", pd.concat([pd.DataFrame(rows), *by], ignore_index=True, sort=False))


def add_weights(frame: pd.DataFrame, method: str) -> pd.DataFrame:
    out = frame.copy()
    if method == "equal_weight":
        n = out.groupby("crash_id")["distance_band_unit_id"].transform("nunique")
        out["weight"] = 1.0 / n
    elif method == "inverse_distance_to_unit_p1":
        score = 1.0 / np.maximum(pd.to_numeric(out["distance_to_unit_geometry_ft"], errors="coerce").fillna(50.0), 5.0)
        out["weight"] = score / score.groupby(out["crash_id"]).transform("sum")
    elif method == "inverse_distance_to_unit_p2":
        score = 1.0 / np.maximum(pd.to_numeric(out["distance_to_unit_geometry_ft"], errors="coerce").fillna(50.0), 5.0) ** 2
        out["weight"] = score / score.groupby(out["crash_id"]).transform("sum")
    elif method == "inverse_distance_to_signal":
        score = 1.0 / np.maximum(pd.to_numeric(out["distance_to_signal_ft"], errors="coerce").fillna(2500.0), 25.0)
        out["weight"] = score / score.groupby(out["crash_id"]).transform("sum")
    elif method == "hybrid_signal_then_unit":
        sig = out[["crash_id", "stable_signal_id", "distance_to_signal_ft"]].drop_duplicates()
        sig_score = 1.0 / np.maximum(pd.to_numeric(sig["distance_to_signal_ft"], errors="coerce").fillna(2500.0), 25.0)
        sig["signal_weight"] = sig_score / sig_score.groupby(sig["crash_id"]).transform("sum")
        out = out.merge(sig[["crash_id", "stable_signal_id", "signal_weight"]], on=["crash_id", "stable_signal_id"], how="left")
        within = out.groupby(["crash_id", "stable_signal_id"])["distance_band_unit_id"].transform("nunique")
        out["weight"] = out["signal_weight"] / within
        out = out.drop(columns=["signal_weight"])
    else:
        raise ValueError(method)
    out["weighting_method"] = method
    return out


def summarize_policy(name: str, frame: pd.DataFrame, weight_col: str, context: pd.DataFrame) -> dict[str, Any]:
    pc = frame.groupby("crash_id")["distance_band_unit_id"].nunique() if not frame.empty else pd.Series(dtype=int)
    unit_weight = frame.groupby("distance_band_unit_id")[weight_col].sum() if not frame.empty else pd.Series(dtype=float)
    sig_weight = frame.groupby("stable_signal_id")[weight_col].sum() if not frame.empty else pd.Series(dtype=float)
    app_weight = frame.groupby("signal_approach_id")[weight_col].sum() if not frame.empty else pd.Series(dtype=float)
    return {
        "policy": name,
        "assigned_unique_crashes": int(frame["crash_id"].nunique()) if not frame.empty else 0,
        "assignment_pairs": len(frame),
        "total_unweighted_crash_count_contribution": float(len(frame)),
        "total_weighted_crash_count_contribution": float(frame[weight_col].sum()) if not frame.empty else 0.0,
        "max_units_per_crash": int(pc.max()) if not pc.empty else 0,
        "average_units_per_crash": float(pc.mean()) if not pc.empty else 0.0,
        "units_receiving_crash_gt0": int(unit_weight.gt(0).sum()),
        "signals_receiving_crash_gt0": int(sig_weight.gt(0).sum()),
        "approaches_receiving_crash_gt0": int(app_weight.gt(0).sum()),
        "zero_crash_units": int(context["distance_band_unit_id"].nunique() - unit_weight.gt(0).sum()),
        "zero_crash_signals": int(context["stable_signal_id"].nunique() - sig_weight.gt(0).sum()),
        "zero_crash_approaches": int(context["signal_approach_id"].nunique() - app_weight.gt(0).sum()),
    }


def policy_comparison(raw_pair: pd.DataFrame, kept: pd.DataFrame, context: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("policy_and_weighting_comparison"):
        raw_full = raw_pair.copy()
        raw_full["count"] = 1.0
        kept_full = kept.copy()
        kept_full["count"] = 1.0
        nearest = kept.sort_values(["crash_id", "distance_to_unit_geometry_ft", "distance_to_signal_ft", "band_order", "distance_band_unit_id"]).drop_duplicates("crash_id").copy()
        nearest["count"] = 1.0
        equal = add_weights(raw_pair, "equal_weight")
        preferred = add_weights(kept, "equal_weight")
        rows = [
            summarize_policy("full_double_count_raw_spatial", raw_full, "count", context),
            summarize_policy("full_double_count_with_band_exclusivity", kept_full, "count", context),
            summarize_policy("nearest_single_unit_owner", nearest, "count", context),
            summarize_policy("total_preserving_fractional_all_candidates_equal", equal, "weight", context),
            summarize_policy("total_preserving_fractional_after_band_exclusivity_equal", preferred, "weight", context),
        ]
        write_csv("crash_policy_comparison_summary.csv", rows)
        band_rows = []
        dir_rows = []
        for name, frame, weight_col in [
            ("full_double_count_with_band_exclusivity", kept_full, "count"),
            ("nearest_single_unit_owner", nearest, "count"),
            ("fractional_after_band_exclusivity_equal", preferred, "weight"),
        ]:
            b = frame.groupby("distance_band")[weight_col].sum().reset_index(name="crash_weight")
            b["policy"] = name
            d = frame.groupby("upstream_downstream")[weight_col].sum().reset_index(name="crash_weight")
            d["policy"] = name
            band_rows.append(b)
            dir_rows.append(d)
        write_csv("weighted_crash_count_by_distance_band.csv", pd.concat(band_rows, ignore_index=True, sort=False))
        write_csv("weighted_crash_count_by_upstream_downstream.csv", pd.concat(dir_rows, ignore_index=True, sort=False))
        return preferred, nearest


def weighting_formula_comparison(kept: pd.DataFrame) -> pd.DataFrame:
    with phase("weighting_formula_comparison"):
        methods = ["equal_weight", "inverse_distance_to_unit_p1", "inverse_distance_to_unit_p2", "inverse_distance_to_signal", "hybrid_signal_then_unit"]
        rows = []
        checks = []
        high_rows = []
        for method in methods:
            w = add_weights(kept, method)
            sums = w.groupby("crash_id")["weight"].sum()
            checks.append({"weighting_method": method, "crashes_checked": len(sums), "min_sum": float(sums.min()), "max_sum": float(sums.max()), "mean_sum": float(sums.mean()), "passed": bool(np.allclose(sums.to_numpy(), 1.0, atol=1e-9))})
            rows.append({"weighting_method": method, "assignment_pairs": len(w), "assigned_unique_crashes": w["crash_id"].nunique(), "min_weight": float(w["weight"].min()), "max_weight": float(w["weight"].max()), "mean_weight": float(w["weight"].mean()), "zero_distance_pair_count": int(pd.to_numeric(w["distance_to_unit_geometry_ft"], errors="coerce").le(0.01).sum()), "total_weight": float(w["weight"].sum())})
            pc = w.groupby("crash_id")["distance_band_unit_id"].nunique()
            high_ids = set(pc[pc.ge(20)].index)
            hw = w.loc[w["crash_id"].isin(high_ids)]
            if not hw.empty:
                high_rows.append({"weighting_method": method, "high_multiplicity_crashes": len(high_ids), "high_multiplicity_pairs": len(hw), "min_high_pair_weight": float(hw["weight"].min()), "max_high_pair_weight": float(hw["weight"].max()), "sum_high_weights": float(hw["weight"].sum())})
        write_csv("crash_weighting_formula_comparison.csv", rows)
        write_csv("per_crash_weight_sum_check.csv", checks)
        write_csv("high_multiplicity_weighting_audit.csv", high_rows)
        return add_weights(kept, "equal_weight")


def constraint_and_overlay_outputs(kept_weighted: pd.DataFrame, raw_pair: pd.DataFrame, kept: pd.DataFrame) -> None:
    with phase("constraint_and_overlay_outputs"):
        same = raw_pair.groupby("crash_id").agg(
            same_signal_count=("stable_signal_id", "nunique"),
            approach_count=("signal_approach_id", "nunique"),
            direction_count=("upstream_downstream", "nunique"),
            unit_count=("distance_band_unit_id", "nunique"),
        ).reset_index()
        same["multi_signal"] = same["same_signal_count"].gt(1)
        same["multi_approach"] = same["approach_count"].gt(1)
        same["multi_direction"] = same["direction_count"].gt(1)
        write_csv("same_signal_assignment_constraint_audit.csv", [
            {"metric": "crashes_with_multi_signal_assignment", "value": int(same["multi_signal"].sum())},
            {"metric": "crashes_with_multi_approach_assignment", "value": int(same["multi_approach"].sum())},
            {"metric": "crashes_with_multi_direction_assignment", "value": int(same["multi_direction"].sum())},
            {"metric": "recommendation", "value": "keep with fractional weighting; ledger non-adjacent and divided-side review cases"},
        ])
        div = kept_weighted.groupby("crash_id").agg(divided_values=("divided_undivided", lambda s: "|".join(sorted(set(s.dropna().astype(str))))), direction_count=("upstream_downstream", "nunique"), weighted_sum=("weight", "sum")).reset_index()
        div["possible_divided_side_conflict"] = div["divided_values"].str.contains("divided", case=False, na=False) & div["direction_count"].gt(1)
        write_csv("divided_side_conflict_weighting_audit.csv", div.loc[div["possible_divided_side_conflict"]].head(100000))
        rm = []
        if (FEASIBILITY / "route_measure_vs_spatial_crash_comparison.csv").exists():
            comp = pd.read_csv(FEASIBILITY / "route_measure_vs_spatial_crash_comparison.csv")
            for row in comp.to_dict("records"):
                rm.append({"route_measure_overlay_class": row["class"], "crash_count": row["crash_count"], "note": "diagnostic prior evidence only"})
        rm.append({"route_measure_overlay_class": "recommended_use", "crash_count": "", "note": "route/measure should be QA support, not primary count evidence"})
        write_csv("route_measure_qa_overlay_summary.csv", rm)


def scorecard_and_fields() -> str:
    decision = "implement_spatial_fractional_crash_assignment_next"
    write_csv("crash_policy_scorecard.csv", [
        {"policy": "full_double_count_raw_spatial", "recommended": False, "reason": "inflates event numerator across overlapping units"},
        {"policy": "full_double_count_with_band_exclusivity", "recommended": False, "reason": "removes band duplication but still double counts crashes across signals/approaches"},
        {"policy": "nearest_single_unit_owner", "recommended": False, "reason": "total preserving but discards signal-centered overlap influence"},
        {"policy": "total_preserving_fractional_after_band_exclusivity", "recommended": True, "reason": "total preserving and keeps overlapping signal-centered influence explicit"},
        {"policy": "signal_first_fractional_weighting", "recommended": False, "reason": "conceptually useful, but equal fractional after exclusivity is simpler for first patch"},
    ])
    write_csv("recommended_crash_patch_fields.csv", [
        {"field": "crash_count_unweighted_candidate", "purpose": "raw accepted candidate assignment count per unit"},
        {"field": "crash_count_weighted", "purpose": "total-preserving fractional crash numerator"},
        {"field": "crash_assignment_count", "purpose": "candidate assignment rows per unit"},
        {"field": "crash_unique_count", "purpose": "unique crashes touching unit before weighting"},
        {"field": "crash_assignment_method", "purpose": "spatial 50 ft with within-group band exclusivity"},
        {"field": "crash_weighting_method", "purpose": "equal fractional per crash across accepted candidates"},
        {"field": "crash_weight_sum_status", "purpose": "per-crash weights sum to one QA status"},
        {"field": "crash_route_measure_support_status", "purpose": "route/measure QA overlay status"},
        {"field": "crash_ambiguity_flag", "purpose": "multiplicity or review flag"},
        {"field": "crash_nonadjacent_band_flag_count", "purpose": "non-adjacent band cases ledgered"},
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
    recon = pd.read_csv(OUT / "spatial_crash_candidate_reconstruction_summary.csv")
    metrics = dict(zip(recon["metric"], recon["value"]))
    zero = pd.read_csv(OUT / "zero_crash_signal_approach_unit_audit.csv")
    pol = pd.read_csv(OUT / "crash_policy_comparison_summary.csv")
    formula = pd.read_csv(OUT / "crash_weighting_formula_comparison.csv")
    rm = pd.read_csv(OUT / "route_measure_qa_overlay_summary.csv")
    text = f"""# Crash Assignment Weighting Policy Audit

Full double-counting is not appropriate for final crash numerators because crashes are event outcomes. A crash may be influenced by multiple signal-centered functional areas, but the accepted assignment weights should preserve the event total: per assigned crash, weights sum to 1.0.

Spatial candidates were reconstructed from staged bin geometry and source crash geometry at 50 ft. Unique assigned crashes: {metrics.get('unique_crashes_assigned')}; raw candidate pairs: {metrics.get('candidate_unit_pairs')}; max units per crash: {metrics.get('max_units_per_crash')}.

Within-group distance-band exclusivity is recommended before weighting. It removes same crash + signal + approach + direction multiband duplication while preserving the assigned crash universe.

## Zero-Crash Audit
{zero.to_string(index=False)}

## Policy Comparison
{pol.to_string(index=False)}

## Weighting Formulas
{formula.to_string(index=False)}

Recommended weighting formula: `equal_weight` after band exclusivity. It is transparent, total-preserving, and avoids overfitting proximity assumptions before map review. Inverse-distance and signal-first formulas are feasible sensitivity options.

Route/measure evidence remains QA support, not primary count evidence:
{rm.to_string(index=False)}

Crash direction-like fields were inventoried only; none were used for assignment, weighting, or upstream/downstream.

Next task should patch `distance_band_context.parquet` with weighted and diagnostic unweighted crash fields using spatial-primary fractional assignment after band exclusivity.

Final decision: `{decision}`
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started crash assignment weighting policy audit.\n", encoding="utf-8")
    parent_dependency_check()
    crashes, units, context, bins, signals = load_inputs()
    crash_points, bin_geom, sig_geom = prepare_geometry(crashes, units, context, bins, signals)
    raw_pair, _raw = reconstruct_candidates(crash_points, bin_geom, sig_geom)
    kept, dropped = apply_band_exclusivity(raw_pair)
    zero_crash_audit(context, raw_pair, kept)
    preferred_equal, nearest = policy_comparison(raw_pair, kept, context)
    kept_weighted = weighting_formula_comparison(kept)
    constraint_and_overlay_outputs(kept_weighted, raw_pair, kept)
    decision = scorecard_and_fields()
    guards()
    write_csv("readiness_decision.csv", [{"final_decision": decision, "patch_staged_context_in_this_task": False, "recommended_next_task": "Patch distance_band_context with spatial fractional crash assignment after band exclusivity"}])
    write_csv("recommended_next_actions.csv", [{"priority": 1, "recommended_next_action": "Implement spatial fractional crash assignment patch", "reason": "Total-preserving fractional policy after band exclusivity is recommended."}])
    findings(decision)
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.audit.crash_assignment_weighting_policy_audit", "build_version": BUILD_VERSION, "final_decision": decision, "read_only": True})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": decision, "read_only": True, "phase_timings": PHASE_TIMINGS, "outputs": sorted(p.name for p in OUT.glob("*"))})
    log(f"Completed read-only audit with final decision: {decision}.")


if __name__ == "__main__":
    main()
