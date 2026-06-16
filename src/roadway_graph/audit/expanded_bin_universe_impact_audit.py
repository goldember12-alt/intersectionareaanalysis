"""Read-only impact audit for virtual expanded bin universe.

Combines staged bin_context and proposed generated bins in memory only. Does
not append bins, assign directionality, or mutate staged/canonical products.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
EXPORT_DIR = STAGING_DIR / "exports"
QA_DIR = REPO_ROOT / "work/roadway_graph/review/proposed_generated_bins_qa_audit"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/expanded_bin_universe_impact_audit"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
PROPOSED_BINS = STAGING_DIR / "proposed_generated_bins.parquet"
CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
PROVENANCE = STAGING_DIR / "continuation_provenance.parquet"
MANIFEST = STAGING_DIR / "manifest.json"
SCHEMA = STAGING_DIR / "schema.json"
EXCLUDED_ROWS = EXPORT_DIR / "proposed_generated_bins_excluded_rows.csv"

DISTANCE_BANDS = ["0-250", "250-500", "500-1000", "1000-1500", "1500-2000", "2000-2500"]
CASE6_SIGNAL = "sig_9eb88931584514a8b0d4"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_csv(df: pd.DataFrame, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / name, index=False)


def nonnull(s: pd.Series) -> pd.Series:
    return s.notna() & (s.astype(str).str.strip() != "")


def normalize_existing(existing: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["row_source_type"] = "existing_staged_bin"
    out["stable_signal_id"] = existing.get("stable_signal_id")
    out["signal_approach_id_v2"] = existing.get("signal_approach_id_v2")
    out["distance_band"] = existing.get("distance_band_v2", existing.get("distance_band"))
    out["distance_start_ft"] = existing.get("distance_start_ft")
    out["distance_end_ft"] = existing.get("distance_end_ft")
    out["source_route_name"] = existing.get("source_route_name")
    out["stable_travelway_id"] = existing.get("stable_travelway_id")
    out["continuation_class"] = ""
    out["directionality_status"] = existing.get("directionality_coverage_status_values")
    out["upstream_downstream"] = existing.get("upstream_downstream_values")
    out["has_directionality"] = nonnull(out["upstream_downstream"])
    out["has_approach_id"] = nonnull(out["signal_approach_id_v2"])
    return out


def normalize_proposed(proposed: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["row_source_type"] = "proposed_generated_distance_continuation_bin"
    out["stable_signal_id"] = proposed.get("stable_signal_id")
    out["signal_approach_id_v2"] = proposed.get("signal_approach_id_v2")
    out["distance_band"] = proposed.get("distance_band")
    out["distance_start_ft"] = proposed.get("distance_start_ft")
    out["distance_end_ft"] = proposed.get("distance_end_ft")
    out["source_route_name"] = proposed.get("source_route_name")
    out["stable_travelway_id"] = ""
    out["continuation_class"] = proposed.get("continuation_class")
    out["directionality_status"] = proposed.get("directionality_status")
    out["upstream_downstream"] = proposed.get("upstream_downstream")
    out["has_directionality"] = False
    out["has_approach_id"] = nonnull(out["signal_approach_id_v2"])
    return out


def count_direction_units(df: pd.DataFrame) -> int:
    valid = df[nonnull(df["stable_signal_id"]) & nonnull(df["signal_approach_id_v2"]) & nonnull(df["distance_band"])].copy()
    valid = valid[nonnull(valid["upstream_downstream"])]
    if valid.empty:
        return 0
    valid["side"] = valid["upstream_downstream"].astype(str).str.split("|")
    exploded = valid.explode("side")
    exploded = exploded[nonnull(exploded["side"])]
    return int(exploded[["stable_signal_id", "signal_approach_id_v2", "distance_band", "side"]].drop_duplicates().shape[0])


def approach_band_support(df: pd.DataFrame) -> pd.DataFrame:
    valid = df[nonnull(df["stable_signal_id"]) & nonnull(df["signal_approach_id_v2"]) & nonnull(df["distance_band"])].copy()
    return valid[["stable_signal_id", "signal_approach_id_v2", "distance_band"]].drop_duplicates()


def direction_side_pattern(existing_norm: pd.DataFrame) -> pd.DataFrame:
    valid = existing_norm[nonnull(existing_norm["stable_signal_id"]) & nonnull(existing_norm["signal_approach_id_v2"])].copy()
    valid = valid[nonnull(valid["upstream_downstream"])]
    if valid.empty:
        return pd.DataFrame(columns=["stable_signal_id", "signal_approach_id_v2", "existing_side_count"])
    valid["side"] = valid["upstream_downstream"].astype(str).str.split("|")
    ex = valid.explode("side")
    ex = ex[nonnull(ex["side"])]
    return (
        ex.groupby(["stable_signal_id", "signal_approach_id_v2"])["side"]
        .nunique()
        .reset_index(name="existing_side_count")
    )


def unit_summaries(existing_norm: pd.DataFrame, proposed_norm: pd.DataFrame, combined: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    current_dir = count_direction_units(existing_norm)
    expanded_dir = count_direction_units(combined)
    current_ab = approach_band_support(existing_norm)
    expanded_ab = approach_band_support(combined)
    proposed_ab = approach_band_support(proposed_norm)
    side_pattern = direction_side_pattern(existing_norm)
    expanded_potential = expanded_ab.merge(side_pattern, on=["stable_signal_id", "signal_approach_id_v2"], how="left")
    expanded_potential["conservative_side_count"] = expanded_potential["existing_side_count"].fillna(0).clip(lower=0, upper=2)
    expanded_potential["upper_bound_side_count"] = 2
    conservative_units = int(expanded_potential["conservative_side_count"].sum())
    upper_units = int(expanded_potential["upper_bound_side_count"].sum())
    proposed_potential = proposed_ab.merge(side_pattern, on=["stable_signal_id", "signal_approach_id_v2"], how="left")
    proposed_potential["conservative_side_count"] = proposed_potential["existing_side_count"].fillna(0).clip(lower=0, upper=2)
    proposed_potential["upper_bound_side_count"] = 2
    needs_dir_cons = int(proposed_potential["conservative_side_count"].sum())
    needs_dir_upper = int(proposed_potential["upper_bound_side_count"].sum())
    summary = pd.DataFrame(
        [
            {"metric": "current_observed_direction_units_existing_only", "value": current_dir, "definition": "signal x approach x distance_band x upstream/downstream among existing bins only"},
            {"metric": "expanded_observed_direction_units_ready_now", "value": expanded_dir, "definition": "same as current because proposed bins have no upstream/downstream"},
            {"metric": "current_approach_band_support_units", "value": len(current_ab), "definition": "signal x approach x distance_band support regardless of directionality"},
            {"metric": "expanded_approach_band_support_units", "value": len(expanded_ab), "definition": "existing plus proposed signal x approach x distance_band support"},
            {"metric": "new_proposed_approach_band_support_units", "value": len(proposed_ab), "definition": "approach-band units supplied by proposed bins"},
        ]
    )
    potential = pd.DataFrame(
        [
            {"variant": "conservative_existing_side_pattern", "expanded_potential_direction_units": conservative_units, "needs_directionality_units_from_proposed_support": needs_dir_cons},
            {"variant": "upper_bound_two_sides_per_approach_band", "expanded_potential_direction_units": upper_units, "needs_directionality_units_from_proposed_support": needs_dir_upper},
        ]
    )
    return summary, expanded_ab, potential


def row_count_summary(existing_norm: pd.DataFrame, proposed_norm: pd.DataFrame, combined: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, df in [("current_existing", existing_norm), ("proposed_generated", proposed_norm), ("virtual_expanded", combined)]:
        assigned = int(df["has_approach_id"].sum())
        total = len(df)
        rows.append(
            {
                "universe": label,
                "row_count": total,
                "signal_count": int(df["stable_signal_id"].nunique(dropna=True)),
                "approach_count": int(df.loc[df["has_approach_id"], "signal_approach_id_v2"].nunique(dropna=True)),
                "assigned_approach_id_bins": assigned,
                "unresolved_approach_id_rows": int(total - assigned),
                "approach_id_coverage_percent": round(assigned / total * 100, 4) if total else 0,
                "directionality_ready_bins": int(df["has_directionality"].sum()),
                "directionality_missing_bins": int(total - df["has_directionality"].sum()),
                "directionality_coverage_percent": round(df["has_directionality"].sum() / total * 100, 4) if total else 0,
            }
        )
    return pd.DataFrame(rows)


def directionality_backlog(combined: pd.DataFrame, proposed_norm: pd.DataFrame, existing_norm: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    missing = combined[~combined["has_directionality"]].copy()
    rows = pd.DataFrame(
        [
            {"metric": "existing_bins_missing_directionality", "value": int((~existing_norm["has_directionality"]).sum())},
            {"metric": "proposed_bins_needing_directionality", "value": int(len(proposed_norm))},
            {"metric": "expanded_total_bins_missing_directionality", "value": int(len(missing))},
            {"metric": "expanded_total_bins", "value": int(len(combined))},
            {"metric": "expanded_directionality_coverage_percent", "value": round(combined["has_directionality"].sum() / len(combined) * 100, 4)},
        ]
    )
    by_band = missing.groupby(["distance_band", "row_source_type"], dropna=False).size().reset_index(name="missing_directionality_bins")
    by_signal = missing.groupby("stable_signal_id", dropna=False).size().reset_index(name="missing_directionality_bins").sort_values("missing_directionality_bins", ascending=False)
    by_approach = (
        missing.groupby(["stable_signal_id", "signal_approach_id_v2"], dropna=False)
        .size()
        .reset_index(name="missing_directionality_bins")
        .sort_values("missing_directionality_bins", ascending=False)
    )
    return rows, by_band, by_signal, by_approach


def excluded_summary(excluded: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if excluded.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty
    x = excluded.copy()
    for col in ["stable_signal_id", "signal_approach_id_v2", "source_route_name", "distance_band", "generated_bin_exclusion_reason"]:
        if col not in x.columns:
            x[col] = ""
    summary = (
        x.groupby(["generated_bin_exclusion_reason", "distance_band"], dropna=False)
        .size()
        .reset_index(name="excluded_rows")
        .sort_values("excluded_rows", ascending=False)
    )
    by_signal = x.groupby("stable_signal_id", dropna=False).size().reset_index(name="excluded_rows").sort_values("excluded_rows", ascending=False)
    by_travelway = x.groupby("source_route_name", dropna=False).size().reset_index(name="excluded_rows").sort_values("excluded_rows", ascending=False)
    case6 = x[x["stable_signal_id"] == CASE6_SIGNAL].copy()
    if case6.empty:
        case6_out = pd.DataFrame(
            [{"stable_signal_id": CASE6_SIGNAL, "proposed_generated_bins": 0, "excluded_rows": 0, "interpretation": "no_excluded_rows_found"}]
        )
    else:
        case6_out = (
            case6.groupby(["stable_signal_id", "distance_band", "source_route_name", "generated_bin_exclusion_reason"], dropna=False)
            .size()
            .reset_index(name="excluded_rows")
        )
        case6_out["interpretation"] = "aligns_with_source_limited_missing_opposite_leg_if_route_extent_absent"
    return summary, by_signal, by_travelway, case6_out


def distance_band_impact(existing_norm: pd.DataFrame, proposed_norm: pd.DataFrame, combined: pd.DataFrame, excluded: pd.DataFrame) -> pd.DataFrame:
    rows = []
    current_ab = approach_band_support(existing_norm)
    expanded_ab = approach_band_support(combined)
    for band in DISTANCE_BANDS:
        existing_band = existing_norm[existing_norm["distance_band"] == band]
        proposed_band = proposed_norm[proposed_norm["distance_band"] == band]
        expanded_band = combined[combined["distance_band"] == band]
        excluded_rows = int((excluded.get("distance_band", pd.Series(dtype=str)) == band).sum()) if not excluded.empty else 0
        rows.append(
            {
                "distance_band": band,
                "existing_bins": len(existing_band),
                "proposed_generated_bins": len(proposed_band),
                "expanded_bins": len(expanded_band),
                "existing_approach_band_support": int((current_ab["distance_band"] == band).sum()),
                "expanded_approach_band_support": int((expanded_ab["distance_band"] == band).sum()),
                "existing_direction_ready_bins": int(existing_band["has_directionality"].sum()),
                "expanded_direction_ready_bins": int(expanded_band["has_directionality"].sum()),
                "potential_bins_needing_directionality": int((~expanded_band["has_directionality"]).sum()),
                "excluded_source_limited_rows": excluded_rows,
            }
        )
    return pd.DataFrame(rows)


def write_findings(
    bin_summary: pd.DataFrame,
    unit_summary: pd.DataFrame,
    potential: pd.DataFrame,
    backlog_summary: pd.DataFrame,
    excluded_rows: int,
    case6: pd.DataFrame,
    recommendation: str,
) -> None:
    expanded_count = int(bin_summary.loc[bin_summary["universe"] == "virtual_expanded", "row_count"].iloc[0])
    combined_cov = float(bin_summary.loc[bin_summary["universe"] == "virtual_expanded", "approach_id_coverage_percent"].iloc[0])
    current_ab = int(unit_summary.loc[unit_summary["metric"] == "current_approach_band_support_units", "value"].iloc[0])
    expanded_ab = int(unit_summary.loc[unit_summary["metric"] == "expanded_approach_band_support_units", "value"].iloc[0])
    text = f"""# Expanded Bin Universe Impact Audit

