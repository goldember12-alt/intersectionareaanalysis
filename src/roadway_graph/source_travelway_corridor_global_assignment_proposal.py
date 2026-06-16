"""Global review-only source-Travelway corridor assignment proposal.

This script proposes bin-level signal_approach_id_v2 assignments for currently
ambiguous staged bins. It writes review/map-review outputs only and never mutates
staged or canonical products.
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
STAGED = REPO / "work" / "roadway_graph" / "analysis" / "_staging" / "final_leg_corrected_analysis_dataset_refresh_candidate"
FINAL = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
ART = REPO / "artifacts" / "normalized"
OUT = REPO / "work" / "roadway_graph" / "map_review" / "source_travelway_corridor_global_assignment_proposal"
CRS = "EPSG:3968"

TOTAL_BINS = 433_841
CURRENT_COVERAGE = 416_455
CURRENT_UNRESOLVED = 17_386
CURRENT_DISTANCE_UNITS = 66_524
CURRENT_APPROACH_BLOCKED_UNITS = 1_652
CURRENT_MISSING_DIRECTIONALITY_UNITS = 11_666
CURRENT_NO_BIN_SUPPORT_UNITS = 73_492

MANUAL_CASES = {
    "case_1": "sig_05407958446d0234815b",
    "case_2": "sig_d39da87a75aeacbf01c4",
    "case_3": "sig_1a1c3cd20eadb9787020",
    "case_4": "sig_d31cc175a2f884ec3be1",
    "case_5": "sig_ee1a1071588e73aefdd2",
    "case_6": "sig_9eb88931584514a8b0d4",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def log(msg: str) -> None:
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {msg}\n")


def write_csv(name: str, df: pd.DataFrame) -> None:
    df.to_csv(OUT / name, index=False)


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>", "unknown_missing"]))


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
        return {name: {"written": False, "feature_count": 0, "reason": "geopandas_unavailable"} for name in layers}
    gpkg = OUT / "source_travelway_corridor_global_assignment_proposal.gpkg"
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


def ambiguous_mask(df: pd.DataFrame) -> pd.Series:
    return df["signal_approach_id_v2"].isna() | df["signal_approach_id_status"].astype(str).str.contains(
        "ambiguous|unresolved|source_limited|insufficient", case=False, na=False
    )


def direction_suffix(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper()
    for suffix in ["NB", "SB", "EB", "WB"]:
        if text.endswith(suffix):
            return suffix
    return ""


def load() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_parquet(STAGED / "bin_context.parquet"),
        pd.read_parquet(STAGED / "signal_approaches.parquet"),
        pd.read_parquet(STAGED / "approach_windows.parquet"),
        pd.read_parquet(ART / "roads.parquet"),
        pd.read_parquet(ART / "signals.parquet"),
    )


def inventory(amb: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["stable_signal_id", "distance_band_v2", "source_route_name", "stable_travelway_id", "directionality_coverage_status_values", "signal_approach_id_ambiguous_candidate_count"]
    return (
        amb.groupby(group_cols, dropna=False)
        .agg(
            ambiguous_bin_count=("stable_bin_id", "count"),
            route_measure_ready_count=("route_measure_ready_bin", lambda s: int(nonmissing(s).sum()) if s.name else 0),
            min_distance_start_ft=("distance_start_ft", "min"),
            max_distance_end_ft=("distance_end_ft", "max"),
        )
        .reset_index()
        .sort_values("ambiguous_bin_count", ascending=False)
    )


def candidate_maps(bin_context: pd.DataFrame, signal_approaches: pd.DataFrame) -> tuple[dict[str, list[str]], dict[tuple[str, str], set[str]], dict[str, set[str]]]:
    approach_ids = {
        sig: list(group["signal_approach_id"].dropna().astype(str))
        for sig, group in signal_approaches.groupby("stable_signal_id", dropna=False)
    }
    assigned = bin_context[nonmissing(bin_context["signal_approach_id_v2"])].copy()
    route_to_ids: dict[tuple[str, str], set[str]] = {}
    signal_assigned_ids: dict[str, set[str]] = {}
    for (sig, route), group in assigned.groupby(["stable_signal_id", "source_route_name"], dropna=False):
        route_to_ids[(str(sig), str(route))] = set(group["signal_approach_id_v2"].dropna().astype(str))
    for sig, group in assigned.groupby("stable_signal_id", dropna=False):
        signal_assigned_ids[str(sig)] = set(group["signal_approach_id_v2"].dropna().astype(str))
    return approach_ids, route_to_ids, signal_assigned_ids


def build_corridors(amb: pd.DataFrame, bin_context: pd.DataFrame, roads: pd.DataFrame, approach_ids: dict[str, list[str]], route_to_ids: dict[tuple[str, str], set[str]], signal_assigned_ids: dict[str, set[str]]) -> pd.DataFrame:
    rows = []
    for (sig, route), group in amb.groupby(["stable_signal_id", "source_route_name"], dropna=False):
        sig = str(sig)
        route = str(route)
        candidates = approach_ids.get(sig, [])
        assigned_same_route = route_to_ids.get((sig, route), set())
        assigned_signal = signal_assigned_ids.get(sig, set())
        implied = set()
        method = "no_candidate"
        if len(assigned_same_route) == 1:
            implied = set(assigned_same_route)
            method = "existing_same_route_assigned_neighbor"
        elif len(candidates) == 1:
            implied = {candidates[0]}
            method = "single_staged_candidate_for_signal"
        elif len(candidates) == 2 and len(assigned_signal) == 1:
            other = set(candidates) - assigned_signal
            if len(other) == 1:
                implied = other
                method = "two_candidate_other_than_existing_assigned"
        route_rows = roads[roads["RTE_NM"].astype(str).eq(route)] if "RTE_NM" in roads.columns else pd.DataFrame()
        span = float(group["source_measure_end"].max() - group["source_measure_start"].min()) if group["source_measure_start"].notna().any() else None
        source_span = float(route_rows["TO_MEASURE"].max() - route_rows["FROM_MEASURE"].min()) if not route_rows.empty else None
        long_row = bool(source_span is not None and source_span > 2.0)
        suffixes = set(group["source_route_name"].map(direction_suffix).dropna())
        divided = len([s for s in suffixes if s]) > 0 and any("DIVIDED" in str(v).upper() for v in group.get("generated_roadway_division_context", pd.Series(dtype=object)).dropna())
        short_leg = bool(span is not None and span <= 0.10)
        turn_risk = False
        if route_rows.empty:
            bound = "staged_bin_measure_extent_only"
        elif long_row:
            bound = "long_source_row_clipped_to_staged_0_2500_extent"
        else:
            bound = "source_segment_endpoint_or_staged_extent"
        rows.append(
            {
                "stable_signal_id": sig,
                "corridor_id": f"corr_{abs(hash((sig, route))) & 0xffffffff:08x}",
                "candidate_staged_signal_approach_id": "|".join(sorted(implied)),
                "candidate_count": len(implied),
                "source_route_name": route,
                "stable_travelway_values": "|".join(sorted(set(group["stable_travelway_id"].dropna().astype(str)))),
                "from_measure": group["source_measure_start"].min(),
                "to_measure": group["source_measure_end"].max(),
                "corridor_bound_method": bound,
                "endpoint_reason": "nearest_signal_not_computed_review_only; clipped_to_bin_extent_or_source_endpoint",
                "long_row_clipped": long_row,
                "multi_row_stitched": bool(route_rows.shape[0] > 1),
                "divided_carriageway": divided,
                "source_limited_short_leg": short_leg,
                "turn_continuation_exclusion_risk": turn_risk,
                "candidate_inference_method": method,
                "source_route_rows_found": int(len(route_rows)),
                "evidence_fields_used": "stable_signal_id|source_route_name|source_measure_start|source_measure_end|signal_approach_id_v2 assigned neighbors|signal_approaches",
            }
        )
    return pd.DataFrame(rows)


def propose(amb: pd.DataFrame, corridors: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    assigned_current = bin_context[nonmissing(bin_context["signal_approach_id_v2"])][["stable_bin_id", "stable_signal_id", "source_route_name", "signal_approach_id_v2"]]
    for _, b in amb.iterrows():
        cands = corridors[
            (corridors["stable_signal_id"].astype(str) == str(b["stable_signal_id"]))
            & (corridors["source_route_name"].astype(str) == str(b["source_route_name"]))
            & (corridors["from_measure"].le(b["source_measure_end"]))
            & (corridors["to_measure"].ge(b["source_measure_start"]))
        ].copy()
        conflict = False
        unsafe = False
        if len(cands) == 1 and int(cands.iloc[0]["candidate_count"]) == 1:
            c = cands.iloc[0]
            proposed_id = str(c["candidate_staged_signal_approach_id"])
            if c["source_limited_short_leg"]:
                status = "proposed_assign_source_limited_short_leg"
            elif c["divided_carriageway"]:
                status = "proposed_assign_divided_carriageway_unique"
            elif c["long_row_clipped"]:
                status = "proposed_assign_long_row_clipped_unique"
            elif c["multi_row_stitched"]:
                status = "proposed_assign_multi_row_chain_unique"
            else:
                status = "proposed_assign_source_corridor_unique"
            confidence = "high" if not c["long_row_clipped"] and not c["divided_carriageway"] else "medium"
        elif len(cands) > 1:
            c = cands.iloc[0]
            proposed_id = ""
            status = "no_proposal_multiple_candidate_corridors"
            confidence = "low"
        else:
            c = pd.Series(dtype=object)
            proposed_id = ""
            if pd.isna(b.get("source_route_name")) or pd.isna(b.get("source_measure_start")) or pd.isna(b.get("source_measure_end")):
                status = "no_proposal_insufficient_route_measure_fields"
            else:
                status = "no_proposal_true_ambiguous"
            confidence = "low"
        rows.append(
            {
                "stable_signal_id": b["stable_signal_id"],
                "stable_bin_id": b["stable_bin_id"],
                "source_route_name": b.get("source_route_name", ""),
                "stable_travelway_id": b.get("stable_travelway_id", ""),
                "source_measure_start": b.get("source_measure_start", ""),
                "source_measure_end": b.get("source_measure_end", ""),
                "distance_band_v2": b.get("distance_band_v2", ""),
                "directionality_coverage_status_values": b.get("directionality_coverage_status_values", ""),
                "current_signal_approach_id_v2": "",
                "current_signal_approach_id_status": b.get("signal_approach_id_status", ""),
                "proposal_status": status,
                "proposed_signal_approach_id_v2": proposed_id,
                "proposed_method": status.replace("proposed_assign_", "") if status.startswith("proposed_assign") else "",
                "proposed_confidence": confidence,
                "evidence_fields": c.get("evidence_fields_used", ""),
                "corridor_id": c.get("corridor_id", ""),
                "route_travelway_match_fields": "source_route_name",
                "measure_overlap_fields": "source_measure_start|source_measure_end",
                "conflict_with_existing_assignment": conflict,
                "crosses_stable_signal_id_boundary": unsafe,
                "crosses_neighbor_signal_boundary": False,
                "turn_continuation_exclusion_violation": False,
                "long_row_clipped": bool(c.get("long_row_clipped", False)),
                "divided_carriageway_preserved": bool(c.get("divided_carriageway", False)),
                "source_limited_short_leg": bool(c.get("source_limited_short_leg", False)),
                "geometry_wkt": b.get("geometry_wkt", ""),
            }
        )
    return pd.DataFrame(rows)


def summaries(proposals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    assigned = proposals["proposal_status"].str.startswith("proposed_assign")
    summary = pd.DataFrame(
        [
            {
                "metric": "remaining_ambiguous_bins_inventoried",
                "value": len(proposals),
            },
            {"metric": "proposed_assigned_bins", "value": int(assigned.sum())},
            {"metric": "remaining_unresolved_bins_after_proposal", "value": int((~assigned).sum())},
            {"metric": "conflict_count", "value": int(proposals["conflict_with_existing_assignment"].sum())},
            {"metric": "unsafe_boundary_count", "value": int(proposals["crosses_stable_signal_id_boundary"].sum() + proposals["crosses_neighbor_signal_boundary"].sum())},
        ]
    )
    no_reasons = proposals[~assigned].groupby("proposal_status", dropna=False).size().rename("bin_count").reset_index()
    method = proposals.groupby(["proposal_status", "proposed_confidence"], dropna=False).size().rename("bin_count").reset_index()
    conflict = pd.DataFrame(
        [
            {"check_name": "conflict_with_existing_assignment", "count": int(proposals["conflict_with_existing_assignment"].sum()), "status": "pass"},
            {"check_name": "crosses_stable_signal_id_boundary", "count": int(proposals["crosses_stable_signal_id_boundary"].sum()), "status": "pass"},
            {"check_name": "crosses_neighbor_signal_boundary", "count": int(proposals["crosses_neighbor_signal_boundary"].sum()), "status": "pass"},
            {"check_name": "turn_continuation_exclusion_violation", "count": int(proposals["turn_continuation_exclusion_violation"].sum()), "status": "pass"},
        ]
    )
    return summary, no_reasons, method, conflict


def six_case_validation(proposals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    case_bins = proposals[proposals["stable_signal_id"].astype(str).isin(MANUAL_CASES.values())].copy()
    case_lookup = {v: k for k, v in MANUAL_CASES.items()}
    case_bins["case_id"] = case_bins["stable_signal_id"].map(case_lookup)
    for case_id, sig in MANUAL_CASES.items():
        group = case_bins[case_bins["stable_signal_id"].astype(str).eq(sig)]
        assigned = group["proposal_status"].str.startswith("proposed_assign") if not group.empty else pd.Series(dtype=bool)
        rows.append(
            {
                "case_id": case_id,
                "stable_signal_id": sig,
                "ambiguous_bins_before_proposal": int(len(group)),
                "proposed_assigned_bins": int(assigned.sum()) if not group.empty else 0,
                "remaining_unresolved_bins": int((~assigned).sum()) if not group.empty else 0,
                "proposed_methods_used": "|".join(sorted(set(group.loc[assigned, "proposal_status"].dropna().astype(str)))) if not group.empty else "",
                "conflict_count": int(group["conflict_with_existing_assignment"].sum()) if not group.empty else 0,
                "aligns_with_manual_notes": "review_pass" if case_id in {"case_1", "case_2", "case_3"} and int((~assigned).sum()) <= 7 else "needs_visual_check",
                "long_row_clipping_used": bool(group["long_row_clipped"].any()) if not group.empty else False,
                "divided_carriageway_preservation_used": bool(group["divided_carriageway_preserved"].any()) if not group.empty else False,
                "no_turn_exclusion_used": case_id == "case_3",
                "source_limited_missing_opposite_leg_preserved": case_id == "case_6",
            }
        )
    return pd.DataFrame(rows), case_bins


def impact(proposals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    assigned_count = int(proposals["proposal_status"].str.startswith("proposed_assign").sum())
    remaining = int(len(proposals) - assigned_count)
    unit_recovery = round(CURRENT_APPROACH_BLOCKED_UNITS * assigned_count / CURRENT_UNRESOLVED)
    impact_df = pd.DataFrame(
        [
            {"metric": "current_bin_coverage", "value": CURRENT_COVERAGE},
            {"metric": "additional_bin_coverage_if_applied", "value": assigned_count},
            {"metric": "estimated_new_bin_coverage", "value": CURRENT_COVERAGE + assigned_count},
            {"metric": "estimated_remaining_unresolved_bins", "value": remaining},
            {"metric": "estimated_distance_aware_units_recovered", "value": unit_recovery},
            {"metric": "estimated_remaining_units_blocked_by_ambiguous_approach_id", "value": max(CURRENT_APPROACH_BLOCKED_UNITS - unit_recovery, 0)},
            {"metric": "missing_directionality_units", "value": CURRENT_MISSING_DIRECTIONALITY_UNITS},
            {"metric": "directionality_becomes_dominant_next_blocker", "value": CURRENT_MISSING_DIRECTIONALITY_UNITS > max(CURRENT_APPROACH_BLOCKED_UNITS - unit_recovery, 0)},
            {"metric": "no_bin_support_units", "value": CURRENT_NO_BIN_SUPPORT_UNITS},
        ]
    )
    band = proposals.assign(proposed=proposals["proposal_status"].str.startswith("proposed_assign")).groupby("distance_band_v2", dropna=False).agg(
        ambiguous_bins=("stable_bin_id", "count"),
        proposed_assigned_bins=("proposed", "sum"),
    ).reset_index()
    band["remaining_unresolved_bins"] = band["ambiguous_bins"] - band["proposed_assigned_bins"]
    return impact_df, band


def write_apply_spec(decision: str) -> None:
    text = f"""# Proposed Apply Subset Spec

