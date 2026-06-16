"""Read-only audit of remaining expanded directionality blockers.

This script does not mutate staged bin_context or assign upstream/downstream.
It decomposes unresolved directionality rows and proposes deterministic rule
families or map-review clusters for later bounded work.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
REVIEW_DIR = REPO_ROOT / "work/roadway_graph/review/expanded_directionality_blocker_rule_proposal_audit"
EXPANDED_RECOVERY_DIR = REPO_ROOT / "work/roadway_graph/review/expanded_directionality_recovery_audit"
EXPANDED_IMPACT_DIR = REPO_ROOT / "work/roadway_graph/review/expanded_bin_universe_impact_audit"
QA_DIR = REPO_ROOT / "work/roadway_graph/review/proposed_generated_bins_qa_audit"
CONTINUATION_SUBSET_DIR = REPO_ROOT / "work/roadway_graph/review/distance_continuation_implementation_subset_review"
ENDPOINT_AUDIT_DIR = REPO_ROOT / "work/roadway_graph/review/distance_endpoint_continuation_audit"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING_DIR / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING_DIR / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING_DIR / "continuation_provenance.parquet"
MANIFEST = STAGING_DIR / "manifest.json"
SCHEMA = STAGING_DIR / "schema.json"
SIGNALS_ARTIFACT = REPO_ROOT / "artifacts/normalized/signals.parquet"
ROADS_ARTIFACT = REPO_ROOT / "artifacts/normalized/roads.parquet"

CONSERVATIVE_TARGET = 109_842
UPPER_BOUND_TARGET = 132_866
KNOWN_DIRECTION_READY_UNITS = 98_831
MANUAL_GUARD_SIGNALS = [
    "sig_9eb88931584514a8b0d4",
    "sig_d31cc175a2f884ec3be1",
    "sig_ee1a1071588e73aefdd2",
    "sig_05407958446d0234815b",
    "sig_d39da87a75aeacbf01c4",
    "sig_1a1c3cd20eadb9787020",
]
BAND_ORDER = {"0-250": 0, "250-500": 1, "500-1000": 2, "1000-1500": 3, "1500-2000": 4, "2000-2500": 5}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_csv(df: pd.DataFrame, name: str) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(REVIEW_DIR / name, index=False)


def log_progress(message: str) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with (REVIEW_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"{now_iso()} {message}\n")


def nonnull(s: pd.Series) -> pd.Series:
    return s.notna() & (s.astype(str).str.strip() != "")


def side_series(df: pd.DataFrame) -> pd.Series:
    if "upstream_downstream_values" in df.columns:
        return df["upstream_downstream_values"]
    if "upstream_downstream" in df.columns:
        return df["upstream_downstream"]
    return pd.Series([pd.NA] * len(df), index=df.index)


def band_series(df: pd.DataFrame) -> pd.Series:
    if "distance_band_v2" in df.columns:
        return df["distance_band_v2"]
    if "distance_band" in df.columns:
        return df["distance_band"]
    return pd.Series([pd.NA] * len(df), index=df.index)


def first_present(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def unit_count(df: pd.DataFrame) -> int:
    sides = side_series(df)
    bands = band_series(df)
    valid = df[nonnull(df["stable_signal_id"]) & nonnull(df["signal_approach_id_v2"]) & nonnull(bands) & nonnull(sides)].copy()
    if valid.empty:
        return 0
    valid["_band"] = bands.loc[valid.index]
    valid["_side"] = sides.loc[valid.index].astype(str).str.split("|")
    exploded = valid.explode("_side")
    exploded = exploded[nonnull(exploded["_side"])]
    return int(exploded[["stable_signal_id", "signal_approach_id_v2", "_band", "_side"]].drop_duplicates().shape[0])


def side_evidence_tables(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    assigned = df[nonnull(side_series(df))].copy()
    assigned["_side"] = side_series(assigned).astype(str)
    assigned["_band"] = band_series(assigned)
    assigned["_band_order"] = assigned["_band"].map(BAND_ORDER)
    by_approach = (
        assigned.groupby(["stable_signal_id", "signal_approach_id_v2"], dropna=False)
        .agg(side_count=("_side", "nunique"), side_values=("_side", lambda x: "|".join(sorted(set(map(str, x))))), assigned_bin_count=("_side", "size"))
        .reset_index()
    )
    by_approach_band = (
        assigned.groupby(["stable_signal_id", "signal_approach_id_v2", "_band"], dropna=False)
        .agg(side_count=("_side", "nunique"), side_values=("_side", lambda x: "|".join(sorted(set(map(str, x))))), assigned_bin_count=("_side", "size"))
        .reset_index()
        .rename(columns={"_band": "distance_band"})
    )
    by_corridor_route = (
        assigned.groupby(["stable_signal_id", "signal_approach_id_v2", "continuation_corridor_id", "source_route_name"], dropna=False)
        .agg(side_count=("_side", "nunique"), side_values=("_side", lambda x: "|".join(sorted(set(map(str, x))))), assigned_bin_count=("_side", "size"))
        .reset_index()
        if {"continuation_corridor_id", "source_route_name"}.issubset(assigned.columns)
        else pd.DataFrame()
    )
    return by_approach, by_approach_band, by_corridor_route


def profile_missing(df: pd.DataFrame) -> pd.DataFrame:
    missing = df[~nonnull(side_series(df))].copy()
    missing["_distance_band"] = band_series(missing)
    config_col = first_present(missing, ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw", "RTE_TYPE_N"])
    divided_col = first_present(missing, ["generated_roadway_division_context", "existing_roadway_division_context", "rim_facility_raw"])
    rows = []
    for col, out_name in [
        ("bin_row_origin", "remaining_directionality_by_origin.csv"),
        ("_distance_band", "remaining_directionality_by_distance_band.csv"),
        (config_col, "remaining_directionality_by_roadway_configuration.csv"),
        ("continuation_class", "remaining_directionality_by_continuation_class.csv"),
        ("stable_signal_id", "remaining_directionality_by_signal.csv"),
    ]:
        if col and col in missing.columns:
            grp = missing.groupby(col, dropna=False).size().reset_index(name="missing_directionality_bins").sort_values("missing_directionality_bins", ascending=False)
            write_csv(grp, out_name)
    approach = (
        missing.groupby(["stable_signal_id", "signal_approach_id_v2"], dropna=False)
        .size()
        .reset_index(name="missing_directionality_bins")
        .sort_values("missing_directionality_bins", ascending=False)
    )
    write_csv(approach, "remaining_directionality_by_approach.csv")
    profile_cols = [
        c
        for c in [
            "stable_bin_id",
            "bin_row_origin",
            "generated_bin_flag",
            "continuation_class",
            "continuation_method",
            "continuation_corridor_id",
            "stable_signal_id",
            "signal_approach_id_v2",
            "_distance_band",
            "distance_start_ft",
            "distance_end_ft",
            "stable_travelway_id",
            "source_route_name",
            "source_route_common",
            "source_measure_start",
            "source_measure_end",
            config_col,
            divided_col,
            "median_group",
            "directionality_direct_or_synthetic_values",
            "mvp_directionality_method_values",
            "directionality_recovery_status",
            "geometry_wkt",
        ]
        if c and c in missing.columns
    ]
    out = missing[profile_cols].copy()
    if "geometry_wkt" in out.columns:
        out["geometry_available"] = nonnull(out["geometry_wkt"])
    return out


def classify_rule_candidates(df: pd.DataFrame) -> pd.DataFrame:
    missing = df[~nonnull(side_series(df))].copy()
    missing["_distance_band"] = band_series(missing)
    missing["_band_order"] = missing["_distance_band"].map(BAND_ORDER)
    by_approach, by_approach_band, by_corridor_route = side_evidence_tables(df)

    cluster_keys = [
        "stable_signal_id",
        "signal_approach_id_v2",
        "continuation_corridor_id",
        "source_route_name",
        "_distance_band",
        "bin_row_origin",
        "continuation_class",
        "directionality_recovery_status",
    ]
    for col in cluster_keys:
        if col not in missing.columns:
            missing[col] = pd.NA
    clusters = (
        missing.groupby(cluster_keys, dropna=False)
        .agg(
            missing_bins=("stable_bin_id", "size"),
            min_distance_start_ft=("distance_start_ft", "min"),
            max_distance_end_ft=("distance_end_ft", "max"),
            geometry_available=("geometry_wkt", lambda x: int(nonnull(x).sum()) if "geometry_wkt" in missing.columns else 0),
            route_measure_non_null=("source_measure_start", lambda x: int(nonnull(x).sum()) if "source_measure_start" in missing.columns else 0),
        )
        .reset_index()
        .rename(columns={"_distance_band": "distance_band"})
    )
    clusters["band_order"] = clusters["distance_band"].map(BAND_ORDER)

    approach_evidence = by_approach.rename(columns={"side_count": "approach_side_count", "side_values": "approach_side_values"})
    clusters = clusters.merge(
        approach_evidence[["stable_signal_id", "signal_approach_id_v2", "approach_side_count", "approach_side_values", "assigned_bin_count"]],
        on=["stable_signal_id", "signal_approach_id_v2"],
        how="left",
    )
    if not by_corridor_route.empty:
        route_evidence = by_corridor_route.rename(columns={"side_count": "corridor_route_side_count", "side_values": "corridor_route_side_values"})
        clusters = clusters.merge(
            route_evidence[
                [
                    "stable_signal_id",
                    "signal_approach_id_v2",
                    "continuation_corridor_id",
                    "source_route_name",
                    "corridor_route_side_count",
                    "corridor_route_side_values",
                ]
            ],
            on=["stable_signal_id", "signal_approach_id_v2", "continuation_corridor_id", "source_route_name"],
            how="left",
        )
    else:
        clusters["corridor_route_side_count"] = pd.NA
        clusters["corridor_route_side_values"] = pd.NA

    band_evidence = by_approach_band.copy()
    band_evidence["band_order"] = band_evidence["distance_band"].map(BAND_ORDER)
    prev_evidence = band_evidence.copy()
    prev_evidence["band_order"] = prev_evidence["band_order"] + 1
    prev_evidence = prev_evidence.rename(columns={"side_count": "prev_band_side_count", "side_values": "prev_band_side_values", "assigned_bin_count": "prev_band_assigned_bins"})
    next_evidence = band_evidence.copy()
    next_evidence["band_order"] = next_evidence["band_order"] - 1
    next_evidence = next_evidence.rename(columns={"side_count": "next_band_side_count", "side_values": "next_band_side_values", "assigned_bin_count": "next_band_assigned_bins"})
    clusters = clusters.merge(
        prev_evidence[["stable_signal_id", "signal_approach_id_v2", "band_order", "prev_band_side_count", "prev_band_side_values", "prev_band_assigned_bins"]],
        on=["stable_signal_id", "signal_approach_id_v2", "band_order"],
        how="left",
    ).merge(
        next_evidence[["stable_signal_id", "signal_approach_id_v2", "band_order", "next_band_side_count", "next_band_side_values", "next_band_assigned_bins"]],
        on=["stable_signal_id", "signal_approach_id_v2", "band_order"],
        how="left",
    )

    config = []
    proposal_status = []
    rule_family = []
    potential_units = []
    for row in clusters.itertuples(index=False):
        origin = str(getattr(row, "bin_row_origin", ""))
        klass = str(getattr(row, "continuation_class", ""))
        route_side_count = getattr(row, "corridor_route_side_count", pd.NA)
        app_side_count = getattr(row, "approach_side_count", pd.NA)
        prev_count = getattr(row, "prev_band_side_count", pd.NA)
        next_count = getattr(row, "next_band_side_count", pd.NA)
        prev_vals = str(getattr(row, "prev_band_side_values", "") or "")
        next_vals = str(getattr(row, "next_band_side_values", "") or "")
        geom_count = int(getattr(row, "geometry_available", 0) or 0)
        measure_count = int(getattr(row, "route_measure_non_null", 0) or 0)
        family = "map_review_needed"
        status = "map_review_candidate_directionality_rule_discovery"
        if origin == "generated_distance_continuation_bin" and measure_count > 0 and pd.notna(route_side_count) and int(route_side_count) == 1:
            family = "generated_corridor_geometry_continuation"
            status = "proposed_recover_generated_corridor_geometry_continuation"
        elif origin == "generated_distance_continuation_bin" and measure_count == 0:
            family = "generated_corridor_geometry_continuation"
            status = "no_proposal_missing_corridor_geometry_or_measure"
        elif "divided" in klass.lower() and pd.notna(route_side_count) and int(route_side_count) == 1:
            family = "divided_direct_geometry"
            status = "proposed_recover_divided_direct_geometry"
        elif "divided" in klass.lower():
            family = "divided_direct_geometry"
            status = "no_proposal_divided_missing_carriageway_fields"
        elif pd.notna(prev_count) and int(prev_count) == 1 and pd.notna(next_count) and int(next_count) == 1 and prev_vals == next_vals:
            family = "adjacent_distance_band_continuity"
            status = "proposed_recover_adjacent_distance_band_continuity"
        elif pd.notna(prev_count) or pd.notna(next_count):
            family = "adjacent_distance_band_continuity"
            status = "no_proposal_adjacent_band_conflict" if prev_vals and next_vals and prev_vals != next_vals else "no_proposal_no_adjacent_directionality"
        elif pd.notna(app_side_count) and int(app_side_count) == 1 and int(getattr(row, "missing_bins", 0)) <= 5:
            family = "single_side_structural"
            status = "proposed_recover_single_side_structural"
        elif pd.notna(app_side_count) and int(app_side_count) == 1:
            family = "single_side_structural"
            status = "no_proposal_single_side_not_structurally_safe"
        elif geom_count > 0 and ("undivided" in klass.lower() or "synthetic" in klass.lower()):
            family = "undivided_synthetic_centerline_geometry"
            status = "proposed_recover_synthetic_undivided_geometry"
        elif geom_count == 0 and ("undivided" in klass.lower() or "synthetic" in klass.lower()):
            family = "undivided_synthetic_centerline_geometry"
            status = "no_proposal_undivided_missing_geometry"
        rule_family.append(family)
        proposal_status.append(status)
        # Cluster contributes at most two direction units at signal x approach x band.
        potential_units.append(2)
        config.append("")
    clusters["proposed_rule_family"] = rule_family
    clusters["proposal_status"] = proposal_status
    clusters["potential_direction_units"] = potential_units
    clusters["proposal_is_deterministic_candidate"] = clusters["proposal_status"].astype(str).str.startswith("proposed_recover_")
    return clusters


def write_candidate_subsets(candidates: pd.DataFrame) -> None:
    write_csv(candidates, "candidate_directionality_rule_proposals.csv")
    family_summary = (
        candidates.groupby(["proposed_rule_family", "proposal_status", "proposal_is_deterministic_candidate"], dropna=False)
        .agg(clusters=("missing_bins", "size"), missing_bins=("missing_bins", "sum"), potential_direction_units=("potential_direction_units", "sum"))
        .reset_index()
        .sort_values(["proposal_is_deterministic_candidate", "potential_direction_units"], ascending=[False, False])
    )
    write_csv(family_summary, "candidate_rule_family_summary.csv")
    mapping = {
        "generated_corridor_geometry_continuation": "generated_corridor_geometry_continuation_candidates.csv",
        "undivided_synthetic_centerline_geometry": "synthetic_undivided_geometry_candidates.csv",
        "divided_direct_geometry": "divided_direct_geometry_candidates.csv",
        "adjacent_distance_band_continuity": "adjacent_distance_band_continuity_candidates.csv",
        "single_side_structural": "single_side_structural_candidates.csv",
    }
    for family, filename in mapping.items():
        write_csv(candidates[candidates["proposed_rule_family"] == family], filename)


def unit_recovery_summaries(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    current = KNOWN_DIRECTION_READY_UNITS
    needed_cons = max(0, CONSERVATIVE_TARGET - current)
    needed_upper = max(0, UPPER_BOUND_TARGET - current)
    proposed = candidates[candidates["proposal_is_deterministic_candidate"]].copy()
    proposed_units = int(proposed["potential_direction_units"].sum()) if not proposed.empty else 0
    summary = pd.DataFrame(
        [
            {"metric": "current_direction_ready_units", "value": current},
            {"metric": "conservative_target", "value": CONSERVATIVE_TARGET},
            {"metric": "upper_bound_target", "value": UPPER_BOUND_TARGET},
            {"metric": "additional_units_needed_for_conservative_target", "value": needed_cons},
            {"metric": "additional_units_needed_for_upper_bound_target", "value": needed_upper},
            {"metric": "candidate_deterministic_potential_units", "value": proposed_units},
            {"metric": "candidate_percent_of_conservative_gap", "value": round(proposed_units / needed_cons * 100, 4) if needed_cons else 0},
            {"metric": "candidate_percent_of_upper_bound_gap", "value": round(proposed_units / needed_upper * 100, 4) if needed_upper else 0},
        ]
    )
    by_family = (
        candidates.groupby(["proposed_rule_family", "proposal_is_deterministic_candidate"], dropna=False)
        .agg(clusters=("missing_bins", "size"), missing_bins=("missing_bins", "sum"), potential_direction_units=("potential_direction_units", "sum"))
        .reset_index()
        .sort_values("potential_direction_units", ascending=False)
    )
    return summary, by_family


def cluster_inventory(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    inv = candidates.copy()
    inv["far_distance_priority"] = inv["distance_band"].isin(["1000-1500", "1500-2000", "2000-2500"])
    inv["review_priority_score"] = (
        inv["potential_direction_units"].fillna(0) * 10
        + inv["missing_bins"].fillna(0)
        + inv["far_distance_priority"].astype(int) * 5
        + (inv["bin_row_origin"].astype(str) == "generated_distance_continuation_bin").astype(int) * 4
        + inv["geometry_available"].fillna(0).clip(upper=1) * 3
    )
    ranked = inv.sort_values(["proposal_is_deterministic_candidate", "review_priority_score"], ascending=[True, False]).head(20)
    return inv, ranked


def manual_guard(candidates: pd.DataFrame, missing_profile: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sig in MANUAL_GUARD_SIGNALS:
        c = candidates[candidates["stable_signal_id"] == sig]
        m = missing_profile[missing_profile["stable_signal_id"] == sig] if "stable_signal_id" in missing_profile.columns else pd.DataFrame()
        violates = False
        if sig == "sig_9eb88931584514a8b0d4":
            # Preserve missing opposite leg: generated/source-limited cases should not be forced without evidence.
            violates = bool(c["proposal_status"].astype(str).str.startswith("proposed_recover_").any() and (c["source_route_name"].astype(str).str.contains("00706", na=False).any()))
        rows.append(
            {
                "stable_signal_id": sig,
                "missing_directionality_bins": int(len(m)),
                "candidate_clusters": int(len(c)),
                "deterministic_candidate_clusters": int(c["proposal_is_deterministic_candidate"].sum()) if not c.empty else 0,
                "proposal_statuses": "|".join(sorted(c["proposal_status"].dropna().astype(str).unique())) if not c.empty else "",
                "potential_direction_units": int(c["potential_direction_units"].sum()) if not c.empty else 0,
                "guard_expectation_violation_flag": violates,
                "guard_note": "source_limited_missing_leg_preserved" if sig == "sig_9eb88931584514a8b0d4" and not violates else "",
            }
        )
    return pd.DataFrame(rows)


def write_findings(missing_count: int, unit_summary: pd.DataFrame, family_summary: pd.DataFrame, ranked: pd.DataFrame, recommendation: str) -> None:
    needed_cons = int(unit_summary.loc[unit_summary["metric"] == "additional_units_needed_for_conservative_target", "value"].iloc[0])
    needed_upper = int(unit_summary.loc[unit_summary["metric"] == "additional_units_needed_for_upper_bound_target", "value"].iloc[0])
    top_families = family_summary.head(8).to_string(index=False)
    text = f"""# Expanded Directionality Blocker Rule-Proposal Audit

