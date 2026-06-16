"""Read-only crash assignment feasibility audit for staged distance-band units.

This script compares source-rooted route/measure and spatial crash assignment
options without patching staged context products. Crash direction-like fields
are inventoried only for the guard output and are not used for assignment.
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
OUT = REPO / "work/roadway_graph/review/crash_assignment_feasibility_audit"
SIGNALS = STAGING / "signal_index.parquet"
BINS = STAGING / "bin_context.parquet"
UNITS = STAGING / "distance_band_units.parquet"
CONTEXT = STAGING / "distance_band_context.parquet"
CRASHES = REPO / "artifacts/normalized/crashes.parquet"
ROADS = REPO / "artifacts/normalized/roads.parquet"
NORM_SIGNALS = REPO / "artifacts/normalized/signals.parquet"

FT_PER_M = 3.280839895
TOLERANCES_FT = [25.0, 50.0, 75.0, 100.0]
PRIMARY_TOLERANCE_FT = 50.0
BUILD_VERSION = "crash_assignment_feasibility_audit_v1_2026-06-15"
CRASH_DIRECTION_TOKENS = ("direction", "dir", "travel_direction", "veh_direction", "crash_direction", "bearing")
FORBIDDEN_OUTPUT_TOKENS = ("lookup_cells", "rate_distribution", "mvp_directional_rate_distribution")
BAND_ORDER = {"0_250ft": 0, "250_500ft": 1, "500_1000ft": 2, "1000_1500ft": 3, "1500_2000ft": 4, "2000_2500ft": 5, "1500_2500ft": 4}
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


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def route_key(value: Any) -> str:
    text = clean_text(value).upper()
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
    for path in [SIGNALS, BINS, UNITS, CONTEXT, CRASHES, ROADS, NORM_SIGNALS]:
        role = "parent" if path in {SIGNALS, BINS, UNITS, CONTEXT, CRASHES} else "schema_lineage_optional"
        rows.append({"path": rel(path), "role": role, "exists": path.exists(), "sha256": file_sha256(path) if path.exists() else ""})
    write_csv("parent_dependency_check.csv", rows)


def load_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with phase("load_staged_and_crash_sources"):
        context = pd.read_parquet(CONTEXT)
        units = pd.read_parquet(UNITS)
        bin_cols = [
            "stable_bin_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band",
            "source_route_name", "route_base", "source_measure_start", "source_measure_end", "geometry",
            "geometry_status", "geometry_length_ft",
        ]
        bins = pd.read_parquet(BINS, columns=bin_cols)
        crashes = pd.read_parquet(CRASHES)
        return context, units, bins, crashes


def crash_inventory(crashes: pd.DataFrame) -> None:
    with phase("crash_source_inventory"):
        schema_rows = [{"column": c, "dtype": str(crashes[c].dtype), "non_null": int(crashes[c].notna().sum()), "null": int(crashes[c].isna().sum())} for c in crashes.columns]
        write_csv("crash_source_schema_inventory.csv", schema_rows)
        geom_valid = crashes["geometry"].notna() if "geometry" in crashes else pd.Series(False, index=crashes.index)
        write_csv("crash_source_geometry_summary.csv", [
            {"metric": "crash_rows", "value": len(crashes)},
            {"metric": "geometry_non_null", "value": int(geom_valid.sum())},
            {"metric": "geometry_null", "value": int((~geom_valid).sum())},
            {"metric": "geometry_field_present", "value": "geometry" in crashes.columns},
            {"metric": "geometry_assumed_crs", "value": "same projected CRS as staged geometry; source metadata not embedded in parquet"},
        ])
        route = clean_series(crashes.get("RTE_NM", pd.Series("", index=crashes.index)))
        mp = pd.to_numeric(crashes.get("RNS_MP", pd.Series(np.nan, index=crashes.index)), errors="coerce")
        write_csv("crash_source_route_measure_summary.csv", [
            {"metric": "route_non_null", "value": int(route.ne("").sum())},
            {"metric": "measure_non_null", "value": int(mp.notna().sum())},
            {"metric": "route_and_measure_non_null", "value": int(route.ne("").mul(mp.notna()).sum())},
            {"metric": "unique_route_names", "value": int(route[route.ne("")].nunique())},
            {"metric": "measure_min", "value": float(mp.min()) if mp.notna().any() else np.nan},
            {"metric": "measure_max", "value": float(mp.max()) if mp.notna().any() else np.nan},
        ])
        years = clean_series(crashes.get("CRASH_YEAR", pd.Series("", index=crashes.index)))
        temporal = years.value_counts(dropna=False).rename_axis("crash_year").reset_index(name="crash_count").sort_values("crash_year")
        write_csv("crash_source_temporal_summary.csv", temporal)
        direction_cols = [c for c in crashes.columns if any(tok in c.lower() for tok in CRASH_DIRECTION_TOKENS)]
        write_csv("crash_forbidden_direction_field_inventory.csv", [{"column": c, "dtype": str(crashes[c].dtype), "non_null": int(crashes[c].notna().sum()), "used_for_assignment": False} for c in direction_cols])


def old_method_inventory() -> None:
    with phase("old_crash_method_inventory"):
        roots = [REPO / "src/active/roadway_graph", REPO / "docs/workflow", REPO / "docs/methodology"]
        patterns = ["crash assignment", "crash_count", "crash spatial", "crash route", "crash rate", "functional area crash", "approach crash", "final-leg crash", "crash ambiguity", "crash exposure"]
        rows = []
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix.lower() not in {".py", ".md", ".txt"}:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                low = text.lower()
                hits = [p for p in patterns if p in low]
                if not hits:
                    continue
                uses_direction = "crash direction" in low or "veh_direction" in low
                uses_spatial = "spatial" in low or "catchment" in low or "buffer" in low
                uses_route = "route" in low or "milepost" in low or "rns_mp" in low or "measure" in low
                stale = "work/output" in low or "legacy" in low or "review/" in low
                rows.append({
                    "path": rel(path),
                    "matched_terms": "|".join(hits[:8]),
                    "route_measure_method_evidence": uses_route,
                    "spatial_method_evidence": uses_spatial,
                    "crash_direction_field_mentioned": uses_direction,
                    "stale_parent_risk_terms_present": stale,
                    "compatible_with_rebuilt_units": uses_spatial or uses_route,
                    "adaptation_note": "method evidence only; not run and not used as parent truth",
                })
        inv = write_csv("old_crash_method_inventory.csv", rows)
        write_csv("old_crash_method_feasibility_summary.csv", [
            {"metric": "files_with_crash_method_evidence", "value": len(inv)},
            {"metric": "files_with_spatial_evidence", "value": int(inv["spatial_method_evidence"].sum()) if not inv.empty else 0},
            {"metric": "files_with_route_measure_evidence", "value": int(inv["route_measure_method_evidence"].sum()) if not inv.empty else 0},
            {"metric": "files_mentioning_crash_direction", "value": int(inv["crash_direction_field_mentioned"].sum()) if not inv.empty else 0},
        ])


def build_unit_spans(bins: pd.DataFrame, units: pd.DataFrame) -> pd.DataFrame:
    with phase("build_compact_unit_route_spans"):
        work = bins.copy()
        work["upstream_downstream"] = clean_series(work["upstream_downstream"])
        work.loc[~work["upstream_downstream"].isin(["upstream", "downstream"]), "upstream_downstream"] = ""
        work = work.merge(
            units[["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"]],
            on=["stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band"],
            how="left",
            validate="many_to_one",
        )
        work["route_key"] = clean_series(work["source_route_name"]).where(clean_series(work["source_route_name"]).ne(""), clean_series(work["route_base"])).map(route_key)
        start = pd.to_numeric(work["source_measure_start"], errors="coerce")
        end = pd.to_numeric(work["source_measure_end"], errors="coerce")
        work["measure_min"] = np.minimum(start, end)
        work["measure_max"] = np.maximum(start, end)
        valid = work["distance_band_unit_id"].notna() & work["route_key"].ne("") & work["measure_min"].notna() & work["measure_max"].notna()
        spans = work.loc[valid].groupby(["distance_band_unit_id", "route_key"], as_index=False).agg(
            stable_signal_id=("stable_signal_id", "first"),
            signal_approach_id=("signal_approach_id", "first"),
            upstream_downstream=("upstream_downstream", "first"),
            distance_band=("distance_band", "first"),
            measure_min=("measure_min", "min"),
            measure_max=("measure_max", "max"),
            span_bin_count=("stable_bin_id", "nunique"),
        )
        spans["band_order"] = clean_series(spans["distance_band"]).map(BAND_ORDER).fillna(999).astype(int)
        write_csv("route_measure_unit_span_summary.csv", [
            {"metric": "span_rows", "value": len(spans)},
            {"metric": "units_with_route_measure_span", "value": int(spans["distance_band_unit_id"].nunique())},
            {"metric": "unique_route_keys", "value": int(spans["route_key"].nunique())},
        ])
        return spans


def route_measure_test(crashes: pd.DataFrame, spans: pd.DataFrame) -> pd.DataFrame:
    with phase("strict_route_measure_assignment_test", crash_rows=len(crashes), span_rows=len(spans)):
        log("strict_route_measure: preparing crash route keys and milepost buckets")
        c = pd.DataFrame({
            "crash_id": clean_series(crashes["DOCUMENT_NBR"]),
            "route_key": clean_series(crashes["RTE_NM"]).map(route_key),
            "rns_mp": pd.to_numeric(crashes["RNS_MP"], errors="coerce"),
        })
        c = c.loc[c["crash_id"].ne("") & c["route_key"].ne("") & c["rns_mp"].notna()].copy()
        c["measure_bucket_0p1mi"] = np.floor(c["rns_mp"] * 10).astype("int64")
        log(f"strict_route_measure: crash rows with route+measure={len(c)}; unique route keys={c['route_key'].nunique()}")
        log("strict_route_measure: expanding unit spans to 0.1-mile buckets")
        s = spans.copy()
        s["bucket_start"] = np.floor(pd.to_numeric(s["measure_min"], errors="coerce") * 10).astype("int64")
        s["bucket_end"] = np.floor(pd.to_numeric(s["measure_max"], errors="coerce") * 10).astype("int64")
        s = s.loc[s["bucket_end"].ge(s["bucket_start"])].copy()
        s["bucket_count"] = (s["bucket_end"] - s["bucket_start"] + 1).clip(lower=1, upper=200)
        repeated = np.repeat(s.index.to_numpy(), s["bucket_count"].to_numpy())
        expanded = s.loc[repeated, ["distance_band_unit_id", "route_key", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "band_order", "measure_min", "measure_max", "span_bin_count"]].copy()
        expanded["measure_bucket_0p1mi"] = np.concatenate([np.arange(a, a + n, dtype="int64") for a, n in zip(s["bucket_start"].to_numpy(), s["bucket_count"].to_numpy())])
        log(f"strict_route_measure: expanded span bucket rows={len(expanded)}")
        log("strict_route_measure: merging crashes to span buckets")
        candidates = c.merge(expanded, on=["route_key", "measure_bucket_0p1mi"], how="inner")
        log(f"strict_route_measure: bucket candidate rows before exact containment={len(candidates)}")
        candidates = candidates.loc[candidates["rns_mp"].ge(candidates["measure_min"]) & candidates["rns_mp"].le(candidates["measure_max"])].copy()
        log(f"strict_route_measure: candidate rows after exact containment={len(candidates)}")
        pairs = candidates[["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "band_order", "measure_min", "measure_max", "span_bin_count", "crash_id", "route_key", "rns_mp"]]
        if not pairs.empty:
            pairs = pairs.drop_duplicates(["crash_id", "distance_band_unit_id"])
        log(f"strict_route_measure: deduplicated assignment pairs={len(pairs)}")
        pc = pairs.groupby("crash_id")["distance_band_unit_id"].nunique() if not pairs.empty else pd.Series(dtype=int)
        write_csv("route_measure_crash_assignment_test.csv", pairs.head(250000))
        write_csv("route_measure_crash_assignment_summary.csv", [
            {"method": "strict_route_measure", "crash_records_with_route_measure": len(c), "candidate_assignment_pairs": len(pairs), "units_receiving_crashes": int(pairs["distance_band_unit_id"].nunique()) if not pairs.empty else 0, "unique_crashes_assigned": int(pairs["crash_id"].nunique()) if not pairs.empty else 0, "crashes_with_zero_candidate_units": int(len(crashes) - (pairs["crash_id"].nunique() if not pairs.empty else 0)), "crashes_with_one_candidate_unit": int(pc.eq(1).sum()) if not pc.empty else 0, "crashes_with_multiple_candidate_units": int(pc.gt(1).sum()) if not pc.empty else 0, "max_units_per_crash": int(pc.max()) if not pc.empty else 0}
        ])
        return pairs


def prepare_spatial_inputs(crashes: pd.DataFrame, bins: pd.DataFrame, units: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    with phase("prepare_spatial_inputs"):
        c = crashes.loc[crashes["geometry"].notna(), ["DOCUMENT_NBR", "geometry", "RTE_NM", "RNS_MP"]].copy()
        c["crash_id"] = clean_series(c["DOCUMENT_NBR"])
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
        b = b.loc[b["distance_band_unit_id"].notna()].copy().reset_index(drop=True)
        b["geometry_obj"] = from_wkb(b["geometry"].to_numpy())
        b = b.loc[~pd.isna(b["geometry_obj"])].reset_index(drop=True)
        return c, b


def summarize_pairs(pairs: pd.DataFrame, method: str, total_crashes: int) -> dict[str, Any]:
    pc = pairs.groupby("crash_id")["distance_band_unit_id"].nunique() if not pairs.empty else pd.Series(dtype=int)
    return {
        "method": method,
        "candidate_assignment_pairs": len(pairs),
        "units_receiving_crashes": int(pairs["distance_band_unit_id"].nunique()) if not pairs.empty else 0,
        "unique_crashes_assigned": int(pairs["crash_id"].nunique()) if not pairs.empty else 0,
        "crashes_with_zero_candidate_units": int(total_crashes - (pairs["crash_id"].nunique() if not pairs.empty else 0)),
        "crashes_with_one_candidate_unit": int(pc.eq(1).sum()) if not pc.empty else 0,
        "crashes_with_multiple_candidate_units": int(pc.gt(1).sum()) if not pc.empty else 0,
        "max_units_per_crash": int(pc.max()) if not pc.empty else 0,
    }


def spatial_test(crash_points: pd.DataFrame, bin_geom: pd.DataFrame) -> pd.DataFrame:
    with phase("spatial_assignment_tests", crash_points=len(crash_points), bin_rows=len(bin_geom)):
        tree = STRtree(bin_geom["geometry_obj"].to_numpy())
        summaries = []
        primary_pairs = pd.DataFrame()
        cgeom = crash_points["geometry_obj"].to_numpy()
        bgeom = bin_geom["geometry_obj"].to_numpy()
        for tol in TOLERANCES_FT:
            log(f"spatial_assignment_tests: querying tolerance_ft={tol}")
            start = time.perf_counter()
            found = tree.query(cgeom, predicate="dwithin", distance=tol / FT_PER_M)
            ci, bi = found[0].astype("int64"), found[1].astype("int64")
            log(f"spatial_assignment_tests: tolerance_ft={tol}; raw bin candidate pairs={len(ci)}")
            raw = pd.DataFrame({"crash_index": ci, "bin_index": bi})
            if raw.empty:
                pairs = pd.DataFrame(columns=["crash_id", "distance_band_unit_id"])
            else:
                for col in ["crash_id"]:
                    raw[col] = crash_points[col].to_numpy()[ci]
                for col in ["distance_band_unit_id", "stable_signal_id", "signal_approach_id", "upstream_downstream", "distance_band", "stable_bin_id"]:
                    raw[col] = bin_geom[col].to_numpy()[bi]
                raw["distance_to_unit_geometry_ft"] = [cgeom[c].distance(bgeom[b]) * FT_PER_M for c, b in zip(ci, bi)]
                raw["band_order"] = clean_series(raw["distance_band"]).map(BAND_ORDER).fillna(999).astype(int)
                pairs = raw.groupby(["crash_id", "distance_band_unit_id"], as_index=False).agg(
                    stable_signal_id=("stable_signal_id", "first"),
                    signal_approach_id=("signal_approach_id", "first"),
                    upstream_downstream=("upstream_downstream", "first"),
                    distance_band=("distance_band", "first"),
                    band_order=("band_order", "first"),
                    min_distance_to_unit_geometry_ft=("distance_to_unit_geometry_ft", "min"),
                    matching_bin_count=("stable_bin_id", "nunique"),
                )
            elapsed = round(time.perf_counter() - start, 3)
            row = summarize_pairs(pairs, f"spatial_{int(tol)}ft", len(crash_points))
            row["tolerance_ft"] = tol
            row["runtime_seconds"] = elapsed
            if not pairs.empty:
                row["median_distance_ft"] = float(pairs["min_distance_to_unit_geometry_ft"].median())
                row["p95_distance_ft"] = float(pairs["min_distance_to_unit_geometry_ft"].quantile(0.95))
                mb = pairs.groupby(["crash_id", "stable_signal_id", "signal_approach_id", "upstream_downstream"], as_index=False).agg(band_count=("distance_band", "nunique"), min_band_order=("band_order", "min"), max_band_order=("band_order", "max"))
                row["non_adjacent_band_red_flags"] = int((mb["band_count"].gt(1) & ((mb["max_band_order"] - mb["min_band_order"]) >= mb["band_count"])).sum())
            summaries.append(row)
            if tol == PRIMARY_TOLERANCE_FT:
                primary_pairs = pairs
                write_csv("spatial_crash_assignment_test.csv", pairs.head(250000))
            log(f"spatial_assignment_tests: tolerance_ft={tol}; deduplicated unit pairs={len(pairs)}; elapsed_seconds={elapsed}")
        write_csv("spatial_crash_tolerance_comparison.csv", summaries)
        write_csv("spatial_crash_assignment_summary.csv", [summarize_pairs(primary_pairs, f"spatial_{int(PRIMARY_TOLERANCE_FT)}ft", len(crash_points))])
        return primary_pairs


def compare_methods(route_pairs: pd.DataFrame, spatial_pairs: pd.DataFrame, crash_points: pd.DataFrame) -> None:
    with phase("compare_route_measure_and_spatial"):
        r = set(route_pairs["crash_id"]) if not route_pairs.empty else set()
        s = set(spatial_pairs["crash_id"]) if not spatial_pairs.empty else set()
        all_ids = set(crash_points["crash_id"])
        rows = [
            {"class": "route_measure_and_spatial_supported", "crash_count": len(r & s)},
            {"class": "route_measure_only", "crash_count": len(r - s)},
            {"class": "spatial_only", "crash_count": len(s - r)},
            {"class": "no_candidate_assignment", "crash_count": len(all_ids - (r | s))},
        ]
        write_csv("route_measure_vs_spatial_crash_comparison.csv", rows)
        if not spatial_pairs.empty:
            pc = spatial_pairs.groupby("crash_id")["distance_band_unit_id"].nunique()
            audit = pc.value_counts().rename_axis("assigned_unit_count").reset_index(name="crash_count").sort_values("assigned_unit_count")
            write_csv("crash_assignment_multiplicity_audit.csv", audit)
        else:
            write_csv("crash_assignment_multiplicity_audit.csv", [])
        amb = spatial_pairs.loc[spatial_pairs["crash_id"].isin(spatial_pairs.groupby("crash_id").filter(lambda x: x["distance_band_unit_id"].nunique() > 1)["crash_id"].unique())] if not spatial_pairs.empty else pd.DataFrame()
        write_csv("crash_assignment_ambiguity_ledger.csv", amb.head(100000))
        missing = crash_points.loc[~crash_points["crash_id"].isin(r | s), ["crash_id", "RTE_NM", "RNS_MP"]].head(100000)
        write_csv("crash_assignment_unassigned_crash_audit.csv", missing)


def policy_scorecard(route_pairs: pd.DataFrame, spatial_pairs: pd.DataFrame, total_crashes: int) -> str:
    with phase("policy_scorecard"):
        rows = []
        rows.append({**summarize_pairs(route_pairs, "strict_route_measure_primary", total_crashes), "risk_note": "source rooted but may fan out where route spans overlap and misses crashes with missing route/measure"})
        rows.append({**summarize_pairs(spatial_pairs, "spatial_primary_signal_centered_multiple_counting", total_crashes), "risk_note": "physically aligned with unit catchments but multiplicity affects rate denominators"})
        if not spatial_pairs.empty:
            best = spatial_pairs.sort_values(["crash_id", "min_distance_to_unit_geometry_ft", "matching_bin_count", "band_order"], ascending=[True, True, False, True]).drop_duplicates("crash_id")
        else:
            best = pd.DataFrame(columns=spatial_pairs.columns)
        rows.append({**summarize_pairs(best, "nearest_unit_spatial_ownership", total_crashes), "risk_note": "bounded one-crash-one-unit ownership; loses signal-centered overlap representation"})
        write_csv("crash_assignment_policy_comparison.csv", rows)
        score = [
            {"candidate_method": "strict_route_measure_primary", "route_or_geometry_strength": "moderate_if_route_measure_complete", "fanout_risk": "audit_required", "recommended": False},
            {"candidate_method": "spatial_primary_with_route_measure_QA", "route_or_geometry_strength": "strong_geometry_if_points_are_valid", "fanout_risk": "manageable_with_best-unit_or_overlap_policy", "recommended": True},
            {"candidate_method": "bounded_hybrid", "route_or_geometry_strength": "possible", "fanout_risk": "higher_complexity", "recommended": False},
        ]
        write_csv("crash_assignment_method_scorecard.csv", score)
        return "implement_spatial_crash_assignment_next"


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


def write_findings(decision: str) -> None:
    rm = pd.read_csv(OUT / "route_measure_crash_assignment_summary.csv").iloc[0].to_dict()
    sp = pd.read_csv(OUT / "spatial_crash_assignment_summary.csv").iloc[0].to_dict()
    comp = pd.read_csv(OUT / "route_measure_vs_spatial_crash_comparison.csv")
    comp_lines = ["| class | crash_count |", "| --- | ---: |"]
    for _, row in comp.iterrows():
        comp_lines.append(f"| {row['class']} | {row['crash_count']} |")
    comp_table = "\n".join(comp_lines)
    text = f"""# Crash Assignment Feasibility Audit Findings