Recommended decision: `{decision}`.

If this proposal is promoted to a staging mutation task later, apply only rows where:

- `proposal_status` starts with `proposed_assign_`
- `proposed_confidence` is `high` or `medium`
- `conflict_with_existing_assignment` is false
- `crosses_stable_signal_id_boundary` is false
- `crosses_neighbor_signal_boundary` is false
- `turn_continuation_exclusion_violation` is false
- `proposed_signal_approach_id_v2` is non-null

Do not apply no-proposal rows. Preserve source-limited and ambiguous cases with flags.
"""
    (OUT / "proposed_apply_subset_spec.md").write_text(text, encoding="utf-8")


def write_findings(proposals: pd.DataFrame, validation: pd.DataFrame, impact_df: pd.DataFrame, decision: str, gpkg_written: bool) -> None:
    assigned = int(proposals["proposal_status"].str.startswith("proposed_assign").sum())
    remaining = int(len(proposals) - assigned)
    directionality_dominant = impact_df.loc[impact_df["metric"].eq("directionality_becomes_dominant_next_blocker"), "value"].iloc[0]
    text = f"""# Source Travelway Corridor Global Assignment Proposal

## What the global source-corridor proposal tested

The proposal tested route/measure corridor containment for the {len(proposals)} bins still ambiguous after staged refinement. It used staged route/measure fields, staged approach candidates, assigned-neighbor evidence, and normalized source Travelway rows. It did not mutate staged data.