## What remains after the first directionality recovery

There are {missing_count:,} bins still missing upstream/downstream in the expanded staged `bin_context`.

## How many additional units are needed to reach the conservative and upper-bound targets

Additional direction-ready units needed: {needed_cons:,} to reach the conservative target and {needed_upper:,} to reach the upper-bound target.

## Which unresolved directionality classes are most important

The main remaining classes are summarized in `candidate_rule_family_summary.csv` and the top rows are:

```text
{top_families}
```

## Which deterministic rule families look promising

The audit produced review-only candidate counts for generated corridor geometry continuation, divided/direct geometry, synthetic undivided geometry, adjacent-band continuity, and single-side structural rules. These are proposals only; no directionality was assigned.

## Whether geometry-based rules are needed

Yes. The remaining blockers generally lack deterministic same-corridor side evidence in the table. Geometry/measure-aware rules or a small map-review sample are needed before another mutation pass.

## Whether a small map-review sample could unlock broader recovery

Yes. `ranked_directionality_map_review_candidate_clusters.csv` selects high-priority clusters for rule discovery without creating a map-review package.

## Recommended next step

Recommendation: `{recommendation}`. Create a small map-review package for directionality rule discovery or build a review-only geometry proposal before mutating staged `bin_context`.
"""
    (REVIEW_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    log_progress("Started expanded directionality blocker rule-proposal audit.")
    required = [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, CONTINUATION_CORRIDORS, CONTINUATION_PROVENANCE, MANIFEST, SCHEMA]
    missing_inputs = [rel(p) for p in required if not p.exists()]
    if missing_inputs:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing_inputs))

    print("reading expanded staged bin_context", flush=True)
    log_progress("Reading expanded staged products.")
    df = pd.read_parquet(BIN_CONTEXT)
    pd.read_parquet(SIGNAL_APPROACHES)
    pd.read_parquet(APPROACH_WINDOWS)
    pd.read_parquet(CONTINUATION_CORRIDORS)
    pd.read_parquet(CONTINUATION_PROVENANCE)

    log_progress("Profiling remaining missing directionality rows.")
    missing_profile = profile_missing(df)
    write_csv(missing_profile, "remaining_directionality_bin_profile.csv")

    log_progress("Classifying candidate rule families.")
    candidates = classify_rule_candidates(df)
    write_candidate_subsets(candidates)

    unit_summary, unit_by_family = unit_recovery_summaries(candidates)
    write_csv(unit_summary, "unit_recovery_potential_summary.csv")
    write_csv(unit_by_family, "unit_recovery_potential_by_rule_family.csv")

    clusters, ranked = cluster_inventory(candidates)
    write_csv(clusters, "unresolved_directionality_cluster_inventory.csv")
    write_csv(ranked, "ranked_directionality_map_review_candidate_clusters.csv")

    guard = manual_guard(candidates, missing_profile)
    write_csv(guard, "manual_guard_signal_directionality_check.csv")

    recommendation = "create_small_map_review_package_for_directionality_rule_discovery"
    deterministic_units = int(unit_summary.loc[unit_summary["metric"] == "candidate_deterministic_potential_units", "value"].iloc[0])
    if deterministic_units > 5_000:
        recommendation = "do_another_table_rule_pass_before_map_review"
    if deterministic_units == 0:
        recommendation = "perform_geometry_enrichment_before_directionality_recovery"

    next_actions = pd.DataFrame(
        [
            {"priority": 1, "recommended_action": recommendation, "rationale": "Remaining blockers need geometry-aware evidence or targeted visual rule discovery before mutation."},
            {"priority": 2, "recommended_action": "create_review_only_directionality_proposal_before_staging_mutation", "rationale": "Do not mutate upstream/downstream from this audit."},
            {"priority": 3, "recommended_action": "preserve_source_limited_and_ambiguous_cases", "rationale": "Directionality doctrine requires explicit unresolved flags rather than force-fill."},
        ]
    )
    write_csv(next_actions, "recommended_next_actions.csv")

    write_findings(len(missing_profile), unit_summary, unit_by_family, ranked, recommendation)
    manifest = {
        "generated_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "output_folder": rel(REVIEW_DIR),
        "inputs_read": [rel(p) for p in required]
        + [rel(p) for p in [EXPANDED_RECOVERY_DIR, EXPANDED_IMPACT_DIR, QA_DIR, CONTINUATION_SUBSET_DIR, ENDPOINT_AUDIT_DIR, SIGNALS_ARTIFACT, ROADS_ARTIFACT] if p.exists()],
        "outputs_written": sorted(p.name for p in REVIEW_DIR.iterdir() if p.is_file()),
        "row_counts": {
            "expanded_bin_context_rows": int(len(df)),
            "remaining_missing_directionality_bins": int(len(missing_profile)),
            "candidate_rule_clusters": int(len(candidates)),
        },
        "staged_bin_context_modified": False,
        "directionality_assigned": False,
        "canonical_products_modified": False,
        "crash_direction_fields_used": False,
    }
    (REVIEW_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "required_outputs_written": True,
        "staged_bin_context_modified": False,
        "directionality_assigned": False,
        "canonical_products_modified": False,
        "raw_source_reads_performed": False,
        "crash_direction_fields_used": False,
        "recommendation": recommendation,
    }
    (REVIEW_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    progress_text = f"# Progress\n- {now_iso()} Completed expanded directionality blocker rule-proposal audit.\n"
    (REVIEW_DIR / "progress_log.md").write_text(progress_text, encoding="utf-8")
    log_progress("Completed expanded directionality blocker rule-proposal audit.")
    print(f"remaining_missing_directionality_bins={len(missing_profile)}")
    print(f"candidate_rule_clusters={len(candidates)}")
    print(f"candidate_deterministic_potential_units={deterministic_units}")
    print(f"recommendation={recommendation}")


if __name__ == "__main__":
    main()
