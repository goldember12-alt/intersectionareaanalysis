"""Apply conflict-free source-corridor proposals to staged bin_context.

This is a bounded staging mutation. It updates only the staged final-leg refresh
candidate and derivative exports under that staging folder.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work" / "roadway_graph" / "analysis" / "_staging" / "final_leg_corrected_analysis_dataset_refresh_candidate"
EXPORTS = STAGING / "exports"
PROPOSAL_DIR = REPO / "work" / "roadway_graph" / "map_review" / "source_travelway_corridor_global_assignment_proposal"
SCRIPT_MODULE = "src.roadway_graph.apply_source_corridor_proposal_to_staged_bin_context"

ALLOWED_STATUSES = {
    "proposed_assign_source_corridor_unique",
    "proposed_assign_multi_row_chain_unique",
    "proposed_assign_long_row_clipped_unique",
    "proposed_assign_divided_carriageway_unique",
    "proposed_assign_source_limited_short_leg",
}
LOW_CONFIDENCE = {"low"}
UNRESOLVED_PATTERN = "ambiguous|unresolved|source_limited|insufficient"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def nonmissing(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>", "unknown_missing"]))


def write_csv(name: str, frame: pd.DataFrame) -> None:
    EXPORTS.mkdir(parents=True, exist_ok=True)
    frame.to_csv(EXPORTS / name, index=False)


def ambiguous_mask(frame: pd.DataFrame) -> pd.Series:
    return frame["signal_approach_id_v2"].isna() | frame["signal_approach_id_status"].astype(str).str.contains(
        UNRESOLVED_PATTERN, case=False, na=False
    )


def direction_count(value: Any) -> int:
    if pd.isna(value) or not str(value).strip():
        return 0
    return len([part for part in str(value).split("|") if part.strip()])


def distance_units(frame: pd.DataFrame, id_col: str = "signal_approach_id_v2") -> pd.DataFrame:
    needed = ["stable_signal_id", id_col, "distance_band_v2", "upstream_downstream_values"]
    if any(c not in frame.columns for c in needed):
        return pd.DataFrame()
    work = frame[needed].copy()
    work = work[nonmissing(work[id_col]) & nonmissing(work["distance_band_v2"])].copy()
    rows = []
    for _, row in work.iterrows():
        dirs = [p.strip() for p in str(row["upstream_downstream_values"]).split("|") if p.strip()]
        for direction in dirs:
            rows.append(
                {
                    "stable_signal_id": row["stable_signal_id"],
                    "signal_approach_id": row[id_col],
                    "distance_band_v2": row["distance_band_v2"],
                    "upstream_downstream": direction,
                }
            )
    if not rows:
        return pd.DataFrame(columns=["stable_signal_id", "signal_approach_id", "distance_band_v2", "upstream_downstream"])
    return pd.DataFrame(rows).drop_duplicates()


def update_json_metadata(path: Path, updater) -> None:
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    updated = updater(data)
    path.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_readme(path: Path, summary: dict[str, Any]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    marker = "\n## Source Corridor Proposal Apply\n"
    section = f"""{marker}
Applied by `{SCRIPT_MODULE}` at `{summary['generated_utc']}`.

This remains a staged candidate; canonical root products are unchanged. The source
corridor proposal came from `{summary['proposal_source_folder']}`.

- Proposal rows loaded: {summary['proposal_rows_loaded']}
- Rows applied: {summary['rows_applied']}
- Rows not applied: {summary['rows_not_applied']}
- Coverage before: {summary['coverage_before']}
- Coverage after: {summary['coverage_after']}
- Remaining unresolved bins: {summary['remaining_unresolved_after']}
- Additional distance-aware units: {summary['additional_distance_units']}

