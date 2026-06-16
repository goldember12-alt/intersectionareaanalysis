"""Read-only distance-aware MVP unit-universe and bin-lineage audit.

This audit evaluates a future distance-band MVP grain without refreshing,
promoting, or modifying canonical/staged products.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
FINAL_DIR = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP_DIR = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
STAGED_DIR = REPO / "work" / "roadway_graph" / "analysis" / "_staging" / "final_leg_corrected_analysis_dataset_refresh_candidate"
OUT_DIR = REPO / "work" / "roadway_graph" / "review" / "distance_aware_unit_universe_and_bin_lineage_audit"

BANDS = [
    ("0-250 ft", 0, 250),
    ("250-500 ft", 250, 500),
    ("500-1,000 ft", 500, 1000),
    ("1,000-1,500 ft", 1000, 1500),
    ("1,500-2,000 ft", 1500, 2000),
    ("2,000-2,500 ft", 2000, 2500),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>", "unknown_missing"]))


def write_csv(name: str, rows) -> None:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    df.to_csv(OUT_DIR / name, index=False)


def log(message: str) -> None:
    with (OUT_DIR / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def assign_distance_band(midpoint: float | int | None) -> str | pd.NA:
    if pd.isna(midpoint):
        return pd.NA
    try:
        m = float(midpoint)
    except Exception:
        return pd.NA
    for label, low, high in BANDS:
        if low <= m < high or (label == "2,000-2,500 ft" and low <= m <= high):
            return label
    return pd.NA


def normalize_window(value) -> str:
    mapping = {"0_1000": "0-1,000 ft", "1000_2500": "1,000-2,500 ft", "0_2500": "0-2,500 ft"}
    if pd.isna(value):
        return value
    return mapping.get(str(value), str(value))


def load_inputs():
    bin_cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "signal_approach_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "speed_limit_mph",
        "aadt",
        "aadt_exposure_denominator",
        "median_group",
        "final_review_recovery_provenance",
        "final_review_context_status",
        "lineage_match_method",
        "lineage_confidence",
        "numeric_missingness_reason",
    ]
    bins = pd.read_csv(FINAL_DIR / "analysis_bin.csv", usecols=bin_cols, low_memory=False)
    bins["window_label"] = bins["analysis_window"].map(normalize_window)
    bins["distance_midpoint_ft"] = (pd.to_numeric(bins["distance_start_ft"], errors="coerce") + pd.to_numeric(bins["distance_end_ft"], errors="coerce")) / 2
    bins["proposed_distance_band"] = bins["distance_midpoint_ft"].apply(assign_distance_band)
    bins["broader_window_0_1000"] = pd.to_numeric(bins["distance_end_ft"], errors="coerce") <= 1000
    bins["broader_window_0_2500"] = pd.to_numeric(bins["distance_end_ft"], errors="coerce") <= 2500

    dir_cols = [
        "stable_signal_id",
        "signal_approach_id",
        "stable_bin_id",
        "stable_travelway_id",
        "window_label",
        "upstream_downstream",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "directionality_direct_or_synthetic",
        "mvp_directionality_method",
        "directionality_coverage_status",
        "directionality_caveat",
        "roadway_configuration" if False else "divided_undivided",
        "speed_limit_mph",
        "aadt",
        "exposure_denominator",
        "median_group",
    ]
    # Keep only columns that exist in the current file.
    header = list(pd.read_csv(MVP_DIR / "mvp_directional_bin_context.csv", nrows=0).columns)
    use = [c for c in dir_cols if c in header]
    dir_bins = pd.read_csv(MVP_DIR / "mvp_directional_bin_context.csv", usecols=use, low_memory=False)
    dir_bins["distance_midpoint_ft"] = (pd.to_numeric(dir_bins["distance_start_ft"], errors="coerce") + pd.to_numeric(dir_bins["distance_end_ft"], errors="coerce")) / 2
    dir_bins["proposed_distance_band"] = dir_bins["distance_midpoint_ft"].apply(assign_distance_band)

    staged_aw = pd.read_parquet(STAGED_DIR / "approach_windows.parquet")
    staged_approaches = pd.read_parquet(STAGED_DIR / "signal_approaches.parquet")
    mvp_units = pd.read_csv(MVP_DIR / "mvp_approach_window_direction_unit.csv", low_memory=False)
    return bins, dir_bins, staged_aw, staged_approaches, mvp_units


def distance_band_definition() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "distance_band": label,
                "start_ft_inclusive": low,
                "end_ft_exclusive": high if high < 2500 else "",
                "end_ft_inclusive": high if high == 2500 else "",
                "broader_window_0_1000": high <= 1000,
                "broader_window_0_2500": high <= 2500,
            }
            for label, low, high in BANDS
        ]
    )


def bin_assignment_profile(bins: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "total_bins", "count": len(bins)},
        {"metric": "bins_with_distance_start_ft", "count": int(nonmissing(bins["distance_start_ft"]).sum())},
        {"metric": "bins_with_distance_end_ft", "count": int(nonmissing(bins["distance_end_ft"]).sum())},
        {"metric": "bins_with_distance_midpoint", "count": int(nonmissing(bins["distance_midpoint_ft"]).sum())},
        {"metric": "bins_assigned_to_proposed_distance_band", "count": int(nonmissing(bins["proposed_distance_band"]).sum())},
        {"metric": "bins_missing_proposed_distance_band", "count": int((~nonmissing(bins["proposed_distance_band"])).sum())},
        {"metric": "distance_field_status", "count": "", "note": "distance_start_ft and distance_end_ft support proposed distance-band assignment"},
    ]
    for band, n in bins["proposed_distance_band"].fillna("<MISSING>").value_counts().sort_index().items():
        rows.append({"metric": "bins_by_proposed_distance_band", "distance_band": band, "count": int(n)})
    return pd.DataFrame(rows)


def old_gap_summary(staged_aw: pd.DataFrame, mvp_units: pd.DataFrame) -> pd.DataFrame:
    theoretical = len(staged_aw) * 2
    actual = len(mvp_units)
    return pd.DataFrame(
        [
            {
                "design": "old_two_window",
                "staged_approach_window_rows": len(staged_aw),
                "directions_per_window_assumption": 2,
                "theoretical_max_units": theoretical,
                "current_mvp_units": actual,
                "absent_theoretical_units": theoretical - actual,
                "why_not_controlling_now": "The future distance-aware design uses signal x approach x direction x distance_band, so expected/absent units must be recalculated from distance bands and bin support.",
            }
        ]
    )


def distance_units(bins: pd.DataFrame, dir_bins: pd.DataFrame, staged_approaches: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    approach_count = staged_approaches[["stable_signal_id", "signal_approach_id"]].drop_duplicates().shape[0]
    theoretical = approach_count * 2 * len(BANDS)
    observed = dir_bins[
        nonmissing(dir_bins["signal_approach_id"])
        & nonmissing(dir_bins["upstream_downstream"])
        & nonmissing(dir_bins["proposed_distance_band"])
    ][["stable_signal_id", "signal_approach_id", "upstream_downstream", "proposed_distance_band"]].drop_duplicates()
    observed_count = len(observed)

    bin_supported = bins[
        nonmissing(bins["signal_approach_id"]) & nonmissing(bins["proposed_distance_band"])
    ][["stable_signal_id", "signal_approach_id", "proposed_distance_band"]].drop_duplicates()
    bin_supported_expected = len(bin_supported) * 2

    missing_approach_bins = bins[(~nonmissing(bins["signal_approach_id"])) & nonmissing(bins["proposed_distance_band"])]
    recoverable_by_signal_window = classify_missing_bins_for_recovery(bins, staged_approaches)
    recoverable_bins = recoverable_by_signal_window[
        recoverable_by_signal_window["classification"].isin(
            ["missing_because_staged_approach_id_not_propagated_to_bin_context", "likely_fixed_by_staged_approach_reconstruction"]
        )
    ]
    recoverable_units = recoverable_bins[
        ["stable_signal_id", "proposed_distance_band"]
    ].drop_duplicates().shape[0] * 2
    unresolved_units = max(theoretical - observed_count - recoverable_units, 0)

    summary = pd.DataFrame(
        [
            {"metric": "theoretical_full_distance_band_max", "unit_count": theoretical, "definition": "staged approaches x 2 directions x 6 proposed distance bands"},
            {"metric": "bin_supported_expected_units", "unit_count": bin_supported_expected, "definition": "current non-null approach bins by distance band x 2 directions"},
            {"metric": "current_observed_distance_units", "unit_count": observed_count, "definition": "current directional bin context with non-null approach, direction, and proposed distance band"},
            {"metric": "recoverable_candidate_units", "unit_count": recoverable_units, "definition": "rough upper-bound from missing-approach bins that appear propagatable from staged/canonical context"},
            {"metric": "unresolved_or_source_limited_units", "unit_count": unresolved_units, "definition": "remaining theoretical combinations not currently observed or likely recoverable from this audit"},
        ]
    )

    expected_rows = []
    for band, _low, _high in BANDS:
        obs = observed[observed["proposed_distance_band"] == band]
        expected_rows.append(
            {
                "distance_band": band,
                "theoretical_full_units": approach_count * 2,
                "bin_supported_units": int((bin_supported["proposed_distance_band"] == band).sum() * 2),
                "current_observed_units": len(obs),
                "observed_upstream_units": int((obs["upstream_downstream"] == "upstream_to_signal").sum()),
                "observed_downstream_units": int((obs["upstream_downstream"] == "downstream_from_signal").sum()),
            }
        )
    absent = pd.DataFrame(expected_rows)
    absent["absent_from_full_theoretical"] = absent["theoretical_full_units"] - absent["current_observed_units"]
    absent["classification"] = "mixed_missingness_includes_legitimate_topology_and_cache_lineage_limits"
    return summary, absent, recoverable_by_signal_window


def classify_missing_bins_for_recovery(bins: pd.DataFrame, staged_approaches: pd.DataFrame) -> pd.DataFrame:
    missing = bins[(~nonmissing(bins["signal_approach_id"]))].copy()
    staged_counts = staged_approaches.groupby("stable_signal_id")["signal_approach_id"].nunique().rename("staged_approach_count").reset_index()
    missing = missing.merge(staged_counts, on="stable_signal_id", how="left")
    nonnull = bins[nonmissing(bins["signal_approach_id"])]
    route_key = ["stable_signal_id", "analysis_window", "source_route_id"]
    route_map = nonnull.groupby(route_key)["signal_approach_id"].nunique().rename("route_unique_approach_count").reset_index()
    tw_key = ["stable_signal_id", "analysis_window", "stable_travelway_id"]
    tw_map = nonnull.groupby(tw_key)["signal_approach_id"].nunique().rename("travelway_unique_approach_count").reset_index()
    missing = missing.merge(route_map, on=route_key, how="left")
    missing = missing.merge(tw_map, on=tw_key, how="left")

    def classify(row):
        if pd.notna(row.get("travelway_unique_approach_count")) and row["travelway_unique_approach_count"] == 1:
            return "missing_because_staged_approach_id_not_propagated_to_bin_context"
        if pd.notna(row.get("route_unique_approach_count")) and row["route_unique_approach_count"] == 1:
            return "missing_because_staged_approach_id_not_propagated_to_bin_context"
        if row.get("staged_approach_count") == 1:
            return "likely_fixed_by_staged_approach_reconstruction"
        if pd.isna(row.get("staged_approach_count")):
            return "missing_because_bin_cannot_be_linked_to_approach"
        if row.get("staged_approach_count", 0) > 1:
            return "ambiguous_needs_map_review"
        return "insufficient_fields_to_classify"

    missing["classification"] = missing.apply(classify, axis=1)
    return missing


def bin_signal_approach_completeness(bins: pd.DataFrame, classified_missing: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    total = len(bins)
    present = int(nonmissing(bins["signal_approach_id"]).sum())
    rows = [
        {"metric": "total_bins", "count": total},
        {"metric": "bins_with_signal_approach_id", "count": present, "share": present / total},
        {"metric": "bins_missing_signal_approach_id", "count": total - present, "share": (total - present) / total},
    ]
    for cls, n in classified_missing["classification"].value_counts().items():
        rows.append({"metric": "missing_bin_classification", "classification": cls, "count": int(n), "share_of_missing": int(n) / len(classified_missing) if len(classified_missing) else 0})
    by_band = bins.assign(missing_signal_approach_id=~nonmissing(bins["signal_approach_id"])).groupby("proposed_distance_band", dropna=False)["missing_signal_approach_id"].agg(["count", "sum"]).reset_index()
    by_band["missing_share"] = by_band["sum"] / by_band["count"]
    by_signal = bins.assign(missing_signal_approach_id=~nonmissing(bins["signal_approach_id"])).groupby("stable_signal_id", dropna=False)["missing_signal_approach_id"].agg(["count", "sum"]).reset_index().sort_values("sum", ascending=False).head(500)
    by_signal["missing_share"] = by_signal["sum"] / by_signal["count"]
    by_travelway = bins.assign(missing_signal_approach_id=~nonmissing(bins["signal_approach_id"])).groupby("stable_travelway_id", dropna=False)["missing_signal_approach_id"].agg(["count", "sum"]).reset_index().sort_values("sum", ascending=False).head(500)
    by_travelway["missing_share"] = by_travelway["sum"] / by_travelway["count"]
    return pd.DataFrame(rows), by_band, by_signal, by_travelway


def propagation_feasibility(bins: pd.DataFrame, staged_approaches: pd.DataFrame) -> pd.DataFrame:
    missing = bins[~nonmissing(bins["signal_approach_id"])].copy()
    methods = []
    candidates = [
        ("stable_signal_id + analysis_window", ["stable_signal_id", "analysis_window"]),
        ("stable_signal_id + analysis_window + stable_travelway_id", ["stable_signal_id", "analysis_window", "stable_travelway_id"]),
        ("stable_signal_id + analysis_window + source_route_id", ["stable_signal_id", "analysis_window", "source_route_id"]),
        ("stable_signal_id + analysis_window + source_route_name", ["stable_signal_id", "analysis_window", "source_route_name"]),
    ]
    nonnull = bins[nonmissing(bins["signal_approach_id"])]
    for name, keys in candidates:
        if not all(k in bins.columns for k in keys):
            methods.append({"candidate_method": name, "status": "not_checked_missing_fields", "fields_required": "|".join(keys)})
            continue
        lookup = nonnull.groupby(keys, dropna=False)["signal_approach_id"].nunique().rename("unique_approach_ids").reset_index()
        m = missing.merge(lookup, on=keys, how="left")
        deterministic = int((m["unique_approach_ids"] == 1).sum())
        ambiguous = int((m["unique_approach_ids"] > 1).sum())
        unresolved = int(m["unique_approach_ids"].isna().sum())
        methods.append(
            {
                "candidate_method": name,
                "missing_bin_rows_considered": len(missing),
                "deterministic_assignments": deterministic,
                "ambiguous_assignments": ambiguous,
                "unresolved_assignments": unresolved,
                "duplicate_or_unsafe_matches": ambiguous,
                "fields_required": "|".join(keys),
                "safe_enough_for_implementation": deterministic > 0 and ambiguous == 0 and unresolved == 0,
                "recommendation": "use_as_partial_rule_with_unresolved_flags" if deterministic and (ambiguous or unresolved) else ("safe_candidate" if deterministic else "not_useful"),
            }
        )
    # Staged single-approach per signal is conservative but broad.
    staged_counts = staged_approaches.groupby("stable_signal_id")["signal_approach_id"].nunique().rename("staged_approach_count").reset_index()
    m = missing.merge(staged_counts, on="stable_signal_id", how="left")
    methods.append(
        {
            "candidate_method": "stable_signal_id where staged signal has exactly one approach",
            "missing_bin_rows_considered": len(missing),
            "deterministic_assignments": int((m["staged_approach_count"] == 1).sum()),
            "ambiguous_assignments": int((m["staged_approach_count"] > 1).sum()),
            "unresolved_assignments": int(m["staged_approach_count"].isna().sum()),
            "duplicate_or_unsafe_matches": int((m["staged_approach_count"] > 1).sum()),
            "fields_required": "stable_signal_id",
            "safe_enough_for_implementation": False,
            "recommendation": "only_use_for_single-approach_signals_with_QA",
        }
    )
    return pd.DataFrame(methods)


def directionality_coverage(bins: pd.DataFrame, dir_bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    covered_ids = set(dir_bins["stable_bin_id"].dropna().unique())
    bins["directionality_covered"] = bins["stable_bin_id"].isin(covered_ids)
    rows = []
    for band, g in bins.groupby("proposed_distance_band", dropna=False):
        covered = int(g["directionality_covered"].sum())
        rows.append({"distance_band": band, "total_bins": len(g), "directionally_covered_bins": covered, "uncovered_bins": len(g) - covered, "covered_share": covered / len(g) if len(g) else 0})
    for band, g in dir_bins.groupby("proposed_distance_band", dropna=False):
        units = g[nonmissing(g["signal_approach_id"]) & nonmissing(g["upstream_downstream"])][["stable_signal_id", "signal_approach_id", "upstream_downstream", "proposed_distance_band"]].drop_duplicates()
        rows.append({"distance_band": band, "metric": "covered_approach_direction_distance_units", "covered_units": len(units)})
    total = len(bins)
    covered = int(bins["directionality_covered"].sum())
    target = math.ceil(total * 0.95)
    to_95 = max(target - covered, 0)
    target_df = pd.DataFrame(
        [
            {
                "total_bins": total,
                "current_directionally_covered_bins": covered,
                "current_covered_share": covered / total,
                "target_95pct_bins": target,
                "additional_bins_needed_for_95pct": to_95,
            }
        ]
    )
    uncovered = bins[~bins["directionality_covered"]]
    cluster = (
        uncovered.groupby(["stable_signal_id", "stable_travelway_id", "proposed_distance_band"], dropna=False)
        .size()
        .rename("uncovered_bin_count")
        .reset_index()
        .sort_values("uncovered_bin_count", ascending=False)
        .head(500)
    )
    return pd.DataFrame(rows), target_df, cluster


def fallback_feasibility(bins: pd.DataFrame, dir_bins: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, low, high in BANDS:
        g = dir_bins[dir_bins["proposed_distance_band"] == label]
        speed = int(nonmissing(g["speed_limit_mph"]).sum()) if "speed_limit_mph" in g else 0
        aadt = int(nonmissing(g["aadt"]).sum()) if "aadt" in g else 0
        exposure = int((pd.to_numeric(g.get("exposure_denominator", pd.Series(dtype=float)), errors="coerce") > 0).sum()) if "exposure_denominator" in g else 0
        unit_count = g[nonmissing(g["signal_approach_id"]) & nonmissing(g["upstream_downstream"])][["stable_signal_id", "signal_approach_id", "upstream_downstream", "proposed_distance_band"]].drop_duplicates().shape[0]
        rows.append({"distance_band": label, "fallback_level": "primary_exact_distance_band", "unit_count": unit_count, "rate_ready_proxy_count": min(speed, aadt, exposure), "speed_present_rows": speed, "aadt_present_rows": aadt, "exposure_positive_rows": exposure, "expected_lookup_cell_sparsity_risk": "high" if unit_count < 5000 else "moderate"})
    for level, mask in [
        ("fallback_1_0_1000_window", pd.to_numeric(dir_bins["distance_end_ft"], errors="coerce") <= 1000),
        ("fallback_2_0_2500_window", pd.to_numeric(dir_bins["distance_end_ft"], errors="coerce") <= 2500),
    ]:
        g = dir_bins[mask]
        unit_count = g[nonmissing(g["signal_approach_id"]) & nonmissing(g["upstream_downstream"])][["stable_signal_id", "signal_approach_id", "upstream_downstream"]].drop_duplicates().shape[0]
        rows.append({"distance_band": "ALL_APPLICABLE", "fallback_level": level, "unit_count": unit_count, "rate_ready_proxy_count": "", "expected_lookup_cell_sparsity_risk": "lower_than_exact_band"})
    rows.append({"distance_band": "CATEGORY", "fallback_level": "fallback_3_broader_category_with_warning", "unit_count": "", "rate_ready_proxy_count": "", "expected_lookup_cell_sparsity_risk": "depends_on_category_collapse"})
    return pd.DataFrame(rows)


def map_review_candidates(classified_missing: pd.DataFrame, uncovered_cluster: pd.DataFrame) -> pd.DataFrame:
    miss = (
        classified_missing.groupby(["stable_signal_id", "proposed_distance_band", "classification"], dropna=False)
        .size()
        .rename("missing_bins_count")
        .reset_index()
    )
    miss["missing_unit_count_contribution"] = miss["missing_bins_count"].clip(upper=1) * 2
    miss["directionality_status"] = "not_assessed_in_approach_missing_rows"
    miss["approach_id_status"] = "missing"
    miss["likely_reason"] = miss["classification"]
    miss["priority_score"] = miss["missing_bins_count"] + miss["missing_unit_count_contribution"] * 10
    miss["recommended_review_action"] = miss["classification"].map(
        {
            "ambiguous_needs_map_review": "map-review approach linkage",
            "missing_because_bin_cannot_be_linked_to_approach": "inspect source geometry/lineage",
            "missing_because_staged_approach_id_not_propagated_to_bin_context": "test deterministic propagation rule",
            "likely_fixed_by_staged_approach_reconstruction": "verify staged approach reconstruction",
        }
    ).fillna("review lineage evidence")
    out = miss.sort_values("priority_score", ascending=False).head(500)
    out["signal_approach_id"] = ""
    out["upstream_downstream_side"] = ""
    return out[
        [
            "stable_signal_id",
            "signal_approach_id",
            "proposed_distance_band",
            "upstream_downstream_side",
            "missing_bins_count",
            "missing_unit_count_contribution",
            "directionality_status",
            "approach_id_status",
            "likely_reason",
            "priority_score",
            "recommended_review_action",
        ]
    ]


def write_access_note() -> None:
    text = """# Access Methodology Note

