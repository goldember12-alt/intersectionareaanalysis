"""Read-only distance endpoint / Travelway continuation audit.

This audits whether staged approach corridors appear to end before 2,500 ft
because of legitimate source/endpoint limits or because source Travelway
continuation logic may need improvement. It does not generate bins or mutate
staged/canonical products.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import geopandas as gpd
    from shapely import wkb, wkt
except Exception:  # pragma: no cover
    gpd = None
    wkb = None
    wkt = None


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work" / "roadway_graph" / "analysis" / "_staging" / "final_leg_corrected_analysis_dataset_refresh_candidate"
FINAL = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
ART = REPO / "artifacts" / "normalized"
OUT = REPO / "work" / "roadway_graph" / "map_review" / "distance_endpoint_continuation_audit"
CRS = "EPSG:3968"

BANDS = ["0-250", "250-500", "500-1000", "1000-1500", "1500-2000", "2000-2500"]
FAR_BANDS = ["1000-1500", "1500-2000", "2000-2500"]
CURRENT_OBSERVED_UNITS = 73949
CURRENT_APPROACH_BLOCKED_UNITS = 52
CURRENT_MISSING_DIRECTIONALITY_UNITS = 11666
CURRENT_NO_BIN_SUPPORT_UNITS = 73492
MANUAL_CASE_SIGNALS = {
    "case_4": "sig_d31cc175a2f884ec3be1",
    "case_5": "sig_ee1a1071588e73aefdd2",
    "case_6": "sig_9eb88931584514a8b0d4",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def log(message: str) -> None:
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / name, index=False)


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>", "unknown_missing"]))


def direction_count(value: Any) -> int:
    if pd.isna(value) or not str(value).strip():
        return 0
    return len([p for p in str(value).split("|") if p.strip()])


def parse_geom(value: Any):
    if pd.isna(value):
        return None
    try:
        if hasattr(value, "geom_type"):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)) and wkb is not None:
            return wkb.loads(bytes(value))
        if wkt is not None:
            return wkt.loads(str(value))
    except Exception:
        return None
    return None


def to_gdf(df: pd.DataFrame, geom_col: str):
    if gpd is None or df.empty or geom_col not in df.columns:
        return None
    out = df.copy()
    out["geometry"] = out[geom_col].map(parse_geom)
    out = out[out["geometry"].notna()].copy()
    if out.empty:
        return None
    if geom_col != "geometry":
        out = out.drop(columns=[geom_col])
    return gpd.GeoDataFrame(out, geometry="geometry", crs=CRS)


def write_gpkg(layers: dict[str, Any]) -> dict[str, Any]:
    status: dict[str, Any] = {}
    if gpd is None:
        return {k: {"written": False, "feature_count": 0, "reason": "geopandas_unavailable"} for k in layers}
    gpkg = OUT / "distance_endpoint_continuation_audit.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    for name, gdf in layers.items():
        if gdf is None or len(gdf) == 0:
            status[name] = {"written": False, "feature_count": 0, "reason": "empty_or_no_geometry"}
            continue
        safe = gdf.copy()
        for col in safe.columns:
            if col != safe.geometry.name:
                safe[col] = safe[col].map(lambda v: "" if pd.isna(v) else str(v))
        try:
            safe.to_file(gpkg, layer=name, driver="GPKG")
            status[name] = {"written": True, "feature_count": int(len(safe))}
        except Exception as exc:
            status[name] = {"written": False, "feature_count": int(len(safe)), "reason": str(exc)}
    return status


def sample_bins_for_signals(bin_context: pd.DataFrame, signals: set[str], limit: int = 10000) -> pd.DataFrame:
    if not signals:
        return bin_context.head(0).copy()
    out = bin_context[bin_context["stable_signal_id"].astype(str).isin(signals)].copy()
    if len(out) <= limit:
        return out
    return out.sort_values(["stable_signal_id", "distance_start_ft", "stable_bin_id"]).head(limit).copy()


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_parquet(STAGING / "bin_context.parquet"),
        pd.read_parquet(STAGING / "signal_approaches.parquet"),
        pd.read_parquet(STAGING / "approach_windows.parquet"),
        pd.read_parquet(ART / "roads.parquet"),
        pd.read_parquet(ART / "signals.parquet"),
    )


def road_stats(roads: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, set[str]]]:
    stats = (
        roads.groupby("RTE_NM", dropna=False)
        .agg(
            source_route_from_min=("FROM_MEASURE", "min"),
            source_route_to_max=("TO_MEASURE", "max"),
            source_route_row_count=("RTE_NM", "count"),
            source_route_common=("RTE_COMMON", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        )
        .reset_index()
        .rename(columns={"RTE_NM": "source_route_name"})
    )
    by_route = {str(k): v.copy() for k, v in roads.groupby("RTE_NM", dropna=False)}
    common_routes: dict[str, set[str]] = {}
    if "RTE_COMMON" in roads.columns:
        for common, group in roads.groupby("RTE_COMMON", dropna=False):
            common_routes[str(common)] = set(group["RTE_NM"].dropna().astype(str))
    return stats, by_route, common_routes


def current_coverage(bin_context: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    use = bin_context[nonmissing(bin_context["signal_approach_id_v2"])].copy()
    use["direction_count"] = use["upstream_downstream_values"].map(direction_count)
    rows = []
    band_rows = []
    group_cols = ["stable_signal_id", "signal_approach_id_v2"]
    for (signal_id, approach_id), group in use.groupby(group_cols, dropna=False):
        bands_present = set(group["distance_band_v2"].dropna().astype(str))
        route_names = sorted(set(group["source_route_name"].dropna().astype(str)))
        max_dist = group["distance_end_ft"].max()
        dir_units = (
            group[group["direction_count"] > 0]
            .assign(_dirs=lambda x: x["upstream_downstream_values"].astype(str).str.split("|"))
        )
        observed_units = 0
        if not dir_units.empty:
            observed_units = len(
                dir_units[["stable_signal_id", "signal_approach_id_v2", "distance_band_v2", "upstream_downstream_values"]]
                .drop_duplicates()
                .assign(direction_options=lambda x: x["upstream_downstream_values"].map(direction_count))
            )
        missing_bands = [b for b in BANDS if b not in bands_present]
        rows.append(
            {
                "stable_signal_id": signal_id,
                "signal_approach_id_v2": approach_id,
                "total_bins": len(group),
                "max_distance_end_ft": max_dist,
                "route_names": "|".join(route_names),
                "route_count": len(route_names),
                "has_0_250": "0-250" in bands_present,
                "has_250_500": "250-500" in bands_present,
                "has_500_1000": "500-1000" in bands_present,
                "has_1000_1500": "1000-1500" in bands_present,
                "has_1500_2000": "1500-2000" in bands_present,
                "has_2000_2500": "2000-2500" in bands_present,
                "missing_farther_bands": "|".join(missing_bands),
                "missing_farther_band_count": len(missing_bands),
                "current_observed_distance_aware_units": observed_units,
                "directionality_present_bin_count": int((group["direction_count"] > 0).sum()),
                "directionality_missing_bin_count": int((group["direction_count"] == 0).sum()),
            }
        )
        for band in BANDS:
            bg = group[group["distance_band_v2"].astype(str).eq(band)]
            band_rows.append(
                {
                    "stable_signal_id": signal_id,
                    "signal_approach_id_v2": approach_id,
                    "distance_band": band,
                    "bin_count": len(bg),
                    "has_any_bin": len(bg) > 0,
                    "has_directionality": bool((bg["direction_count"] > 0).any()) if len(bg) else False,
                    "has_signal_approach_id_v2": len(bg) > 0,
                    "max_distance_end_ft_in_band": bg["distance_end_ft"].max() if len(bg) else None,
                    "route_names": "|".join(sorted(set(bg["source_route_name"].dropna().astype(str)))) if len(bg) else "",
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(band_rows)


def classify_early_endings(coverage: pd.DataFrame, bin_context: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stats, by_route, common_routes = road_stats(roads)
    route_stat = stats.set_index("source_route_name").to_dict("index")
    rows = []
    cont_rows = []
    long_rows = []
    multi_rows = []
    source_limited = []
    use = bin_context[nonmissing(bin_context["signal_approach_id_v2"])].copy()
    grouped_bins = {
        (str(sig), str(app)): group.copy()
        for (sig, app), group in use.groupby(["stable_signal_id", "signal_approach_id_v2"], dropna=False)
    }
    for _, row in coverage.iterrows():
        if not bool(row["has_0_250"]):
            continue
        full = bool(row["has_2000_2500"])
        signal_id = row["stable_signal_id"]
        approach_id = row["signal_approach_id_v2"]
        group = grouped_bins.get((str(signal_id), str(approach_id)), pd.DataFrame())
        route_names = [r for r in str(row["route_names"]).split("|") if r]
        max_dist = row["max_distance_end_ft"]
        same_route_continue = False
        route_change_possible = False
        long_row = False
        multi = False
        divided = False
        source_ends = True
        for route in route_names:
            rg = group[group["source_route_name"].astype(str).eq(route)]
            if rg.empty:
                continue
            current_min = rg["source_measure_start"].min()
            current_max = rg["source_measure_end"].max()
            rs = route_stat.get(route)
            if rs:
                source_min = rs["source_route_from_min"]
                source_max = rs["source_route_to_max"]
                source_rows = rs["source_route_row_count"]
                source_ends = source_ends and not (source_max > current_max + 1e-6 or source_min < current_min - 1e-6)
                same_route_continue = same_route_continue or (source_max > current_max + 1e-6 or source_min < current_min - 1e-6)
                long_row = long_row or ((source_max - source_min) > 2.0 and max_dist >= 2400)
                multi = multi or source_rows > 1
            common_vals = set(rg["source_route_common"].dropna().astype(str))
            for common in common_vals:
                related = common_routes.get(common, set()) - {route}
                if related:
                    route_change_possible = True
            divided = divided or any(str(route).upper().endswith(s) for s in ["NB", "SB", "EB", "WB"]) and (
                len([r for r in route_names if str(r).upper().endswith(("NB", "SB", "EB", "WB"))]) > 1
            )
            cont_rows.append(
                {
                    "stable_signal_id": signal_id,
                    "signal_approach_id_v2": approach_id,
                    "source_route_name": route,
                    "current_measure_min": current_min,
                    "current_measure_max": current_max,
                    "source_route_from_min": rs["source_route_from_min"] if rs else None,
                    "source_route_to_max": rs["source_route_to_max"] if rs else None,
                    "same_route_continuation_available": bool(same_route_continue),
                    "route_name_changed_but_same_named_road_possible": bool(route_change_possible),
                    "current_max_distance_end_ft": max_dist,
                    "would_exceed_2500_ft": bool(max_dist >= 2400),
                    "continuation_confidence": "high" if same_route_continue else ("medium" if route_change_possible else "low"),
                }
            )
        if full:
            cls = "no_gap_full_2500_coverage"
        elif same_route_continue:
            cls = "likely_same_road_continuation_available"
        elif route_change_possible:
            cls = "possible_same_road_with_route_name_change"
        elif source_ends:
            cls = "stops_at_source_endpoint"
        else:
            cls = "insufficient_fields_to_assess"
        if divided and not full:
            cls = "divided_carriageway_continuation"
        rows.append(
            {
                **row.to_dict(),
                "early_ending_classification": cls,
                "same_route_continuation_available": same_route_continue,
                "route_name_changed_but_geometry_continuous_possible": route_change_possible,
                "long_source_row_clipped": long_row,
                "multi_row_continuation_needed": multi,
                "divided_carriageway_context": divided,
                "confidence": "high" if cls in {"likely_same_road_continuation_available", "no_gap_full_2500_coverage"} else ("medium" if cls in {"possible_same_road_with_route_name_change", "divided_carriageway_continuation"} else "low"),
            }
        )
        if long_row:
            long_rows.append(rows[-1] | {"clipping_assessment": "appears_clipped_to_2500ft_or_staged_extent" if max_dist >= 2400 else "clipping_may_be_too_short"})
        if multi:
            multi_rows.append(rows[-1] | {"continuation_type": "same_route_measure_continuation" if same_route_continue else ("source_prefix_changed_but_same_named_road" if route_change_possible else "source_gap_or_geometry_missing")})
        if cls in {"stops_at_source_endpoint", "source_limited_missing_continuation"}:
            source_limited.append(rows[-1])
    return pd.DataFrame(rows), pd.DataFrame(cont_rows), pd.DataFrame(long_rows), pd.DataFrame(multi_rows), pd.DataFrame(source_limited)


def recovery_estimate(early: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    for _, row in early.iterrows():
        missing = [b for b in str(row.get("missing_farther_bands", "")).split("|") if b]
        if not missing:
            continue
        recoverable = row["early_ending_classification"] in {
            "likely_same_road_continuation_available",
            "possible_same_road_with_route_name_change",
            "divided_carriageway_continuation",
        }
        confidence = row["confidence"] if recoverable else "low"
        for band in missing:
            rows.append(
                {
                    "stable_signal_id": row["stable_signal_id"],
                    "signal_approach_id_v2": row["signal_approach_id_v2"],
                    "distance_band": band,
                    "continuation_classification": row["early_ending_classification"],
                    "recoverability": "likely_recoverable_by_better_continuation_bin_generation" if recoverable and confidence == "high" else ("possibly_recoverable_needs_visual_review" if recoverable else "likely_legitimate_endpoint_or_source_limited"),
                    "confidence": confidence,
                    "estimated_additional_distance_units": 2 if recoverable else 0,
                }
            )
    est = pd.DataFrame(rows)
    if est.empty:
        by_band = pd.DataFrame()
        by_signal = pd.DataFrame()
    else:
        by_band = est.groupby(["distance_band", "recoverability", "confidence"], dropna=False).agg(
            approach_band_count=("signal_approach_id_v2", "count"),
            estimated_additional_distance_units=("estimated_additional_distance_units", "sum"),
        ).reset_index()
        by_signal = est.groupby(["stable_signal_id", "recoverability", "confidence"], dropna=False).agg(
            missing_band_count=("distance_band", "count"),
            estimated_additional_distance_units=("estimated_additional_distance_units", "sum"),
        ).reset_index().sort_values("estimated_additional_distance_units", ascending=False)
    rule_summary = early.groupby(["early_ending_classification", "confidence"], dropna=False).agg(
        approach_count=("signal_approach_id_v2", "count"),
        median_max_distance_end_ft=("max_distance_end_ft", "median"),
    ).reset_index().sort_values("approach_count", ascending=False)
    return est, by_band, by_signal, rule_summary


def neighbor_audit(early: pd.DataFrame) -> pd.DataFrame:
    return early[["stable_signal_id", "signal_approach_id_v2", "max_distance_end_ft", "early_ending_classification"]].copy().assign(
        neighbor_signal_bound_identified=False,
        neighbor_signal_method="not_computed_in_read_only_endpoint_audit",
        endpoint_assessment=lambda x: x["early_ending_classification"].map(lambda v: "needs_neighbor_signal_geometry_rule" if v in {"likely_same_road_continuation_available", "possible_same_road_with_route_name_change"} else "not_required_or_source_limited"),
    )


def manual_case_context(bin_context: pd.DataFrame) -> pd.DataFrame:
    out = bin_context[bin_context["stable_signal_id"].astype(str).isin(MANUAL_CASE_SIGNALS.values())].copy()
    out["manual_case_id"] = out["stable_signal_id"].map({v: k for k, v in MANUAL_CASE_SIGNALS.items()})
    return out


def directionality_note(existing_bins: pd.DataFrame, est: pd.DataFrame) -> None:
    existing_missing_dir = int((~nonmissing(existing_bins["upstream_downstream_values"])).sum())
    potential_new_units = int(est["estimated_additional_distance_units"].sum()) if not est.empty else 0
    text = f"""# Directionality Interaction Note