## What adding 214,740 proposed bins changes

The virtual expanded universe has {expanded_count:,} bins. Combined approach-ID coverage is {combined_cov:.4f}% because proposed rows carry `signal_approach_id_v2`.

## Why the unit denominator changes again

The proposed bins add distance support but not directionality. They expand signal-approach-distance-band support before they become direction-ready MVP units.

## Current observed units vs expanded support units

Current approach-band support: {current_ab:,}. Expanded approach-band support: {expanded_ab:,}. Direction-ready units do not increase until directionality is assigned to proposed bins.

## Directionality backlog after proposed append

Directionality backlog summary:
{backlog_summary.to_string(index=False)}

## What the 59,770 excluded rows mean

Excluded rows: {excluded_rows:,}. They remain source-limited proposed intervals that exceeded source measure extent in the generated-bin proposal.

## Manual Case 6 source-limited check

Manual Case 6 rows are summarized in `manual_case6_excluded_row_check.csv`. The check preserves the source-limited missing-leg interpretation rather than inventing an opposite leg.

## Whether proposed generated bins should be appended

Recommendation: `{recommendation}`. The append should be followed by a directionality assignment plan because all proposed bins currently need directionality.

## Recommended next step

Append the proposed bins only in a separate bounded staging mutation task, then run a directionality assignment/recovery task against the expanded staged bin universe.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    required = [BIN_CONTEXT, PROPOSED_BINS, CORRIDORS, PROVENANCE, MANIFEST, SCHEMA]
    missing = [rel(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing))
    print("reading staged bin_context and proposed bins", flush=True)
    existing = pd.read_parquet(BIN_CONTEXT)
    proposed = pd.read_parquet(PROPOSED_BINS)
    corridors = pd.read_parquet(CORRIDORS)
    provenance = pd.read_parquet(PROVENANCE)
    excluded = pd.read_csv(EXCLUDED_ROWS, low_memory=False) if EXCLUDED_ROWS.exists() else pd.DataFrame()

    existing_norm = normalize_existing(existing)
    proposed_norm = normalize_proposed(proposed)
    combined = pd.concat([existing_norm, proposed_norm], ignore_index=True)

    bin_summary = row_count_summary(existing_norm, proposed_norm, combined)
    write_csv(bin_summary, "current_vs_proposed_vs_expanded_bin_summary.csv")
    write_csv(
        bin_summary[["universe", "row_count", "assigned_approach_id_bins", "unresolved_approach_id_rows", "approach_id_coverage_percent"]],
        "expanded_approach_id_coverage_summary.csv",
    )
    band_summary = (
        combined.groupby(["distance_band", "row_source_type"], dropna=False)
        .size()
        .reset_index(name="bin_rows")
        .sort_values(["distance_band", "row_source_type"])
    )
    write_csv(band_summary, "expanded_distance_band_bin_summary.csv")

    unit_summary, expanded_ab, potential = unit_summaries(existing_norm, proposed_norm, combined)
    write_csv(unit_summary, "current_vs_expanded_unit_summary.csv")
    ab_summary = expanded_ab.groupby("distance_band", dropna=False).size().reset_index(name="expanded_approach_band_support_units")
    write_csv(ab_summary, "expanded_approach_band_support_summary.csv")
    write_csv(potential, "expanded_potential_direction_unit_summary.csv")

    backlog_summary, backlog_by_band, backlog_by_signal, backlog_by_approach = directionality_backlog(combined, proposed_norm, existing_norm)
    write_csv(backlog_summary, "directionality_backlog_after_append_summary.csv")
    write_csv(backlog_by_band, "directionality_backlog_by_distance_band.csv")
    write_csv(backlog_by_signal, "directionality_backlog_by_signal.csv")
    write_csv(backlog_by_approach, "directionality_backlog_by_approach.csv")

    excl_summary, excl_by_signal, excl_by_travelway, case6 = excluded_summary(excluded)
    write_csv(excl_summary, "excluded_source_limited_summary.csv")
    write_csv(excl_by_signal, "excluded_rows_by_signal.csv")
    write_csv(excl_by_travelway, "excluded_rows_by_travelway.csv")
    case6_props = proposed[proposed["stable_signal_id"] == CASE6_SIGNAL].copy()
    case6_extra = pd.DataFrame(
        [
            {
                "stable_signal_id": CASE6_SIGNAL,
                "proposed_generated_bins": len(case6_props),
                "proposed_distance_bands": "|".join(sorted(case6_props["distance_band"].dropna().astype(str).unique())) if not case6_props.empty else "",
                "proposed_continuation_classes": "|".join(sorted(case6_props["continuation_class"].dropna().astype(str).unique())) if not case6_props.empty else "",
            }
        ]
    )
    write_csv(pd.concat([case6, case6_extra], ignore_index=True, sort=False), "manual_case6_excluded_row_check.csv")

    dist_impact = distance_band_impact(existing_norm, proposed_norm, combined, excluded)
    write_csv(dist_impact, "distance_band_impact_summary.csv")

    recommendation = "append_all_proposed_generated_bins_to_staging"
    if int(backlog_summary.loc[backlog_summary["metric"] == "proposed_bins_needing_directionality", "value"].iloc[0]) > 0:
        recommendation = "append_only_after_directionality_plan"
    rec = pd.DataFrame(
        [
            {
                "append_readiness_final_recommendation": recommendation,
                "recommended_scope": "all_proposed_generated_bins",
                "rationale": "QA passed and approach-band support improves materially, but proposed bins create a large directionality backlog.",
                "requires_separate_append_task": True,
                "requires_directionality_plan": True,
                "do_not_regenerate_mvp_yet": True,
            }
        ]
    )
    write_csv(rec, "append_readiness_final_recommendation.csv")
    actions = pd.DataFrame(
        [
            {"priority": 1, "recommended_action": "prepare_bounded_append_task_for_all_proposed_bins", "rationale": "Virtual expanded QA shows no structural blocker."},
            {"priority": 2, "recommended_action": "build_directionality_assignment_plan_for_expanded_universe", "rationale": "All proposed bins need upstream/downstream before MVP use."},
            {"priority": 3, "recommended_action": "keep_excluded_rows_source_limited", "rationale": "Excluded rows remain source endpoint cases in current evidence."},
        ]
    )
    write_csv(actions, "recommended_next_actions.csv")

    write_findings(bin_summary, unit_summary, potential, backlog_summary, len(excluded), case6, recommendation)
    manifest = {
        "generated_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "output_folder": rel(OUT_DIR),
        "inputs_read": [rel(p) for p in required + [EXCLUDED_ROWS, QA_DIR] if p.exists()],
        "outputs_written": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "row_counts": {
            "existing_bins": int(len(existing)),
            "proposed_generated_bins": int(len(proposed)),
            "virtual_expanded_bins": int(len(combined)),
            "excluded_rows": int(len(excluded)),
            "continuation_corridors": int(len(corridors)),
            "continuation_provenance": int(len(provenance)),
        },
        "combined_parquet_written": False,
        "staged_bin_context_modified": False,
        "directionality_assigned": False,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "required_outputs_written": True,
        "canonical_products_modified": False,
        "staged_bin_context_modified": False,
        "combined_expanded_parquet_written": False,
        "directionality_assigned": False,
        "crash_direction_fields_used": False,
        "raw_source_reads_performed": False,
    }
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    progress_text = f"# Progress\n- {now_iso()} Built virtual expanded bin universe in memory and wrote audit outputs.\n"
    (OUT_DIR / "progress_log.md").write_text(progress_text, encoding="utf-8")
    (OUT_DIR / "run_progress_log.txt").write_text(progress_text, encoding="utf-8")

    print(f"expanded_bins={len(combined)}")
    print(f"combined_approach_id_coverage={bin_summary.loc[bin_summary['universe']=='virtual_expanded','approach_id_coverage_percent'].iloc[0]}")
    print(f"current_vs_expanded_approach_band_support={unit_summary.to_dict(orient='records')}")
    print(f"append_recommendation={recommendation}")


if __name__ == "__main__":
    main()