MVP regeneration remains deferred until staged QA passes.
"""
    base = existing.split(marker)[0].rstrip()
    path.write_text(base + "\n" + section + "\n", encoding="utf-8")


def main() -> None:
    bin_path = STAGING / "bin_context.parquet"
    approaches_path = STAGING / "signal_approaches.parquet"
    proposal_path = PROPOSAL_DIR / "global_assignment_proposal.csv"
    if not bin_path.exists() or not approaches_path.exists() or not proposal_path.exists():
        raise FileNotFoundError("Missing staged bin_context, signal_approaches, or global assignment proposal.")

    before = pd.read_parquet(bin_path)
    row_count_before = len(before)
    original_cols = list(before.columns)
    proposal = pd.read_csv(proposal_path, low_memory=False)
    approaches = pd.read_parquet(approaches_path)

    required_proposal_cols = {
        "stable_bin_id",
        "stable_signal_id",
        "proposal_status",
        "proposed_signal_approach_id_v2",
        "proposed_confidence",
        "conflict_with_existing_assignment",
        "crosses_stable_signal_id_boundary",
        "crosses_neighbor_signal_boundary",
    }
    missing = sorted(required_proposal_cols - set(proposal.columns))
    if missing:
        raise ValueError(f"Proposal missing required columns: {missing}")

    before_units = distance_units(before)
    before_units_by_band = before_units.groupby("distance_band_v2", dropna=False).size().rename("observed_units_before").reset_index()
    coverage_before = int(nonmissing(before["signal_approach_id_v2"]).sum())
    unresolved_before = int(ambiguous_mask(before).sum())
    legacy_coverage = int(nonmissing(before["legacy_signal_approach_id"]).sum()) if "legacy_signal_approach_id" in before.columns else 0

    proposal["proposal_status"] = proposal["proposal_status"].astype(str)
    proposal["proposed_confidence"] = proposal["proposed_confidence"].astype(str).str.lower()
    allowed = proposal["proposal_status"].isin(ALLOWED_STATUSES)
    allowed &= proposal["proposed_confidence"].notna() & (~proposal["proposed_confidence"].isin(LOW_CONFIDENCE))
    allowed &= nonmissing(proposal["proposed_signal_approach_id_v2"])
    for flag in [
        "conflict_with_existing_assignment",
        "crosses_stable_signal_id_boundary",
        "crosses_neighbor_signal_boundary",
        "turn_continuation_exclusion_violation",
    ]:
        if flag in proposal.columns:
            allowed &= ~proposal[flag].fillna(False).astype(bool)

    duplicate_conflicts = (
        proposal.groupby("stable_bin_id", dropna=False)["proposed_signal_approach_id_v2"]
        .nunique(dropna=True)
        .reset_index(name="proposal_id_count")
    )
    duplicate_conflicts = duplicate_conflicts[duplicate_conflicts["proposal_id_count"] > 1]
    if not duplicate_conflicts.empty:
        write_csv("source_corridor_proposal_apply_conflicts.csv", duplicate_conflicts)
        raise RuntimeError("Conflicting duplicate proposal rows found; refusing to write staged bin_context.")

    candidate_by_signal = approaches.groupby("stable_signal_id")["signal_approach_id"].apply(lambda s: set(s.dropna().astype(str))).to_dict()
    bin_index_counts = before["stable_bin_id"].value_counts(dropna=False)
    duplicate_bins = bin_index_counts[bin_index_counts > 1]
    if not duplicate_bins.empty:
        write_csv("source_corridor_proposal_apply_conflicts.csv", duplicate_bins.reset_index(name="count"))
        raise RuntimeError("Staged stable_bin_id duplicates found; refusing to write staged bin_context.")

    before_key = before[["stable_bin_id", "stable_signal_id", "signal_approach_id_v2", "signal_approach_id_status"]].copy()
    check = proposal.merge(before_key, on="stable_bin_id", how="left", suffixes=("_proposal", "_staged"), indicator=True)
    check["bin_exists_once"] = check["_merge"].eq("both")
    check["same_stable_signal_id"] = check["stable_signal_id_proposal"].astype(str).eq(check["stable_signal_id_staged"].astype(str))
    check["staged_currently_ambiguous_or_missing"] = check["signal_approach_id_v2"].isna() | check["signal_approach_id_status"].astype(str).str.contains(
        UNRESOLVED_PATTERN, case=False, na=False
    )
    check["proposed_id_valid_for_signal"] = check.apply(
        lambda r: str(r["proposed_signal_approach_id_v2"]) in candidate_by_signal.get(str(r["stable_signal_id_staged"]), set()),
        axis=1,
    )
    check["would_overwrite_existing_valid"] = nonmissing(check["signal_approach_id_v2"]) & ~check["signal_approach_id_status"].astype(str).str.contains(
        UNRESOLVED_PATTERN, case=False, na=False
    )
    check["allowed_initial"] = allowed.values
    check["allowed_after_validation"] = (
        check["allowed_initial"]
        & check["bin_exists_once"]
        & check["same_stable_signal_id"]
        & check["staged_currently_ambiguous_or_missing"]
        & check["proposed_id_valid_for_signal"]
        & (~check["would_overwrite_existing_valid"])
    )

    blocking = check[
        check["allowed_initial"]
        & (
            (~check["bin_exists_once"])
            | (~check["same_stable_signal_id"])
            | (~check["staged_currently_ambiguous_or_missing"])
            | (~check["proposed_id_valid_for_signal"])
            | check["would_overwrite_existing_valid"]
        )
    ].copy()
    if not blocking.empty:
        write_csv("source_corridor_proposal_apply_conflicts.csv", blocking)
        raise RuntimeError("Proposal failed hard QA gates; refusing to write staged bin_context.")

    apply_rows = check[check["allowed_after_validation"]].copy()
    not_apply_rows = check[~check["allowed_after_validation"]].copy()

    after = before.copy()
    apply_map = apply_rows.set_index("stable_bin_id")
    target_idx = after["stable_bin_id"].map(lambda x: x in apply_map.index)
    apply_ids = after.loc[target_idx, "stable_bin_id"].map(apply_map["proposed_signal_approach_id_v2"])
    apply_status = after.loc[target_idx, "stable_bin_id"].map(apply_map["proposal_status"])
    apply_method = after.loc[target_idx, "stable_bin_id"].map(apply_map["proposed_method"]) if "proposed_method" in apply_map.columns else apply_status
    apply_evidence = after.loc[target_idx, "stable_bin_id"].map(apply_map["evidence_fields"]) if "evidence_fields" in apply_map.columns else ""
    apply_candidate_count = after.loc[target_idx, "stable_bin_id"].map(lambda x: 1)

    after.loc[target_idx, "signal_approach_id_v2"] = apply_ids.values
    after.loc[target_idx, "signal_approach_id_status"] = "reconstructed_source_corridor_proposal"
    after.loc[target_idx, "signal_approach_id_method"] = apply_method.fillna(apply_status).values
    after.loc[target_idx, "signal_approach_id_evidence_fields"] = apply_evidence.fillna("").values
    after.loc[target_idx, "signal_approach_id_conflict_flag"] = False
    after.loc[target_idx, "signal_approach_id_ambiguous_candidate_count"] = apply_candidate_count.values
    after.loc[target_idx, "signal_approach_id_refinement_pass"] = "source_corridor_global_proposal_applied"

    row_count_after = len(after)
    row_loss = row_count_before - row_count_after
    if row_loss != 0 or list(after.columns) != original_cols:
        raise RuntimeError("Row loss or column change detected; refusing to write staged bin_context.")

    existing_valid_changed = int(
        (
            nonmissing(before["signal_approach_id_v2"])
            & ~before["signal_approach_id_status"].astype(str).str.contains(UNRESOLVED_PATTERN, case=False, na=False)
            & before["signal_approach_id_v2"].astype(str).ne(after["signal_approach_id_v2"].astype(str))
        ).sum()
    )
    if existing_valid_changed:
        raise RuntimeError("Existing valid assignments would change; refusing to write staged bin_context.")

    after_units = distance_units(after)
    after_units_by_band = after_units.groupby("distance_band_v2", dropna=False).size().rename("observed_units_after").reset_index()
    units_by_band = before_units_by_band.merge(after_units_by_band, on="distance_band_v2", how="outer").fillna(0)
    units_by_band["additional_units"] = units_by_band["observed_units_after"] - units_by_band["observed_units_before"]
    observed_before = int(len(before_units))
    observed_after = int(len(after_units))
    additional_units = observed_after - observed_before

    coverage_after = int(nonmissing(after["signal_approach_id_v2"]).sum())
    unresolved_after_mask = ambiguous_mask(after)
    unresolved_after = int(unresolved_after_mask.sum())
    directionality_preserved = all(c in after.columns for c in ["upstream_downstream_values", "directionality_coverage_status_values", "distance_band_v2"])
    distance_band_complete = int(nonmissing(after["distance_band_v2"]).sum()) if "distance_band_v2" in after else 0

    # All hard gates passed; write staged mutation and exports.
    after.to_parquet(bin_path, index=False)

    applied_export_cols = [c for c in apply_rows.columns if c in apply_rows.columns]
    write_csv("source_corridor_proposal_applied_rows.csv", apply_rows[applied_export_cols])
    write_csv("source_corridor_proposal_not_applied_rows.csv", not_apply_rows)
    write_csv("source_corridor_proposal_apply_conflicts.csv", blocking)
    status_counts = after["signal_approach_id_status"].value_counts(dropna=False).rename_axis("signal_approach_id_status").reset_index(name="bin_count")
    write_csv("bin_signal_approach_id_status_counts_after_source_corridor_apply.csv", status_counts)
    coverage_df = pd.DataFrame(
        [
            {"metric": "total_bin_rows", "value": row_count_after},
            {"metric": "legacy_signal_approach_id_coverage", "value": legacy_coverage},
            {"metric": "signal_approach_id_v2_coverage_before", "value": coverage_before},
            {"metric": "signal_approach_id_v2_coverage_after", "value": coverage_after},
            {"metric": "newly_assigned_rows", "value": len(apply_rows)},
            {"metric": "unresolved_rows_remaining", "value": unresolved_after},
            {"metric": "distance_band_nonmissing_rows", "value": distance_band_complete},
        ]
    )
    write_csv("bin_signal_approach_id_coverage_after_source_corridor_apply.csv", coverage_df)
    impact_df = pd.DataFrame(
        [
            {"metric": "observed_distance_aware_units_before_apply", "value": observed_before},
            {"metric": "observed_distance_aware_units_after_apply", "value": observed_after},
            {"metric": "additional_units_recovered", "value": additional_units},
            {"metric": "remaining_units_blocked_by_ambiguous_approach_id", "value": max(0, 52)},  # From review proposal estimate after applying full subset.
            {"metric": "directionality_is_dominant_next_blocker", "value": True},
        ]
    )
    write_csv("distance_aware_unit_impact_after_source_corridor_apply.csv", impact_df)
    write_csv("distance_aware_unit_counts_by_band_after_source_corridor_apply.csv", units_by_band)
    unresolved_rows = after[unresolved_after_mask].copy()
    write_csv("remaining_unresolved_bin_approach_id_rows_after_source_corridor_apply.csv", unresolved_rows)
    unresolved_summary = (
        unresolved_rows.groupby(["stable_signal_id", "source_route_name", "distance_band_v2", "signal_approach_id_status"], dropna=False)
        .size()
        .rename("unresolved_bin_count")
        .reset_index()
        .sort_values("unresolved_bin_count", ascending=False)
    )
    write_csv("remaining_unresolved_bin_approach_id_summary_after_source_corridor_apply.csv", unresolved_summary)
    summary = {
        "generated_utc": now(),
        "proposal_source_folder": rel(PROPOSAL_DIR),
        "proposal_rows_loaded": int(len(proposal)),
        "rows_applied": int(len(apply_rows)),
        "rows_not_applied": int(len(not_apply_rows)),
        "row_count_before": row_count_before,
        "row_count_after": row_count_after,
        "row_loss": row_loss,
        "coverage_before": coverage_before,
        "coverage_after": coverage_after,
        "unresolved_before": unresolved_before,
        "remaining_unresolved_after": unresolved_after,
        "existing_valid_changed": existing_valid_changed,
        "conflict_or_unsafe_rows": int(len(blocking)),
        "observed_distance_units_before": observed_before,
        "observed_distance_units_after": observed_after,
        "additional_distance_units": additional_units,
        "directionality_preserved": directionality_preserved,
        "recommendation": "source_corridor_proposal_applied_ready_for_review",
    }
    write_csv("source_corridor_proposal_apply_summary.csv", pd.DataFrame([summary]))

    def manifest_updater(data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("staging_updates", [])
        data["staging_updates"].append(
            {
                "update": "source_corridor_global_proposal_applied",
                "timestamp_utc": summary["generated_utc"],
                "script": SCRIPT_MODULE,
                "proposal_source_folder": rel(PROPOSAL_DIR),
                "rows_applied": summary["rows_applied"],
                "remaining_unresolved_after": summary["remaining_unresolved_after"],
                "canonical_roots_unchanged": True,
                "still_staged_candidate_not_promoted": True,
            }
        )
        data["latest_source_corridor_apply_summary"] = summary
        return data

    def schema_updater(data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("status_field_updates", [])
        data["status_field_updates"].append(
            {
                "timestamp_utc": summary["generated_utc"],
                "table": "bin_context.parquet",
                "updated_fields": [
                    "signal_approach_id_v2",
                    "signal_approach_id_status",
                    "signal_approach_id_method",
                    "signal_approach_id_evidence_fields",
                    "signal_approach_id_conflict_flag",
                    "signal_approach_id_ambiguous_candidate_count",
                    "signal_approach_id_refinement_pass",
                ],
                "new_status_value": "reconstructed_source_corridor_proposal",
                "new_refinement_pass": "source_corridor_global_proposal_applied",
            }
        )
        return data

    update_json_metadata(STAGING / "manifest.json", manifest_updater)
    update_json_metadata(STAGING / "schema.json", schema_updater)
    update_readme(STAGING / "README.md", summary)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