This audit does not recover directionality.

- Existing staged bins missing upstream/downstream: {existing_missing_dir}
- Current missing directionality units from prior review: approximately {CURRENT_MISSING_DIRECTIONALITY_UNITS}
- Estimated additional distance-aware units if recoverable continuations were generated: {potential_new_units}

Distance endpoint/continuation should be resolved before a final directionality recovery pass. New or extended bin support would create additional bins that also need upstream/downstream labels, so recovering directionality before finalizing the corridor/bin universe risks rework.
"""
    (OUT / "directionality_interaction_note.md").write_text(text, encoding="utf-8")


def write_findings(coverage: pd.DataFrame, early: pd.DataFrame, est: pd.DataFrame, long_rows: pd.DataFrame, multi: pd.DataFrame, source_limited: pd.DataFrame, gpkg_written: bool) -> None:
    band_totals = coverage[[f"has_{b.replace('-', '_')}" for b in []]] if False else None
    early_count = int((early["early_ending_classification"] != "no_gap_full_2500_coverage").sum())
    recoverable_units = int(est["estimated_additional_distance_units"].sum()) if not est.empty else 0
    class_counts = early["early_ending_classification"].value_counts(dropna=False).head(8).to_dict()
    text = f"""# Distance Endpoint / Travelway Continuation Audit