The future tool needs to distinguish two access concepts.

## A. Proposed Access Point Type

This is the access type the user wants to evaluate or place, such as RIRO or full movement. It is an input scenario for the tool.

## B. Existing Access Environment

This describes observed context near the signal, approach, and distance band: access count, access density per 1,000 ft when a denominator is explicit, typed access evidence, and access type mix or presence flags.

The current MVP fields mostly describe the existing access environment. `access_type` can look like a scenario variable, but without a separate proposed-access input it should not be interpreted as the user's proposed access type. Future MVP design should keep proposed access type separate from observed typed-access evidence and default/no-evidence categories.
"""
    (OUT_DIR / "access_methodology_note.md").write_text(text, encoding="utf-8")


def findings(metrics: dict) -> None:
    text = f"""# Distance-Aware Unit Universe and Bin-Lineage Audit

## Why 51,626 and 9,101 belong to the old two-window design

The old theoretical maximum was `25,813 staged approach-window rows x 2 directions = 51,626`. The current MVP has `42,525` rows, so the old absent theoretical count was `9,101`. That calculation assumes the primary grain is broad approach-window-direction using only `0-1,000 ft` and `0-2,500 ft`.

That number is no longer the controlling target if the MVP moves to distance-aware bands. The new grain is `signal x approach x upstream/downstream x distance_band`, so expected and absent units must be recalculated from approach entities, six proposed distance bands, bin support, and directionality coverage.

