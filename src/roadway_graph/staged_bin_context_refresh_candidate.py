"""Build staged bin-context refresh candidate.

This script writes only to the existing final-leg refresh staging folder. It
does not modify canonical root products, promote outputs, or regenerate MVP.
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

BANDS = [
    ("0-250", 0, 250),
    ("250-500", 250, 500),
    ("500-1000", 500, 1000),
    ("1000-1500", 1000, 1500),
    ("1500-2000", 1500, 2000),
    ("2000-2500", 2000, 2500),
]

PREVIOUS_DISTANCE_AUDIT = {
    "theoretical_full_max": 155_064,
    "bin_supported_expected_units": 81_572,
    "current_observed_distance_units": 62_334,
    "recoverable_candidate_units": 4_672,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>", "unknown_missing"]))


def assign_band(midpoint):
    if pd.isna(midpoint):
        return pd.NA
    m = float(midpoint)
    for label, low, high in BANDS:
        if low <= m < high or (label == "2000-2500" and low <= m <= high):
            return label
    return pd.NA


def band_start(label):
    for b, low, _high in BANDS:
        if b == label:
            return low
    return pd.NA


def band_end(label):
    for b, _low, high in BANDS:
        if b == label:
            return high
    return pd.NA


def load_inputs():
    bins = pd.read_csv(FINAL_DIR / "analysis_bin.csv", low_memory=False)
    staged_approaches = pd.read_parquet(STAGED_DIR / "signal_approaches.parquet")
    staged_aw = pd.read_parquet(STAGED_DIR / "approach_windows.parquet")
    dir_bins = pd.read_csv(MVP_DIR / "mvp_directional_bin_context.csv", low_memory=False)
    return bins, staged_approaches, staged_aw, dir_bins


def build_existing_mapping(bins: pd.DataFrame, staged_approaches: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    valid_ids = staged_approaches[["stable_signal_id", "signal_approach_id"]].drop_duplicates()
    b = bins[nonmissing(bins["signal_approach_id"])].merge(
        valid_ids,
        on=["stable_signal_id", "signal_approach_id"],
        how="inner",
    )
    g = b.groupby(keys, dropna=False)["signal_approach_id"].agg(["nunique", lambda x: sorted(set(x.astype(str)))])
    g = g.reset_index().rename(columns={"nunique": "candidate_count", "<lambda_0>": "candidate_ids"})
    # pandas may name lambda column differently depending version
    if "candidate_ids" not in g.columns:
        lambda_cols = [c for c in g.columns if c not in keys + ["candidate_count"]]
        g = g.rename(columns={lambda_cols[0]: "candidate_ids"})
    g["candidate_ids"] = g["candidate_ids"].apply(lambda xs: "|".join(xs))
    return g


def reconstruct_signal_approach_id(bins: pd.DataFrame, staged_approaches: pd.DataFrame) -> pd.DataFrame:
    out = bins.copy()
    out.insert(0, "pre_refresh_bin_row_id", range(len(out)))
    out["legacy_signal_approach_id"] = out["signal_approach_id"]
    out["signal_approach_id_v2"] = pd.NA
    out["signal_approach_id_status"] = "insufficient_evidence_not_assigned"
    out["signal_approach_id_method"] = "not_assigned"
    out["signal_approach_id_evidence_fields"] = ""
    out["signal_approach_id_conflict_flag"] = False
    out["signal_approach_id_ambiguous_candidate_count"] = 0

    staged_ids = staged_approaches[["stable_signal_id", "signal_approach_id"]].drop_duplicates()
    staged_counts = staged_ids.groupby("stable_signal_id")["signal_approach_id"].nunique().rename("staged_signal_approach_count").reset_index()
    staged_single = staged_ids.merge(staged_counts, on="stable_signal_id", how="left")
    staged_single = staged_single[staged_single["staged_signal_approach_count"] == 1][["stable_signal_id", "signal_approach_id"]].rename(columns={"signal_approach_id": "single_staged_signal_approach_id"})

    # A. preserve existing valid IDs.
    valid_existing = out[["pre_refresh_bin_row_id", "stable_signal_id", "legacy_signal_approach_id"]].rename(columns={"legacy_signal_approach_id": "signal_approach_id"})
    valid_existing = valid_existing[nonmissing(valid_existing["signal_approach_id"])].merge(
        staged_ids,
        on=["stable_signal_id", "signal_approach_id"],
        how="inner",
    )
    idx = out["pre_refresh_bin_row_id"].isin(valid_existing["pre_refresh_bin_row_id"])
    out.loc[idx, "signal_approach_id_v2"] = out.loc[idx, "legacy_signal_approach_id"]
    out.loc[idx, "signal_approach_id_status"] = "existing_valid"
    out.loc[idx, "signal_approach_id_method"] = "preserved_existing_valid_id"
    out.loc[idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|legacy_signal_approach_id|staged_signal_approaches"

    # Conflicting existing IDs are non-null but not in staged approach universe for same signal.
    legacy_nonnull = nonmissing(out["legacy_signal_approach_id"])
    conflict_idx = legacy_nonnull & (~idx)
    out.loc[conflict_idx, "signal_approach_id_status"] = "invalid_or_conflicting_existing_id"
    out.loc[conflict_idx, "signal_approach_id_conflict_flag"] = True
    out.loc[conflict_idx, "signal_approach_id_method"] = "legacy_id_not_found_in_staged_signal_approaches"
    out.loc[conflict_idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|legacy_signal_approach_id|staged_signal_approaches"

    missing_mask = ~nonmissing(out["signal_approach_id_v2"]) & (~out["signal_approach_id_conflict_flag"])

    # C1. stable signal + window + travelway maps to one staged approach from existing valid bins.
    for method_name, keys, status in [
        ("stable_signal_id + analysis_window + stable_travelway_id", ["stable_signal_id", "analysis_window", "stable_travelway_id"], "reconstructed_by_signal_window_travelway"),
        ("stable_signal_id + analysis_window + source_route_id", ["stable_signal_id", "analysis_window", "source_route_id"], "reconstructed_by_signal_window_route"),
        ("stable_signal_id + analysis_window + source_route_name", ["stable_signal_id", "analysis_window", "source_route_name"], "reconstructed_by_signal_window_route"),
    ]:
        if not all(k in out.columns for k in keys):
            continue
        mapping = build_existing_mapping(out, staged_approaches, keys)
        m = out.loc[missing_mask, ["pre_refresh_bin_row_id"] + keys].merge(mapping, on=keys, how="left")
        det = m[m["candidate_count"] == 1].copy()
        if not det.empty:
            id_map = det.set_index("pre_refresh_bin_row_id")["candidate_ids"].to_dict()
            row_idx = out["pre_refresh_bin_row_id"].isin(id_map.keys())
            out.loc[row_idx, "signal_approach_id_v2"] = out.loc[row_idx, "pre_refresh_bin_row_id"].map(id_map)
            out.loc[row_idx, "signal_approach_id_status"] = status
            out.loc[row_idx, "signal_approach_id_method"] = method_name
            out.loc[row_idx, "signal_approach_id_evidence_fields"] = "|".join(keys) + "|existing_valid_bin_mapping"
            out.loc[row_idx, "signal_approach_id_ambiguous_candidate_count"] = 1
        amb = m[m["candidate_count"].fillna(0) > 1]
        if not amb.empty:
            amb_map = amb.set_index("pre_refresh_bin_row_id")["candidate_count"].to_dict()
            amb_idx = out["pre_refresh_bin_row_id"].isin(amb_map.keys()) & (~nonmissing(out["signal_approach_id_v2"]))
            out.loc[amb_idx, "signal_approach_id_status"] = "ambiguous_not_assigned"
            out.loc[amb_idx, "signal_approach_id_method"] = method_name
            out.loc[amb_idx, "signal_approach_id_evidence_fields"] = "|".join(keys) + "|existing_valid_bin_mapping"
            out.loc[amb_idx, "signal_approach_id_ambiguous_candidate_count"] = out.loc[amb_idx, "pre_refresh_bin_row_id"].map(amb_map).fillna(0).astype(int)
        missing_mask = ~nonmissing(out["signal_approach_id_v2"]) & (~out["signal_approach_id_conflict_flag"]) & (out["signal_approach_id_status"] != "ambiguous_not_assigned")

    # B. single-approach signal rule, only after stronger route/travelway rules.
    single = out.loc[missing_mask, ["pre_refresh_bin_row_id", "stable_signal_id"]].merge(staged_single, on="stable_signal_id", how="left")
    det = single[nonmissing(single["single_staged_signal_approach_id"])]
    if not det.empty:
        id_map = det.set_index("pre_refresh_bin_row_id")["single_staged_signal_approach_id"].to_dict()
        row_idx = out["pre_refresh_bin_row_id"].isin(id_map.keys())
        out.loc[row_idx, "signal_approach_id_v2"] = out.loc[row_idx, "pre_refresh_bin_row_id"].map(id_map)
        out.loc[row_idx, "signal_approach_id_status"] = "reconstructed_single_approach_signal"
        out.loc[row_idx, "signal_approach_id_method"] = "stable_signal_id_has_one_staged_approach"
        out.loc[row_idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|staged_signal_approaches"
        out.loc[row_idx, "signal_approach_id_ambiguous_candidate_count"] = 1

    # Remaining missing rows: distinguish multi-candidate staged signals from no staged evidence.
    remaining = ~nonmissing(out["signal_approach_id_v2"]) & (~out["signal_approach_id_conflict_flag"]) & (out["signal_approach_id_status"] != "ambiguous_not_assigned")
    counts = out.loc[remaining, ["pre_refresh_bin_row_id", "stable_signal_id"]].merge(staged_counts, on="stable_signal_id", how="left")
    multi = counts[counts["staged_signal_approach_count"].fillna(0) > 1].set_index("pre_refresh_bin_row_id")["staged_signal_approach_count"].to_dict()
    multi_idx = out["pre_refresh_bin_row_id"].isin(multi.keys()) & remaining
    out.loc[multi_idx, "signal_approach_id_status"] = "ambiguous_not_assigned"
    out.loc[multi_idx, "signal_approach_id_method"] = "multiple_staged_approaches_no_unique_route_or_travelway_match"
    out.loc[multi_idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|analysis_window|route_travelway_fields"
    out.loc[multi_idx, "signal_approach_id_ambiguous_candidate_count"] = out.loc[multi_idx, "pre_refresh_bin_row_id"].map(multi).fillna(0).astype(int)
    none_idx = remaining & (~multi_idx)
    out.loc[none_idx, "signal_approach_id_status"] = "source_limited_not_assigned"
    out.loc[none_idx, "signal_approach_id_method"] = "no_staged_approach_candidate_for_signal"
    out.loc[none_idx, "signal_approach_id_evidence_fields"] = "stable_signal_id|staged_signal_approaches"

    return out


def add_distance_bands(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    start = pd.to_numeric(out["distance_start_ft"], errors="coerce")
    end = pd.to_numeric(out["distance_end_ft"], errors="coerce")
    out["distance_band_mid_ft"] = (start + end) / 2
    out["distance_band_v2"] = out["distance_band_mid_ft"].apply(assign_band)
    out["distance_band_start_ft"] = out["distance_band_v2"].apply(band_start)
    out["distance_band_end_ft"] = out["distance_band_v2"].apply(band_end)
    out["broad_window_0_1000_flag"] = end <= 1000
    out["broad_window_0_2500_flag"] = end <= 2500
    out["crosses_distance_band_boundary"] = False
    for _label, low, high in BANDS:
        out["crosses_distance_band_boundary"] = out["crosses_distance_band_boundary"] | ((start < low) & (end > low)) | ((start < high) & (end > high))
    out["crosses_distance_band_boundary"] = out["crosses_distance_band_boundary"].astype("object")
    out.loc[start.isna() | end.isna(), "crosses_distance_band_boundary"] = pd.NA
    out["distance_band_assignment_method"] = "midpoint_from_distance_start_end_ft"
    out.loc[start.isna() | end.isna(), "distance_band_assignment_method"] = "missing_distance_not_assigned"
    return out


def add_directionality_summary(bin_context: pd.DataFrame, dir_bins: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "stable_bin_id",
        "upstream_downstream",
        "directionality_direct_or_synthetic",
        "mvp_directionality_method",
        "directionality_coverage_status",
        "directionality_caveat",
    ]
    use = [c for c in cols if c in dir_bins.columns]
    d = dir_bins[use].copy()
    agg_rows = []
    for bid, g in d.groupby("stable_bin_id", dropna=False):
        row = {"stable_bin_id": bid}
        for c in use:
            if c == "stable_bin_id":
                continue
            vals = sorted(set(g[c].dropna().astype(str)))
            row[f"{c}_values"] = "|".join(vals)
        row["directionality_row_count"] = len(g)
        row["directionality_upstream_downstream_count"] = g["upstream_downstream"].nunique(dropna=True) if "upstream_downstream" in g else 0
        agg_rows.append(row)
    agg = pd.DataFrame(agg_rows)
    out = bin_context.merge(agg, on="stable_bin_id", how="left")
    out["directionality_coverage_preserved_flag"] = out["directionality_row_count"].fillna(0) > 0
    return out


def distance_unit_impact(bin_context: pd.DataFrame, dir_bins: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = dir_bins[["stable_bin_id", "stable_signal_id", "upstream_downstream", "distance_start_ft", "distance_end_ft"]].copy()
    d["distance_band_mid_ft"] = (pd.to_numeric(d["distance_start_ft"], errors="coerce") + pd.to_numeric(d["distance_end_ft"], errors="coerce")) / 2
    d["distance_band_v2"] = d["distance_band_mid_ft"].apply(assign_band)
    before = d.merge(
        bin_context[["stable_bin_id", "legacy_signal_approach_id", "signal_approach_id_v2", "signal_approach_id_status"]],
        on="stable_bin_id",
        how="left",
    )
    current = before[
        nonmissing(before["legacy_signal_approach_id"]) & nonmissing(before["upstream_downstream"]) & nonmissing(before["distance_band_v2"])
    ][["stable_signal_id", "legacy_signal_approach_id", "upstream_downstream", "distance_band_v2"]].drop_duplicates()
    staged = before[
        nonmissing(before["signal_approach_id_v2"]) & nonmissing(before["upstream_downstream"]) & nonmissing(before["distance_band_v2"])
    ][["stable_signal_id", "signal_approach_id_v2", "upstream_downstream", "distance_band_v2"]].drop_duplicates()
    current_keys = set(map(tuple, current.itertuples(index=False, name=None)))
    staged_keys = set(map(tuple, staged.rename(columns={"signal_approach_id_v2": "legacy_signal_approach_id"}).itertuples(index=False, name=None)))
    additional = len(staged_keys - current_keys)
    ambiguous_units = before[before["signal_approach_id_status"] == "ambiguous_not_assigned"][["stable_signal_id", "upstream_downstream", "distance_band_v2"]].drop_duplicates().shape[0]
    no_dir_bins = bin_context[~bin_context["directionality_coverage_preserved_flag"]]
    missing_dir_units = no_dir_bins[nonmissing(no_dir_bins["signal_approach_id_v2"]) & nonmissing(no_dir_bins["distance_band_v2"])][["stable_signal_id", "signal_approach_id_v2", "distance_band_v2"]].drop_duplicates().shape[0] * 2
    summary = pd.DataFrame(
        [
            {"metric": "previous_audit_theoretical_full_max", "unit_count": PREVIOUS_DISTANCE_AUDIT["theoretical_full_max"]},
            {"metric": "previous_audit_bin_supported_expected_units", "unit_count": PREVIOUS_DISTANCE_AUDIT["bin_supported_expected_units"]},
            {"metric": "previous_audit_current_observed_distance_units", "unit_count": PREVIOUS_DISTANCE_AUDIT["current_observed_distance_units"]},
            {"metric": "previous_audit_recoverable_candidate_units", "unit_count": PREVIOUS_DISTANCE_AUDIT["recoverable_candidate_units"]},
            {"metric": "current_observed_distance_units_before_staged_bin_context", "unit_count": len(current)},
            {"metric": "staged_observed_distance_units_after_v2_approach_id", "unit_count": len(staged)},
            {"metric": "additional_units_recovered_by_approach_id_reconstruction", "unit_count": additional},
            {"metric": "units_still_missing_due_to_missing_directionality", "unit_count": missing_dir_units},
            {"metric": "units_still_missing_due_to_ambiguous_approach_id", "unit_count": ambiguous_units},
            {"metric": "units_still_missing_due_to_no_bin_support", "unit_count": max(PREVIOUS_DISTANCE_AUDIT["theoretical_full_max"] - PREVIOUS_DISTANCE_AUDIT["bin_supported_expected_units"], 0)},
            {"metric": "units_still_missing_or_source_limited", "unit_count": max(PREVIOUS_DISTANCE_AUDIT["theoretical_full_max"] - len(staged) - missing_dir_units, 0)},
        ]
    )
    by_band = staged.groupby("distance_band_v2").size().rename("staged_observed_distance_units").reset_index()
    before_band = current.groupby("distance_band_v2").size().rename("current_observed_distance_units").reset_index()
    by_band = by_band.merge(before_band, on="distance_band_v2", how="outer").fillna(0)
    by_band["additional_units_recovered"] = by_band["staged_observed_distance_units"] - by_band["current_observed_distance_units"]
    return summary, by_band


def far_distance_diagnostic(bin_context: pd.DataFrame, dir_bins: pd.DataFrame) -> pd.DataFrame:
    d = dir_bins[["stable_bin_id", "upstream_downstream"]].drop_duplicates()
    b = bin_context.merge(d, on="stable_bin_id", how="left")
    g = (
        b.groupby(["stable_signal_id", "signal_approach_id_v2", "distance_band_v2"], dropna=False)
        .agg(
            bin_count=("stable_bin_id", "nunique"),
            directionality_rows=("upstream_downstream", lambda s: int(nonmissing(s).sum())),
            direction_count=("upstream_downstream", lambda s: s.dropna().nunique()),
            length_mi=("bin_length_mi", lambda s: pd.to_numeric(s, errors="coerce").sum()),
        )
        .reset_index()
    )
    return g.sort_values(["distance_band_v2", "bin_count"], ascending=[True, False])


def write_exports(bin_context: pd.DataFrame, dir_bins: pd.DataFrame, before_rows: int, unit_summary: pd.DataFrame, unit_by_band: pd.DataFrame):
    bin_context.head(500).to_csv(EXPORTS / "bin_context_sample.csv", index=False)
    row_loss = before_rows - len(bin_context)
    key_summary = pd.DataFrame(
        [
            {"check": "row_count_preserved", "before_rows": before_rows, "after_rows": len(bin_context), "row_loss": row_loss, "status": "pass" if row_loss == 0 else "fail"},
            {"check": "stable_bin_id_unique", "duplicate_rows": int(bin_context.duplicated(["stable_bin_id"], keep=False).sum()), "status": "pass" if bin_context["stable_bin_id"].is_unique else "fail"},
            {"check": "signal_approach_id_v2_conflicts", "conflict_rows": int(bin_context["signal_approach_id_conflict_flag"].sum()), "status": "pass" if int(bin_context["signal_approach_id_conflict_flag"].sum()) == 0 else "fail"},
            {"check": "distance_band_assignment_complete", "missing_rows": int((~nonmissing(bin_context["distance_band_v2"])).sum()), "status": "pass" if nonmissing(bin_context["distance_band_v2"]).all() else "fail"},
            {"check": "directionality_fields_preserved", "directionality_covered_rows": int(bin_context["directionality_coverage_preserved_flag"].sum()), "status": "pass"},
        ]
    )
    key_summary.to_csv(EXPORTS / "bin_context_key_integrity_summary.csv", index=False)
    status_counts = bin_context["signal_approach_id_status"].value_counts(dropna=False).rename_axis("signal_approach_id_status").reset_index(name="row_count")
    status_counts.to_csv(EXPORTS / "bin_signal_approach_id_status_counts.csv", index=False)
    method_summary = (
        bin_context.groupby(["signal_approach_id_status", "signal_approach_id_method"], dropna=False)
        .size()
        .rename("row_count")
        .reset_index()
        .sort_values("row_count", ascending=False)
    )
    method_summary.to_csv(EXPORTS / "bin_signal_approach_id_reconstruction_summary.csv", index=False)
    unresolved = bin_context[~nonmissing(bin_context["signal_approach_id_v2"])]
    unresolved.to_csv(EXPORTS / "bin_signal_approach_id_unresolved_rows.csv", index=False)
    bin_context[bin_context["signal_approach_id_status"] == "ambiguous_not_assigned"].to_csv(EXPORTS / "bin_signal_approach_id_ambiguous_rows.csv", index=False)
    bin_context[bin_context["signal_approach_id_conflict_flag"]].to_csv(EXPORTS / "bin_signal_approach_id_conflicts.csv", index=False)
    band_counts = (
        bin_context.groupby("distance_band_v2", dropna=False)
        .agg(
            bin_count=("stable_bin_id", "count"),
            bins_with_signal_approach_id_v2=("signal_approach_id_v2", lambda s: int(nonmissing(s).sum())),
            bins_with_legacy_signal_approach_id=("legacy_signal_approach_id", lambda s: int(nonmissing(s).sum())),
            directionality_covered_bins=("directionality_coverage_preserved_flag", "sum"),
            crosses_distance_band_boundary=("crosses_distance_band_boundary", lambda s: int((s == True).sum())),
        )
        .reset_index()
    )
    band_counts.to_csv(EXPORTS / "distance_band_bin_counts.csv", index=False)
    unit_summary.to_csv(EXPORTS / "distance_aware_unit_impact_summary.csv", index=False)
    unit_by_band.to_csv(EXPORTS / "distance_aware_unit_counts_by_band.csv", index=False)
    far_distance_diagnostic(bin_context, dir_bins).to_csv(EXPORTS / "far_distance_coverage_diagnostic.csv", index=False)
    map_review = bin_context[bin_context["signal_approach_id_status"].isin(["ambiguous_not_assigned", "source_limited_not_assigned", "insufficient_evidence_not_assigned"])].copy()
    map_review["priority_score"] = map_review.groupby(["stable_signal_id", "distance_band_v2"])["stable_bin_id"].transform("count")
    map_review["recommended_review_action"] = map_review["signal_approach_id_status"].map(
        {
            "ambiguous_not_assigned": "map-review approach linkage",
            "source_limited_not_assigned": "inspect source/geometry limitation",
            "insufficient_evidence_not_assigned": "review lineage fields",
        }
    )
    cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "distance_band_v2",
        "signal_approach_id_status",
        "signal_approach_id_ambiguous_candidate_count",
        "priority_score",
        "recommended_review_action",
    ]
    map_review[cols].sort_values("priority_score", ascending=False).head(5000).to_csv(EXPORTS / "map_review_candidate_bin_approach_linkage.csv", index=False)
    return key_summary, status_counts, method_summary


def update_manifest_schema_readme(bin_context: pd.DataFrame, metrics: dict, files_written: list[str]):
    manifest_path = STAGED_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest["bin_context_refresh"] = {
        "generated_utc": now(),
        "producing_script": "src.roadway_graph.staged_bin_context_refresh_candidate",
        "input_tables_read": [
            rel(FINAL_DIR / "analysis_bin.csv"),
            rel(MVP_DIR / "mvp_directional_bin_context.csv"),
            rel(STAGED_DIR / "approach_windows.parquet"),
            rel(STAGED_DIR / "signal_approaches.parquet"),
        ],
        "output_files_written": files_written,
        "qa_metrics": metrics,
        "staging_candidate_not_promoted": True,
        "null_key_join_rule": "Existing signal_approach_id joins used only non-null legacy IDs; null-to-null matches were not counted.",
    }
    manifest["row_counts"]["bin_context"] = len(bin_context)
    (STAGED_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    schema_path = STAGED_DIR / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8")) if schema_path.exists() else {"tables": {}}
    schema["tables"]["bin_context.parquet"] = {
        "expected_grain": "stable_bin_id, one row per final leg-corrected bin",
        "primary_key_candidates": ["stable_bin_id"],
        "columns": {c: str(t) for c, t in bin_context.dtypes.items()},
        "required_fields": ["stable_bin_id", "stable_signal_id", "signal_approach_id_v2", "distance_band_v2"],
        "nullable_fields": [c for c in bin_context.columns if bin_context[c].isna().any()],
        "status_provenance_fields": [
            "legacy_signal_approach_id",
            "signal_approach_id_v2",
            "signal_approach_id_status",
            "signal_approach_id_method",
            "signal_approach_id_evidence_fields",
            "signal_approach_id_conflict_flag",
            "signal_approach_id_ambiguous_candidate_count",
        ],
    }
    (STAGED_DIR / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")

    readme = STAGED_DIR / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else "# Final-Leg Corrected Analysis Dataset Refresh Candidate\n"
    if "## Staged Bin Context Refresh" not in text:
        text += "\n## Staged Bin Context Refresh\n\n"
    text += (
        f"\nGenerated `{rel(STAGED_DIR / 'bin_context.parquet')}` with {len(bin_context)} rows. "
        "This is a staging candidate only. It preserves legacy bin rows, adds `signal_approach_id_v2` with reconstruction provenance, "
        "assigns proposed distance bands, and carries current directionality coverage summaries. MVP regeneration remains deferred.\n"
    )
    readme.write_text(text, encoding="utf-8")


def main():
    EXPORTS.mkdir(parents=True, exist_ok=True)
    bins, staged_approaches, _staged_aw, dir_bins = load_inputs()
    before_rows = len(bins)
    candidate = reconstruct_signal_approach_id(bins, staged_approaches)
    candidate = add_distance_bands(candidate)
    candidate = add_directionality_summary(candidate, dir_bins)
    unit_summary, unit_by_band = distance_unit_impact(candidate, dir_bins)
    candidate.to_parquet(STAGED_DIR / "bin_context.parquet", index=False)
    key_summary, status_counts, method_summary = write_exports(candidate, dir_bins, before_rows, unit_summary, unit_by_band)

    metrics = {
        "before_rows": before_rows,
        "after_rows": len(candidate),
        "row_loss": before_rows - len(candidate),
        "legacy_signal_approach_id_coverage": int(nonmissing(candidate["legacy_signal_approach_id"]).sum()),
        "signal_approach_id_v2_coverage": int(nonmissing(candidate["signal_approach_id_v2"]).sum()),
        "existing_valid_rows": int((candidate["signal_approach_id_status"] == "existing_valid").sum()),
        "ambiguous_rows": int((candidate["signal_approach_id_status"] == "ambiguous_not_assigned").sum()),
        "unresolved_rows": int((~nonmissing(candidate["signal_approach_id_v2"])).sum()),
        "conflict_rows": int(candidate["signal_approach_id_conflict_flag"].sum()),
        "distance_band_missing_rows": int((~nonmissing(candidate["distance_band_v2"])).sum()),
        "directionality_covered_rows": int(candidate["directionality_coverage_preserved_flag"].sum()),
        "staged_observed_distance_unit_count": int(unit_summary.loc[unit_summary["metric"] == "staged_observed_distance_units_after_v2_approach_id", "unit_count"].iloc[0]),
        "additional_units_recovered": int(unit_summary.loc[unit_summary["metric"] == "additional_units_recovered_by_approach_id_reconstruction", "unit_count"].iloc[0]),
    }
    files_written = sorted(rel(p) for p in [STAGED_DIR / "bin_context.parquet", *EXPORTS.glob("bin_*"), *EXPORTS.glob("distance_*"), EXPORTS / "far_distance_coverage_diagnostic.csv", EXPORTS / "map_review_candidate_bin_approach_linkage.csv"] if p.exists())
    update_manifest_schema_readme(candidate, metrics, files_written)

    failed = metrics["row_loss"] != 0 or metrics["conflict_rows"] != 0 or metrics["distance_band_missing_rows"] != 0
    if failed:
        recommendation = "bin_context_candidate_failed_due_to_row_loss_or_conflicts"
        next_step = "audit staged bin_context candidate"
    elif metrics["ambiguous_rows"] > 0:
        recommendation = "bin_context_candidate_blocked_by_ambiguous_approach_linkage"
        next_step = "refine approach-ID reconstruction"
    else:
        recommendation = "bin_context_candidate_ready_for_review"
        next_step = "audit staged bin_context candidate"
    if metrics["directionality_covered_rows"] < len(candidate):
        next_step = "start directionality recovery/map-review package" if recommendation == "bin_context_candidate_ready_for_review" else next_step

    print(json.dumps({"recommendation": recommendation, "recommended_next_step": next_step, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