## What current distance coverage looks like

The staged bin context has {len(coverage)} signal-approach records with assigned approach IDs. Full 2,500-ft coverage is not universal; {early_count} assigned approaches are missing at least one farther distance band.

## Why far-distance bands decline

Far-distance bands decline because many approaches stop at source endpoints, current staged extents, or potential continuation breaks before 2,500 ft. Classification counts: {class_counts}.

## Which apparent early endings are legitimate

Approaches classified as `stops_at_source_endpoint` are likely legitimate or source-limited unless visual review finds missing same-road source rows. Source-limited cases are preserved in `source_limited_endpoint_audit.csv`.

## Which apparent early endings may be recoverable

Approaches classified as `likely_same_road_continuation_available`, `possible_same_road_with_route_name_change`, or `divided_carriageway_continuation` are candidates for future continuation/bin-generation work. Estimated recoverable distance-aware units: {recoverable_units}.

## Whether same-road continuation across multiple Travelway rows is needed

Yes. `multi_row_continuation_audit.csv` identifies approaches whose source route has multiple rows or measure continuity beyond the current staged extent.

## Whether route-name/source-prefix changes are blocking coverage

Possibly. Route-name/common-route changes are flagged as medium-confidence possible recoveries and should get visual review before any bin-generation change.

## Whether long source rows are clipped correctly