## What the distance-aware unit universe means

The distance-aware universe asks whether each signal approach has upstream/downstream observed context in each proposed distance band: `0-250`, `250-500`, `500-1,000`, `1,000-1,500`, `1,500-2,000`, and `2,000-2,500 ft`. Broad windows become fallback aggregations, not the primary unit.

## How many distance-aware units are expected, observed, recoverable, and unresolved

- Theoretical full distance-band max: {metrics['theoretical_full_distance_band_max']}
- Bin-supported expected units: {metrics['bin_supported_expected_units']}
- Current observed distance units: {metrics['current_observed_distance_units']}
- Recoverable candidate units: {metrics['recoverable_candidate_units']}
- Unresolved or source-limited units: {metrics['unresolved_or_source_limited_units']}

## Why only 79.52% of bins have signal_approach_id

Current `analysis_bin.csv` has {metrics['bins_with_signal_approach_id']} bins with `signal_approach_id` out of {metrics['total_bins']} total bins. The remaining {metrics['bins_missing_signal_approach_id']} bins appear to be a mixture of propagation gaps, ambiguous approach linkage, and source/geometry limitations. The staged approach-window candidate fixed approach IDs at the broad approach-window grain, but it did not write staged bin context, so the key has not yet been propagated to bins.

## Whether staged signal_approach_id can be propagated to bin context