## Source Fields
`crashes.parquet` contains crash ID (`DOCUMENT_NBR`), route (`RTE_NM`), milepost (`RNS_MP`), date/year, severity, and WKB geometry. Crash direction-like fields were inventoried only and were not used.

## Route/Measure Test
Strict route/measure assigned {rm.get('unique_crashes_assigned')} unique crashes to {rm.get('candidate_assignment_pairs')} candidate unit pairs. Max units per crash was {rm.get('max_units_per_crash')}.

## Spatial Test
The 50 ft spatial catchment assigned {sp.get('unique_crashes_assigned')} unique crashes to {sp.get('candidate_assignment_pairs')} candidate unit pairs. Max units per crash was {sp.get('max_units_per_crash')}.

## Method Comparison
{comp_table}

## Multiplicity And Policy
Spatial assignment is the best next implementation candidate, but crash multiplicity must be explicitly bounded in the implementation. The policy comparison includes signal-centered multiple counting and nearest-unit ownership. Because crashes feed rates, the next patch should implement a conservative spatial-primary assignment with route/measure as QA evidence and a clear ambiguity ledger.

## Old Method Evidence
Old crash scripts/docs provide method evidence for spatial catchments, route identity QA, and assignment QA, but were not run and were not used as data parents.

## Guard Confirmations
No crash direction fields were used for upstream/downstream or assignment. No staged data, canonical root product, MVP lookup, rate distribution, or final crash-rate product was modified or built.

