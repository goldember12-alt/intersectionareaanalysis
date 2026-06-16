"""Second-pass staged bin approach-ID refinement.

This updates only the staged final-leg candidate folder. It preserves pass-1
status/method fields and assigns additional bin-level approach IDs only where a
candidate rule yields exactly one staged approach without crossing signals.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
FINAL_DIR = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP_DIR = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
STAGED_DIR = REPO / "work" / "roadway_graph" / "analysis" / "_staging" / "final_leg_corrected_analysis_dataset_refresh_candidate"
EXPORTS = STAGED_DIR / "exports"

PREVIOUS = {
    "theoretical_full_max": 155_064,
    "bin_supported_expected_units": 81_572,
    "previous_staged_observed_distance_units": 66_316,
    "previous_current_observed_distance_units": 62_334,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>", "unknown_missing"]))


def load_inputs():
    bin_context = pd.read_parquet(STAGED_DIR / "bin_context.parquet")
    approaches = pd.read_parquet(STAGED_DIR / "signal_approaches.parquet")
    approach_windows = pd.read_parquet(STAGED_DIR / "approach_windows.parquet")
    dir_bins = pd.read_csv(MVP_DIR / "mvp_directional_bin_context.csv", low_memory=False)
    return bin_context, approaches, approach_windows, dir_bins


def build_unique_mapping(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    assigned = df[nonmissing(df["signal_approach_id_v2"])]
    g = (
        assigned.groupby(keys, dropna=False)["signal_approach_id_v2"]
        .agg(["nunique", lambda s: "|".join(sorted(set(s.dropna().astype(str))))])
        .reset_index()
    )
    lambda_col = [c for c in g.columns if c not in keys + ["nunique"]][0]
    return g.rename(columns={"nunique": "candidate_count", lambda_col: "candidate_ids"})


def apply_unique_mapping(df: pd.DataFrame, keys: list[str], status: str, method: str) -> tuple[pd.DataFrame, int, int, int]:
    mapping = build_unique_mapping(df, keys)
    unresolved_mask = ~nonmissing(df["signal_approach_id_v2"])
    target = df.loc[unresolved_mask, ["pre_refresh_bin_row_id"] + keys].merge(mapping, on=keys, how="left")
    det = target[target["candidate_count"] == 1]
    amb = target[target["candidate_count"].fillna(0) > 1]
    unres = target["candidate_count"].isna().sum()
    if not det.empty:
        id_map = det.set_index("pre_refresh_bin_row_id")["candidate_ids"].to_dict()
        idx = df["pre_refresh_bin_row_id"].isin(id_map.keys())
        df.loc[idx, "signal_approach_id_v2"] = df.loc[idx, "pre_refresh_bin_row_id"].map(id_map)
        df.loc[idx, "signal_approach_id_status"] = status
        df.loc[idx, "signal_approach_id_method"] = method
        df.loc[idx, "signal_approach_id_evidence_fields"] = "|".join(keys) + "|assigned_bin_context_unique_mapping"
        df.loc[idx, "signal_approach_id_ambiguous_candidate_count"] = 1
        df.loc[idx, "signal_approach_id_refinement_pass"] = "pass2"
    # Only update ambiguous counts for rows still unassigned.
    if not amb.empty:
        amb_map = amb.set_index("pre_refresh_bin_row_id")["candidate_count"].to_dict()
        idx = df["pre_refresh_bin_row_id"].isin(amb_map.keys()) & (~nonmissing(df["signal_approach_id_v2"]))
        df.loc[idx, "signal_approach_id_ambiguous_candidate_count"] = df.loc[idx, "pre_refresh_bin_row_id"].map(amb_map).fillna(0).astype(int)
    return df, len(det), len(amb), int(unres)


def apply_neighbor_continuity(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    rows_to_assign: dict[int, str] = {}
    group_keys = ["stable_signal_id", "stable_travelway_id", "analysis_window"]
    sortable = df.sort_values(group_keys + ["distance_start_ft", "distance_end_ft", "pre_refresh_bin_row_id"])
    for _key, g in sortable.groupby(group_keys, dropna=False):
        ids = g["signal_approach_id_v2"].tolist()
        row_ids = g["pre_refresh_bin_row_id"].tolist()
        for pos, sid in enumerate(ids):
            if pd.notna(sid):
                continue
            prev_id = next((ids[j] for j in range(pos - 1, -1, -1) if pd.notna(ids[j])), None)
            next_id = next((ids[j] for j in range(pos + 1, len(ids)) if pd.notna(ids[j])), None)
            if prev_id is not None and next_id is not None and prev_id == next_id:
                rows_to_assign[row_ids[pos]] = prev_id
    if rows_to_assign:
        idx = df["pre_refresh_bin_row_id"].isin(rows_to_assign.keys())
        df.loc[idx, "signal_approach_id_v2"] = df.loc[idx, "pre_refresh_bin_row_id"].map(rows_to_assign)
        df.loc[idx, "signal_approach_id_status"] = "reconstructed_refined_by_neighbor_continuity"
        df.loc[idx, "signal_approach_id_method"] = "same_signal_travelway_window_neighboring_assigned_bins_agree"
        df.loc[idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|stable_travelway_id|analysis_window|distance_start_ft|neighboring_signal_approach_id_v2"
        df.loc[idx, "signal_approach_id_ambiguous_candidate_count"] = 1
        df.loc[idx, "signal_approach_id_refinement_pass"] = "pass2"
    return df, len(rows_to_assign)


def refresh_remaining_status(df: pd.DataFrame, approaches: pd.DataFrame) -> pd.DataFrame:
    unresolved = ~nonmissing(df["signal_approach_id_v2"])
    counts = approaches.groupby("stable_signal_id")["signal_approach_id"].nunique().rename("staged_candidate_count").reset_index()
    m = df.loc[unresolved, ["pre_refresh_bin_row_id", "stable_signal_id"]].merge(counts, on="stable_signal_id", how="left")
    multi = m[m["staged_candidate_count"].fillna(0) > 1].set_index("pre_refresh_bin_row_id")["staged_candidate_count"].to_dict()
    none = m[m["staged_candidate_count"].fillna(0) <= 1].set_index("pre_refresh_bin_row_id")["staged_candidate_count"].to_dict()
    if multi:
        idx = df["pre_refresh_bin_row_id"].isin(multi.keys())
        df.loc[idx, "signal_approach_id_status"] = "ambiguous_not_assigned_after_refinement"
        df.loc[idx, "signal_approach_id_method"] = "multiple_staged_approaches_remain_plausible_after_refinement"
        df.loc[idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|travelway_route_distance_fields"
        df.loc[idx, "signal_approach_id_ambiguous_candidate_count"] = df.loc[idx, "pre_refresh_bin_row_id"].map(multi).fillna(0).astype(int)
        df.loc[idx, "signal_approach_id_refinement_pass"] = "pass2_unresolved"
    if none:
        idx = df["pre_refresh_bin_row_id"].isin(none.keys())
        df.loc[idx, "signal_approach_id_status"] = "insufficient_evidence_not_assigned_after_refinement"
        df.loc[idx, "signal_approach_id_method"] = "no_unique_staged_approach_candidate_after_refinement"
        df.loc[idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|staged_signal_approaches"
        df.loc[idx, "signal_approach_id_refinement_pass"] = "pass2_unresolved"
    return df


def profile_unresolved(df: pd.DataFrame, approaches: pd.DataFrame) -> pd.DataFrame:
    unresolved = df[(~nonmissing(df["signal_approach_id_v2"])) | df["signal_approach_id_status"].astype(str).str.contains("ambiguous|insufficient|source_limited", case=False, na=False)].copy()
    cand_signal = approaches.groupby("stable_signal_id")["signal_approach_id"].nunique().rename("candidate_approaches_for_signal").reset_index()
    unresolved = unresolved.merge(cand_signal, on="stable_signal_id", how="left")
    rows = []
    group_fields = [
        "stable_signal_id",
        "analysis_window",
        "distance_band_v2",
        "upstream_downstream_values",
        "directionality_coverage_status_values",
        "mvp_directionality_method_values",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
    ]
    for field in [f for f in group_fields if f in unresolved.columns]:
        g = unresolved.groupby(field, dropna=False).agg(
            unresolved_bin_count=("stable_bin_id", "count"),
            candidate_approaches_min=("candidate_approaches_for_signal", "min"),
            candidate_approaches_max=("candidate_approaches_for_signal", "max"),
        ).reset_index().sort_values("unresolved_bin_count", ascending=False).head(200)
        for _, row in g.iterrows():
            rows.append({
                "profile_field": field,
                "profile_value": row[field],
                "unresolved_bin_count": int(row["unresolved_bin_count"]),
                "candidate_approaches_min": row["candidate_approaches_min"],
                "candidate_approaches_max": row["candidate_approaches_max"],
            })
    return pd.DataFrame(rows)


def distance_unit_impact(before: pd.DataFrame, after: pd.DataFrame, dir_bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = dir_bins[["stable_bin_id", "stable_signal_id", "upstream_downstream", "distance_start_ft", "distance_end_ft"]].copy()
    if "distance_band_v2" not in d.columns:
        mid = (pd.to_numeric(d["distance_start_ft"], errors="coerce") + pd.to_numeric(d["distance_end_ft"], errors="coerce")) / 2
        # Same labels already in bin_context; merge is simpler for exact band.
        pass
    before_d = d.merge(before[["stable_bin_id", "signal_approach_id_v2", "distance_band_v2", "signal_approach_id_status"]], on="stable_bin_id", how="left")
    after_d = d.merge(after[["stable_bin_id", "signal_approach_id_v2", "distance_band_v2", "signal_approach_id_status"]], on="stable_bin_id", how="left")
    def units(df):
        return df[nonmissing(df["signal_approach_id_v2"]) & nonmissing(df["upstream_downstream"]) & nonmissing(df["distance_band_v2"])][["stable_signal_id", "signal_approach_id_v2", "upstream_downstream", "distance_band_v2"]].drop_duplicates()
    before_units = units(before_d)
    after_units = units(after_d)
    before_set = set(map(tuple, before_units.itertuples(index=False, name=None)))
    after_set = set(map(tuple, after_units.itertuples(index=False, name=None)))
    ambiguous_units = after_d[after_d["signal_approach_id_status"].astype(str).str.contains("ambiguous", case=False, na=False)][["stable_signal_id", "upstream_downstream", "distance_band_v2"]].drop_duplicates().shape[0]
    missing_dir_bins = after[(after["directionality_coverage_preserved_flag"] == False) & nonmissing(after["signal_approach_id_v2"]) & nonmissing(after["distance_band_v2"])]
    missing_dir_units = missing_dir_bins[["stable_signal_id", "signal_approach_id_v2", "distance_band_v2"]].drop_duplicates().shape[0] * 2
    summary = pd.DataFrame([
        {"metric": "theoretical_full_max", "unit_count": PREVIOUS["theoretical_full_max"]},
        {"metric": "bin_supported_expected_units", "unit_count": PREVIOUS["bin_supported_expected_units"]},
        {"metric": "previous_current_observed_distance_units", "unit_count": PREVIOUS["previous_current_observed_distance_units"]},
        {"metric": "previous_staged_observed_distance_units", "unit_count": PREVIOUS["previous_staged_observed_distance_units"]},
        {"metric": "staged_observed_distance_units_before_refinement", "unit_count": len(before_units)},
        {"metric": "staged_observed_distance_units_after_refinement", "unit_count": len(after_units)},
        {"metric": "additional_units_recovered_by_refinement", "unit_count": len(after_set - before_set)},
        {"metric": "units_still_missing_due_to_ambiguous_approach_id", "unit_count": ambiguous_units},
        {"metric": "units_still_missing_due_to_missing_directionality", "unit_count": missing_dir_units},
        {"metric": "units_still_missing_due_to_no_bin_support", "unit_count": max(PREVIOUS["theoretical_full_max"] - PREVIOUS["bin_supported_expected_units"], 0)},
        {"metric": "units_still_missing_or_source_limited", "unit_count": max(PREVIOUS["theoretical_full_max"] - len(after_units) - missing_dir_units, 0)},
    ])
    by_band = after_units.groupby("distance_band_v2").size().rename("observed_units_after_refinement").reset_index()
    before_band = before_units.groupby("distance_band_v2").size().rename("observed_units_before_refinement").reset_index()
    by_band = by_band.merge(before_band, on="distance_band_v2", how="outer").fillna(0)
    by_band["additional_units_recovered"] = by_band["observed_units_after_refinement"] - by_band["observed_units_before_refinement"]
    return summary, by_band


def far_distance(after: pd.DataFrame, unit_by_band: pd.DataFrame) -> pd.DataFrame:
    g = after.groupby("distance_band_v2", dropna=False).agg(
        bin_count=("stable_bin_id", "count"),
        assigned_approach_id_count=("signal_approach_id_v2", lambda s: int(nonmissing(s).sum())),
        unresolved_approach_id_count=("signal_approach_id_v2", lambda s: int((~nonmissing(s)).sum())),
        directionality_covered_bins=("directionality_coverage_preserved_flag", "sum"),
    ).reset_index()
    return g.merge(unit_by_band, on="distance_band_v2", how="left")


def map_review(after: pd.DataFrame, approaches: pd.DataFrame) -> pd.DataFrame:
    unresolved = after[~nonmissing(after["signal_approach_id_v2"])].copy()
    candidates = approaches.groupby("stable_signal_id")["signal_approach_id"].agg(lambda s: "|".join(sorted(set(s.astype(str))))).rename("candidate_signal_approach_id_values").reset_index()
    unresolved = unresolved.merge(candidates, on="stable_signal_id", how="left")
    group_cols = ["stable_signal_id", "distance_band_v2", "analysis_window", "stable_travelway_id", "source_route_id", "source_route_name", "signal_approach_id_status"]
    g = unresolved.groupby(group_cols, dropna=False).agg(
        unresolved_bin_count=("stable_bin_id", "count"),
        candidate_signal_approach_id_values=("candidate_signal_approach_id_values", "first"),
        upstream_downstream=("upstream_downstream_values", "first"),
    ).reset_index()
    g["missing_unit_contribution"] = g["unresolved_bin_count"].clip(upper=1) * 2
    far_weight = g["distance_band_v2"].map({"1000-1500": 2, "1500-2000": 3, "2000-2500": 4}).fillna(1)
    band_count = g.groupby("stable_signal_id")["distance_band_v2"].transform("nunique")
    g["priority_score"] = g["unresolved_bin_count"] + g["missing_unit_contribution"] * 10 + far_weight * 5 + band_count
    g["ambiguity_reason"] = g["signal_approach_id_status"]
    g["recommended_review_action"] = "map-review unresolved approach linkage; directionality already present where upstream_downstream is populated"
    return g.sort_values("priority_score", ascending=False).head(1000)


def write_outputs(before: pd.DataFrame, after: pd.DataFrame, approaches: pd.DataFrame, dir_bins: pd.DataFrame, metrics: dict):
    write = lambda name, df: df.to_csv(EXPORTS / name, index=False)
    write("bin_approach_id_refinement_profile.csv", profile_unresolved(after, approaches))
    write("bin_approach_id_refinement_status_counts.csv", after["signal_approach_id_status"].value_counts(dropna=False).rename_axis("signal_approach_id_status").reset_index(name="row_count"))
    write("bin_approach_id_refinement_method_counts.csv", after.groupby(["signal_approach_id_status", "signal_approach_id_method"], dropna=False).size().rename("row_count").reset_index().sort_values("row_count", ascending=False))
    refined = after[after["signal_approach_id_refinement_pass"].eq("pass2")]
    write("bin_approach_id_refined_rows.csv", refined)
    write("bin_approach_id_remaining_ambiguous_rows.csv", after[after["signal_approach_id_status"].astype(str).str.contains("ambiguous", case=False, na=False)])
    write("bin_approach_id_remaining_source_limited_rows.csv", after[after["signal_approach_id_status"].astype(str).str.contains("source_limited|insufficient", case=False, na=False)])
    write("bin_approach_id_conflicts_after_refinement.csv", after[after["signal_approach_id_conflict_flag"] == True])
    unit_summary, unit_by_band = distance_unit_impact(before, after, dir_bins)
    write("distance_aware_unit_impact_after_refinement.csv", unit_summary)
    write("distance_aware_unit_counts_by_band_after_refinement.csv", unit_by_band)
    write("far_distance_coverage_after_refinement.csv", far_distance(after, unit_by_band))
    write("map_review_candidate_bin_approach_linkage_after_refinement.csv", map_review(after, approaches))
    prepost = pd.DataFrame([
        {"metric": "row_count_before", "value": len(before)},
        {"metric": "row_count_after", "value": len(after)},
        {"metric": "row_loss", "value": len(before) - len(after)},
        {"metric": "coverage_before_refinement", "value": int(nonmissing(before["signal_approach_id_v2"]).sum())},
        {"metric": "coverage_after_refinement", "value": int(nonmissing(after["signal_approach_id_v2"]).sum())},
        {"metric": "newly_assigned_bins", "value": metrics["newly_assigned_bins"]},
        {"metric": "remaining_unresolved_bins", "value": int((~nonmissing(after["signal_approach_id_v2"])).sum())},
        {"metric": "conflict_rows", "value": int(after["signal_approach_id_conflict_flag"].sum())},
        {"metric": "additional_distance_units_recovered", "value": int(unit_summary.loc[unit_summary.metric.eq("additional_units_recovered_by_refinement"), "unit_count"].iloc[0])},
    ])
    write("pre_vs_post_bin_approach_id_refinement_summary.csv", prepost)
    return unit_summary


def update_staging_metadata(after: pd.DataFrame, metrics: dict, recommendation: str, next_step: str) -> None:
    manifest_path = STAGED_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest["bin_approach_id_refinement"] = {
        "generated_utc": now(),
        "producing_script": "src.roadway_graph.staged_bin_approach_id_refinement",
        "input_tables_read": [
            rel(STAGED_DIR / "bin_context.parquet"),
            rel(STAGED_DIR / "signal_approaches.parquet"),
            rel(STAGED_DIR / "approach_windows.parquet"),
            rel(MVP_DIR / "mvp_directional_bin_context.csv"),
        ],
        "qa_metrics": metrics,
        "recommendation": recommendation,
        "recommended_next_step": next_step,
        "staging_candidate_not_promoted": True,
    }
    manifest.setdefault("row_counts", {})["bin_context"] = len(after)
    (STAGED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    schema_path = STAGED_DIR / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else {"tables": {}}
    schema.setdefault("tables", {})["bin_context.parquet"] = {
        "expected_grain": "stable_bin_id, one row per final leg-corrected bin",
        "primary_key_candidates": ["stable_bin_id"],
        "columns": {c: str(t) for c, t in after.dtypes.items()},
        "required_fields": ["stable_bin_id", "stable_signal_id", "distance_band_v2"],
        "nullable_fields": [c for c in after.columns if after[c].isna().any()],
        "status_provenance_fields": [
            "legacy_signal_approach_id",
            "signal_approach_id_v2",
            "signal_approach_id_status_pass1",
            "signal_approach_id_method_pass1",
            "signal_approach_id_status",
            "signal_approach_id_method",
            "signal_approach_id_refinement_pass",
        ],
    }
    (STAGED_DIR / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")

    readme_path = STAGED_DIR / "README.md"
    text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else "# Final-Leg Corrected Analysis Dataset Refresh Candidate\n"
    text += (
        "\n## Bin Approach-ID Refinement\n\n"
        f"Second-pass refinement assigned {metrics['newly_assigned_bins']} additional bins and leaves "
        f"{metrics['remaining_unresolved_bins']} unresolved/ambiguous bins. This remains a staging candidate; MVP regeneration is still deferred.\n"
    )
    readme_path.write_text(text, encoding="utf-8")


def main():
    EXPORTS.mkdir(parents=True, exist_ok=True)
    before, approaches, _approach_windows, dir_bins = load_inputs()
    before = before.copy()
    after = before.copy()
    if "signal_approach_id_status_pass1" not in after.columns:
        after["signal_approach_id_status_pass1"] = after["signal_approach_id_status"]
    if "signal_approach_id_method_pass1" not in after.columns:
        after["signal_approach_id_method_pass1"] = after["signal_approach_id_method"]
    after["signal_approach_id_refinement_pass"] = after.get("signal_approach_id_refinement_pass", "pass1")
    after.loc[after["signal_approach_id_refinement_pass"].isna(), "signal_approach_id_refinement_pass"] = "pass1"

    before_coverage = int(nonmissing(before["signal_approach_id_v2"]).sum())

    # A. signal + travelway unique across all assigned bins.
    after, det_tw, amb_tw, unres_tw = apply_unique_mapping(
        after,
        ["stable_signal_id", "stable_travelway_id"],
        "reconstructed_refined_by_signal_travelway_unique",
        "stable_signal_id + stable_travelway_id unique assigned approach",
    )
    # B. route/side unique. Side/direction fields are limited, so use available route-common/detail keys conservatively.
    for keys, status in [
        (["stable_signal_id", "source_route_id", "existing_roadway_division_context"], "reconstructed_refined_by_route_side_unique"),
        (["stable_signal_id", "source_route_common", "existing_roadway_division_context"], "reconstructed_refined_by_route_side_unique"),
        (["stable_signal_id", "route_key_common", "existing_roadway_division_context"], "reconstructed_refined_by_route_side_unique"),
    ]:
        if all(k in after.columns for k in keys):
            after, _det, _amb, _unres = apply_unique_mapping(after, keys, status, " + ".join(keys) + " unique assigned approach")
    # C. neighbor continuity.
    after, det_neighbor = apply_neighbor_continuity(after)
    after = refresh_remaining_status(after, approaches)

    # QA: no crossing stable_signal_id possible because every mapping includes stable_signal_id.
    after_coverage = int(nonmissing(after["signal_approach_id_v2"]).sum())
    metrics = {
        "row_count_before": len(before),
        "row_count_after": len(after),
        "row_loss": len(before) - len(after),
        "stable_bin_id_duplicate_count": int(after.duplicated(["stable_bin_id"], keep=False).sum()),
        "coverage_before_refinement": before_coverage,
        "coverage_after_refinement": after_coverage,
        "newly_assigned_bins": after_coverage - before_coverage,
        "remaining_unresolved_bins": int((~nonmissing(after["signal_approach_id_v2"])).sum()),
        "conflict_rows": int(after["signal_approach_id_conflict_flag"].sum()),
        "distance_band_missing_rows": int((~nonmissing(after["distance_band_v2"])).sum()),
        "directionality_covered_rows": int(after["directionality_coverage_preserved_flag"].sum()),
        "existing_valid_changed_rows": int(((before["signal_approach_id_status"] == "existing_valid") & (before["signal_approach_id_v2"] != after["signal_approach_id_v2"])).sum()),
        "assignment_crosses_stable_signal_id_boundaries": 0,
        "signal_travelway_unique_assignments_first_rule": det_tw,
        "neighbor_continuity_assignments": det_neighbor,
    }

    failed = any([
        metrics["row_loss"] != 0,
        metrics["stable_bin_id_duplicate_count"] != 0,
        metrics["conflict_rows"] != 0,
        metrics["distance_band_missing_rows"] != 0,
        metrics["existing_valid_changed_rows"] != 0,
        metrics["assignment_crosses_stable_signal_id_boundaries"] != 0,
    ])
    if failed:
        recommendation = "bin_approach_id_refinement_failed_due_to_row_loss_or_conflicts"
        next_step = "audit staged bin_context candidate"
    elif metrics["remaining_unresolved_bins"] > 0:
        recommendation = "bin_approach_id_refinement_blocked_by_true_ambiguity"
        next_step = "investigate far-distance approach-leg endpoint/bin-generation logic"
    else:
        recommendation = "bin_approach_id_refinement_ready_for_review"
        next_step = "audit staged bin_context candidate"

    # Write parquet after QA metrics are computed but before metadata update.
    after.to_parquet(STAGED_DIR / "bin_context.parquet", index=False)
    unit_summary = write_outputs(before, after, approaches, dir_bins, metrics)
    metrics["additional_distance_units_recovered"] = int(unit_summary.loc[unit_summary.metric.eq("additional_units_recovered_by_refinement"), "unit_count"].iloc[0])
    metrics["staged_observed_distance_units_before_refinement"] = int(unit_summary.loc[unit_summary.metric.eq("staged_observed_distance_units_before_refinement"), "unit_count"].iloc[0])
    metrics["staged_observed_distance_units_after_refinement"] = int(unit_summary.loc[unit_summary.metric.eq("staged_observed_distance_units_after_refinement"), "unit_count"].iloc[0])
    update_staging_metadata(after, metrics, recommendation, next_step)

    print(json.dumps({"recommendation": recommendation, "recommended_next_step": next_step, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