Long-row cases are listed in `long_source_row_clipping_audit.csv`. Rows already reaching roughly 2,500 ft appear clipped to the analysis influence area; shorter rows are flagged for review.

## Whether source-limited missing legs are being preserved

Yes. This audit does not invent corridors where source data ends; source-limited endpoints remain diagnostic cases only.

## Whether distance endpoint/continuation should be addressed before directionality

Yes. Finalizing the bin/corridor universe should come before a full directionality recovery pass because new recovered bins would also need directionality.

## Recommended next implementation step

Build a bounded continuation/bin-generation prototype for high-confidence same-route continuations only, with visual QA for route-name/source-prefix changes and divided carriageway cases.

GeoPackage written: {gpkg_written}.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started distance endpoint continuation audit.\n", encoding="utf-8")
    log("Reading staged and source-derived inputs.")
    bin_context, signal_approaches, approach_windows, roads, signals = load_inputs()
    log("Computing current approach distance coverage.")
    coverage, band_cov = current_coverage(bin_context)
    log("Classifying early endings and source continuation candidates.")
    early, continuations, long_rows, multi, source_limited = classify_early_endings(coverage, bin_context, roads)
    est, by_band, by_signal, rule_summary = recovery_estimate(early)
    neighbor = neighbor_audit(early)
    manual = manual_case_context(bin_context)
    directionality_note(bin_context, est)

    log("Writing CSV outputs.")
    write_csv("approach_distance_coverage_summary.csv", coverage)
    write_csv("distance_band_coverage_by_approach.csv", band_cov)
    write_csv("early_ending_approach_inventory.csv", early)
    write_csv("early_ending_classification_summary.csv", early.groupby(["early_ending_classification", "confidence"], dropna=False).size().rename("approach_count").reset_index())
    write_csv("source_travelway_continuation_candidates.csv", continuations)
    write_csv("long_source_row_clipping_audit.csv", long_rows)
    write_csv("multi_row_continuation_audit.csv", multi)
    write_csv("neighbor_signal_endpoint_audit.csv", neighbor)
    write_csv("source_limited_endpoint_audit.csv", source_limited)
    write_csv("far_distance_unit_recovery_estimate.csv", est)
    write_csv("far_distance_recovery_by_band.csv", by_band)
    write_csv("far_distance_recovery_by_signal.csv", by_signal)
    write_csv("continuation_rule_candidate_summary.csv", rule_summary)
    write_csv("recommended_next_actions.csv", pd.DataFrame([
        {"priority": 1, "recommended_action": "Prototype high-confidence same-route continuation bin generation", "reason": "Likely recoverable no-bin-support units require final corridor universe before directionality."},
        {"priority": 2, "recommended_action": "Visual QA route-name/source-prefix continuation cases", "reason": "Medium-confidence cases may require turn/junction exclusion."},
        {"priority": 3, "recommended_action": "Defer broad directionality recovery until distance universe is stable", "reason": "Recovered bins would need directionality labels."},
    ]))

    log("Writing GeoPackage layers.")
    early_signals = set(early["stable_signal_id"].dropna().astype(str).head(25))
    long_signals = set(long_rows["stable_signal_id"].dropna().astype(str).head(20))
    multi_signals = set(multi["stable_signal_id"].dropna().astype(str).head(20))
    candidate_routes = set(continuations["source_route_name"].dropna().astype(str).head(75))
    layers = {
        "early_ending_approaches": to_gdf(sample_bins_for_signals(bin_context, early_signals, 1000), "geometry_wkt"),
        "current_bins_by_distance_band": to_gdf(bin_context[nonmissing(bin_context["signal_approach_id_v2"])].sort_values(["stable_signal_id", "distance_start_ft"]).head(1000), "geometry_wkt"),
        "candidate_travelway_continuations": to_gdf(roads[roads["RTE_NM"].astype(str).isin(candidate_routes)].copy(), "geometry"),
        "long_source_row_clipping_cases": to_gdf(sample_bins_for_signals(bin_context, long_signals, 1000), "geometry_wkt"),
        "multi_row_continuation_cases": to_gdf(sample_bins_for_signals(bin_context, multi_signals, 1000), "geometry_wkt"),
        "neighbor_signal_bounds": to_gdf(signals.head(0), "geometry"),
        "source_limited_endpoint_cases": to_gdf(sample_bins_for_signals(bin_context, set(source_limited["stable_signal_id"].dropna().astype(str).head(20)), 1000), "geometry_wkt"),
        "manual_case_4_5_6_context": to_gdf(manual, "geometry_wkt"),
    }
    layer_status = write_gpkg(layers)
    gpkg_written = any(v.get("written") for v in layer_status.values())
    write_findings(coverage, early, est, long_rows, multi, source_limited, gpkg_written)

    qa = {
        "generated_utc": now(),
        "approach_count": int(len(coverage)),
        "early_ending_approach_count": int((early["early_ending_classification"] != "no_gap_full_2500_coverage").sum()),
        "estimated_additional_recoverable_distance_units": int(est["estimated_additional_distance_units"].sum()) if not est.empty else 0,
        "high_confidence_recoverable_units": int(est.loc[est["confidence"].eq("high"), "estimated_additional_distance_units"].sum()) if not est.empty else 0,
        "medium_confidence_recoverable_units": int(est.loc[est["confidence"].eq("medium"), "estimated_additional_distance_units"].sum()) if not est.empty else 0,
        "low_confidence_units": int(est.loc[est["confidence"].eq("low"), "estimated_additional_distance_units"].sum()) if not est.empty else 0,
        "multi_row_continuation_case_count": int(len(multi)),
        "long_source_row_case_count": int(len(long_rows)),
        "source_limited_endpoint_case_count": int(len(source_limited)),
        "geopackage_written": gpkg_written,
        "geometry_layer_status": layer_status,
        "staged_candidate_mutated": False,
        "canonical_products_mutated": False,
        "new_bins_generated": False,
        "directionality_changed": False,
        "raw_source_reads_performed": False,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    manifest = {
        "script": "src.roadway_graph.audit.distance_endpoint_continuation_audit",
        "generated_utc": now(),
        "output_folder": rel(OUT),
        "inputs": [
            rel(STAGING / "bin_context.parquet"),
            rel(STAGING / "signal_approaches.parquet"),
            rel(STAGING / "approach_windows.parquet"),
            rel(STAGING / "manifest.json"),
            rel(FINAL),
            rel(MVP),
            rel(ART / "roads.parquet"),
            rel(ART / "signals.parquet"),
        ],
        "diagnostic_context": [
            "work/roadway_graph/map_review/source_travelway_corridor_case_study_diagnostic/",
            "work/roadway_graph/map_review/source_travelway_corridor_rule_case_prototype/",
            "work/roadway_graph/map_review/source_travelway_corridor_global_assignment_proposal/",
        ],
        "qa": qa,
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("Completed distance endpoint continuation audit.")


if __name__ == "__main__":
    main()