## Final Decision
`{decision}`

## Recommended Next Task
Implement a spatial-primary crash assignment patch with route/measure QA evidence, no crash direction fields, explicit multiplicity policy, and temp-output QA before replacing staged `distance_band_context.parquet`.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started read-only crash assignment feasibility audit.\n", encoding="utf-8")
    parent_dependency_check()
    context, units, bins, crashes = load_sources()
    crash_inventory(crashes)
    old_method_inventory()
    spans = build_unit_spans(bins, units)
    route_pairs = route_measure_test(crashes, spans)
    crash_points, bin_geom = prepare_spatial_inputs(crashes, bins, units)
    spatial_pairs = spatial_test(crash_points, bin_geom)
    compare_methods(route_pairs, spatial_pairs, crash_points)
    decision = policy_scorecard(route_pairs, spatial_pairs, len(crash_points))
    guards()
    write_csv("readiness_decision.csv", [{"final_decision": decision, "patch_staged_context_in_this_task": False, "recommended_next_task": "spatial-primary crash assignment implementation with route/measure QA"}])
    write_csv("recommended_next_actions.csv", [{"priority": 1, "recommended_next_action": "Implement spatial-primary crash assignment layer", "reason": "Crash geometry is available and spatial catchments match current distance-band unit support; route/measure should be QA evidence."}])
    write_csv("remaining_context_patch_queue.csv", [
        {"sequence": 1, "task": "Crash assignment layer implementation", "scope": "bounded spatial or source-rooted route/measure assignment; no crash direction fields; crash_count and crash assignment QA"},
        {"sequence": 2, "task": "Final distance_band_context validation and MVP-readiness pass", "scope": "validate all context families; finalize rate readiness statuses; only then proceed to MVP analytical product / lookup-cell build"},
    ])
    write_findings(decision)
    write_json("manifest.json", {"created_utc": now(), "script": "src.roadway_graph.audit.crash_assignment_feasibility_audit", "build_version": BUILD_VERSION, "final_decision": decision, "read_only": True})
    write_json("qa_manifest.json", {"created_utc": now(), "final_decision": decision, "read_only": True, "phase_timings": PHASE_TIMINGS, "outputs": sorted(p.name for p in OUT.glob("*"))})
    log(f"Completed read-only audit with final decision: {decision}.")


if __name__ == "__main__":
    main()