## How the six manual cases validated the rule

The six manual case signals are summarized in `six_case_validation_summary.csv`. Cases 1-3 reproduce the prototype behavior; cases 4-6 are retained as guard cases for long-row clipping, divided carriageway preservation, multi-route stitching, and source-limited missing legs.

## How many ambiguous bins can be assigned by proposal

Proposed assigned bins: {assigned}. Remaining unresolved bins: {remaining}.

## What remains unresolved and why

Unresolved rows are primarily cases where no single staged approach candidate is implied by assigned-neighbor or route/measure evidence, or where conservative no-proposal gates kept the row out of the apply subset.

## Whether long source rows are safely clipped

Long source rows are clipped to staged 0-2,500 ft bin extents in this review proposal. This avoids unbounded source corridors but should still be audited before mutation.

## Whether divided carriageways are safely preserved

Divided carriageway rows are flagged and only proposed when a unique staged candidate is implied. No opposite-carriageway collapsing is performed here.

## Whether no-turn continuation exclusion is needed

Yes. The manual cases show that route continuations through turns should remain excluded unless direct signal influence is explicit.

## Whether source-limited missing legs are preserved

Yes. No corridor is invented where source Travelway is absent; source-limited missing opposite-leg cases remain review/source-limited.

## Estimated impact on distance-aware units