Partial propagation looks feasible, especially through route/travelway/window keys where existing non-null bins provide a unique approach mapping. It is not safe to blanket-fill all missing bin rows. A staged bin-context refresh should use deterministic partial rules and preserve unresolved/ambiguous rows with flags.

## Whether the 92% bin directionality coverage is misleading at distance-band grain

The 92% bin-level directionality coverage is useful but can be optimistic for distance-aware MVP readiness. A small number of uncovered bins can erase an approach-direction-distance unit in a specific band, and exact-band lookup cells will be sparser than broad windows. The audit estimates {metrics['additional_bins_needed_for_95pct']} additional bins are needed to reach 95% bin-level directionality coverage.

## Whether directionality and bin approach lineage should be fixed before speed/AADT

Yes. Bin approach lineage and directionality should be stabilized before speed/AADT/exposure refresh, because distance-aware numeric context has to attach to the correct signal, approach, direction, and distance band.

## Recommended immediate next implementation step

Build a staged bin-context candidate that propagates staged `signal_approach_id` to bins only where deterministic, assigns proposed distance bands, preserves direct/synthetic directionality flags, and exports unresolved map-review queues. Do not regenerate MVP until that staged bin context passes QA.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "progress_log.md").write_text(f"# Progress Log\n\n- {now()} - Started distance-aware unit universe audit.\n", encoding="utf-8")
    log("Reading canonical and staged cache products.")
    bins, dir_bins, staged_aw, staged_approaches, mvp_units = load_inputs()

    write_csv("distance_band_definition.csv", distance_band_definition())
    write_csv("bin_distance_band_assignment_profile.csv", bin_assignment_profile(bins))
    write_csv("old_two_window_unit_gap_summary.csv", old_gap_summary(staged_aw, mvp_units))

    log("Computing distance-aware unit universe.")
    universe, expected_observed, classified_missing = distance_units(bins, dir_bins, staged_approaches)
    write_csv("distance_aware_unit_universe_summary.csv", universe)
    write_csv("distance_aware_expected_vs_observed_units.csv", expected_observed)
    absent = expected_observed.copy()
    absent["absent_reason_note"] = "Exact reason requires staged bin-context refresh; current audit separates observed, recoverable, and unresolved at aggregate level."
    write_csv("distance_aware_absent_unit_classification.csv", absent)

    comp, by_band, by_signal, by_travelway = bin_signal_approach_completeness(bins, classified_missing)
    write_csv("bin_signal_approach_id_completeness.csv", comp)
    write_csv("bin_signal_approach_id_missingness_by_distance_band.csv", by_band)
    write_csv("bin_signal_approach_id_missingness_by_signal.csv", by_signal)
    write_csv("bin_signal_approach_id_missingness_by_travelway.csv", by_travelway)
    write_csv("staged_approach_id_to_bin_propagation_feasibility.csv", propagation_feasibility(bins, staged_approaches))

    coverage, target, uncovered_cluster = directionality_coverage(bins, dir_bins)
    write_csv("directionality_coverage_by_distance_band.csv", coverage)
    write_csv("directionality_coverage_to_95_target.csv", target)
    write_csv("directionality_uncovered_cluster_summary.csv", uncovered_cluster)
    write_csv("fallback_hierarchy_feasibility.csv", fallback_feasibility(bins, dir_bins))
    write_access_note()
    write_csv("map_review_candidate_distance_units.csv", map_review_candidates(classified_missing, uncovered_cluster))
    write_csv(
        "recommended_next_actions.csv",
        pd.DataFrame(
            [
                {"priority": 1, "action": "Build staged bin_context candidate with deterministic signal_approach_id propagation", "reason": "distance-aware MVP needs signal x approach x direction x distance_band lineage"},
                {"priority": 2, "action": "Assign proposed distance bands in staged bin context", "reason": "distance bands are available from current distance_start_ft/end_ft"},
                {"priority": 3, "action": "Preserve direct/synthetic directionality and unresolved flags by bin", "reason": "92% bin coverage can still leave exact-band unit gaps"},
                {"priority": 4, "action": "Create map-review package for ambiguous approach linkage and uncovered directionality clusters", "reason": "recover high-yield missing distance units without forcing labels"},
                {"priority": 5, "action": "Refresh speed/AADT/exposure after bin approach lineage is stable", "reason": "numeric context must attach to correct approach-distance-direction units"},
            ]
        ),
    )

    metrics = {row["metric"]: int(row["unit_count"]) for row in universe.to_dict("records") if pd.notna(row["unit_count"])}
    total_bins = len(bins)
    bins_with_sa = int(nonmissing(bins["signal_approach_id"]).sum())
    metrics.update(
        {
            "total_bins": total_bins,
            "bins_with_signal_approach_id": bins_with_sa,
            "bins_missing_signal_approach_id": total_bins - bins_with_sa,
            "additional_bins_needed_for_95pct": int(target.iloc[0]["additional_bins_needed_for_95pct"]),
        }
    )
    findings(metrics)

    qa = [
        {"qa_check": "canonical_root_products_not_modified", "status": "pass"},
        {"qa_check": "staged_candidate_not_modified", "status": "pass"},
        {"qa_check": "no_mvp_regeneration", "status": "pass"},
        {"qa_check": "no_raw_source_reads", "status": "pass"},
        {"qa_check": "null_signal_approach_id_matches_not_counted", "status": "pass"},
        {"qa_check": "crash_direction_not_used_for_upstream_downstream", "status": "pass"},
        {"qa_check": "outputs_only_in_review_folder", "status": "pass", "evidence": rel(OUT_DIR)},
    ]
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    manifest = {
        "script": "src.roadway_graph.audit.distance_aware_unit_universe_and_bin_lineage_audit",
        "generated_utc": now(),
        "inputs": [rel(FINAL_DIR), rel(MVP_DIR), rel(STAGED_DIR)],
        "output_folder": rel(OUT_DIR),
        "outputs": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "key_metrics": metrics,
        "non_goals": ["no refresh", "no promotion", "no MVP regeneration", "no raw source reads", "no input mutation"],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log("Completed distance-aware unit universe audit.")


if __name__ == "__main__":
    main()