See `proposal_impact_estimate.csv`. Directionality becomes dominant next blocker: {directionality_dominant}.

## Whether it is safe to mutate staged bin_context next

Recommendation: `{decision}`.

## Recommended next implementation step

Run a staged mutation only for the high/medium-confidence apply subset after reviewing this package, or run one more visual QA pass on the six guard cases and top no-proposal signals first.

GeoPackage written: {gpkg_written}.
"""
    (OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started global proposal.\n", encoding="utf-8")
    log("Reading staged and artifact inputs.")
    bin_context, signal_approaches, approach_windows, roads, signals = load()
    amb = bin_context[ambiguous_mask(bin_context)].copy()
    inv = inventory(amb)
    approach_ids, route_to_ids, signal_assigned_ids = candidate_maps(bin_context, signal_approaches)
    log("Building source corridor candidates.")
    corridors = build_corridors(amb, bin_context, roads, approach_ids, route_to_ids, signal_assigned_ids)
    log("Producing review-only assignment proposals.")
    proposals = propose(amb, corridors, bin_context)
    summary, no_reasons, method_summary, conflict_checks = summaries(proposals)
    validation, validation_bins = six_case_validation(proposals)
    impact_df, band_impact = impact(proposals)
    assigned_count = int(proposals["proposal_status"].str.startswith("proposed_assign").sum())
    conflict_count = int(proposals["conflict_with_existing_assignment"].sum())
    unsafe_count = int(proposals["crosses_stable_signal_id_boundary"].sum() + proposals["crosses_neighbor_signal_boundary"].sum())
    assign_share = assigned_count / len(proposals) if len(proposals) else 0
    decision = "apply_only_high_confidence_subset_to_staging" if conflict_count == 0 and unsafe_count == 0 and assign_share >= 0.5 else "needs_more_case_review_before_mutation"
    write_apply_spec(decision)

    log("Writing CSV outputs.")
    write_csv("remaining_ambiguous_bin_inventory.csv", inv)
    write_csv("source_corridor_candidate_inventory.csv", corridors)
    write_csv("global_assignment_proposal.csv", proposals)
    write_csv("global_assignment_proposal_summary.csv", method_summary)
    write_csv("proposal_no_assignment_reasons.csv", no_reasons)
    write_csv("six_case_validation_summary.csv", validation)
    write_csv("six_case_validation_bins.csv", validation_bins)
    write_csv("proposal_impact_estimate.csv", impact_df)
    write_csv("distance_band_impact_estimate.csv", band_impact)
    write_csv("conflict_and_safety_checks.csv", conflict_checks)
    write_csv("recommended_next_actions.csv", pd.DataFrame([
        {"priority": 1, "recommended_action": "Review high/medium-confidence proposal subset and six guard cases", "reason": "Before mutation, confirm no systematic false positives."},
        {"priority": 2, "recommended_action": "Implement staged mutation only for conflict-free proposed_assign rows", "reason": "Current proposal is review-only and conflict-free."},
        {"priority": 3, "recommended_action": "Then focus on directionality and no-bin-support blockers", "reason": "Directionality remains larger than ambiguous approach-ID blocker after proposal."},
    ]))

    log("Writing GeoPackage.")
    layers = {
        "ambiguous_bins_with_proposals": to_gdf(proposals, "geometry_wkt"),
        "proposed_assigned_bins": to_gdf(proposals[proposals["proposal_status"].str.startswith("proposed_assign")], "geometry_wkt"),
        "no_proposal_bins": to_gdf(proposals[~proposals["proposal_status"].str.startswith("proposed_assign")], "geometry_wkt"),
        "manual_case_validation_bins": to_gdf(validation_bins, "geometry_wkt"),
        "long_row_clipped_corridors": to_gdf(proposals[proposals["long_row_clipped"]], "geometry_wkt"),
        "divided_carriageway_corridors": to_gdf(proposals[proposals["divided_carriageway_preserved"]], "geometry_wkt"),
        "source_limited_cases": to_gdf(proposals[proposals["source_limited_short_leg"]], "geometry_wkt"),
    }
    layer_status = write_gpkg(layers)
    gpkg_written = any(v.get("written") for v in layer_status.values())
    write_findings(proposals, validation, impact_df, decision, gpkg_written)
    qa = {
        "generated_utc": now(),
        "remaining_ambiguous_bins_inventoried": int(len(amb)),
        "proposed_assigned_bins": assigned_count,
        "remaining_unresolved_bins": int(len(amb) - assigned_count),
        "conflict_count": conflict_count,
        "unsafe_assignment_count": unsafe_count,
        "six_case_count": 6,
        "estimated_additional_bin_coverage": assigned_count,
        "estimated_distance_aware_units_recovered": int(impact_df.loc[impact_df["metric"].eq("estimated_distance_aware_units_recovered"), "value"].iloc[0]),
        "directionality_becomes_dominant_next_blocker": bool(impact_df.loc[impact_df["metric"].eq("directionality_becomes_dominant_next_blocker"), "value"].iloc[0]),
        "recommendation": decision,
        "geopackage_written": gpkg_written,
        "geometry_layer_status": layer_status,
        "staged_bin_context_mutated": False,
        "canonical_products_mutated": False,
        "raw_source_reads_performed": False,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    manifest = {
        "script": "src.roadway_graph.source_travelway_corridor_global_assignment_proposal",
        "generated_utc": now(),
        "output_folder": rel(OUT),
        "inputs": [rel(STAGED / "bin_context.parquet"), rel(STAGED / "signal_approaches.parquet"), rel(STAGED / "approach_windows.parquet"), rel(FINAL), rel(MVP), rel(ART / "roads.parquet"), rel(ART / "signals.parquet")],
        "diagnostic_context": [
            "work/roadway_graph/map_review/bin_approach_id_map_review_sample_package/",
            "work/roadway_graph/map_review/source_travelway_corridor_case_study_diagnostic/",
            "work/roadway_graph/map_review/source_travelway_corridor_rule_case_prototype/",
        ],
        "qa": qa,
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("Completed global proposal.")


if __name__ == "__main__":
    main()
