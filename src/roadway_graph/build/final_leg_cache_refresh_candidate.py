"""Build a staged final-leg corrected analysis cache refresh candidate.

This is intentionally conservative. It writes a Parquet-first staging candidate
without modifying the current canonical root products or regenerating the MVP.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
FINAL_DIR = REPO / "work" / "roadway_graph" / "analysis" / "final_leg_corrected_analysis_dataset"
MVP_DIR = REPO / "work" / "roadway_graph" / "analysis" / "mvp_dataset"
OUT_DIR = REPO / "work" / "roadway_graph" / "analysis" / "_staging" / "final_leg_corrected_analysis_dataset_refresh_candidate"
EXPORTS = OUT_DIR / "exports"

ARTIFACTS = [
    REPO / "artifacts" / "normalized" / "signals.parquet",
    REPO / "artifacts" / "normalized" / "roads.parquet",
    REPO / "artifacts" / "normalized" / "speed.parquet",
    REPO / "artifacts" / "normalized" / "aadt.parquet",
]
OPTIONAL_ARTIFACTS = [
    REPO / "artifacts" / "normalized" / "access_v2.parquet",
    REPO / "artifacts" / "normalized" / "crashes.parquet",
]

WINDOW_MAP = {
    "0_1000": "0-1,000 ft",
    "1000_2500": "1,000-2,500 ft",
}

SPEED_BINS = [
    (0, 25, "<=25 mph"),
    (25, 35, "26-35 mph"),
    (35, 45, "36-45 mph"),
    (45, 10_000, "46+ mph"),
]

AADT_BINS = [
    (0, 5_000, "<5k"),
    (5_000, 15_000, "5k-15k"),
    (15_000, 30_000, "15k-30k"),
    (30_000, 10**12, "30k+"),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def nonmissing(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & (text != "") & (~text.str.lower().isin(["nan", "none", "null", "<missing>"]))


def stable_hash(*parts: object, length: int = 16) -> str:
    text = "|".join("" if pd.isna(p) else str(p) for p in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def reconstructed_id(stable_signal_id: str, approach_label: str) -> str:
    return f"sa_v2_{stable_hash(stable_signal_id, approach_label)}"


def access_band_ascii(value: object) -> object:
    if pd.isna(value):
        return value
    return str(value).replace("–", "-").replace("—", "-")


def category_from_bins(value: object, bins: list[tuple[float, float, str]]) -> object:
    if pd.isna(value):
        return pd.NA
    try:
        v = float(value)
    except Exception:
        return pd.NA
    for low, high, label in bins:
        if low <= v <= high:
            return label
    return pd.NA


def read_artifact_metadata(path: Path) -> dict:
    try:
        import pyarrow.parquet as pq

        pf = pq.ParquetFile(path)
        return {
            "path": rel(path),
            "row_count": pf.metadata.num_rows,
            "columns": list(pf.schema_arrow.names),
            "status": "metadata_read",
        }
    except Exception as exc:
        return {"path": rel(path), "row_count": None, "columns": [], "status": "metadata_error", "error": str(exc)}


def inventory_current_tables() -> list[dict]:
    rows = []
    for path in sorted(FINAL_DIR.glob("*.csv")):
        try:
            cols = list(pd.read_csv(path, nrows=0).columns)
            with path.open("rb") as f:
                n = max(sum(1 for _ in f) - 1, 0)
            rows.append(
                {
                    "table": path.name,
                    "row_count": n,
                    "column_count": len(cols),
                    "columns": cols,
                    "key_fields": "|".join([c for c in ["stable_signal_id", "signal_approach_id", "signal_window", "stable_bin_id"] if c in cols]),
                }
            )
        except Exception as exc:
            rows.append({"table": path.name, "row_count": None, "column_count": None, "error": str(exc)})
    return rows


def build_bin_numeric_rollup(bin_df: pd.DataFrame) -> pd.DataFrame:
    df = bin_df.copy()
    df["signal_window"] = df["analysis_window"].map(WINDOW_MAP).fillna(df["analysis_window"])
    df["speed_limit_mph_num"] = pd.to_numeric(df.get("speed_limit_mph"), errors="coerce")
    df["aadt_num"] = pd.to_numeric(df.get("aadt"), errors="coerce")
    df["bin_length_mi_num"] = pd.to_numeric(df.get("bin_length_mi"), errors="coerce")
    df["aadt_exposure_denominator_num"] = pd.to_numeric(df.get("aadt_exposure_denominator"), errors="coerce")

    def weighted_avg(group: pd.DataFrame, value_col: str) -> float | pd.NA:
        values = group[value_col]
        weights = group["bin_length_mi_num"]
        mask = values.notna() & weights.notna() & (weights > 0)
        if not mask.any():
            return pd.NA
        return float((values[mask] * weights[mask]).sum() / weights[mask].sum())

    rows = []
    group_cols = ["stable_signal_id", "signal_approach_id", "signal_window"]
    for keys, group in df.groupby(group_cols, dropna=False):
        stable_signal_id, signal_approach_id, signal_window = keys
        speed = weighted_avg(group, "speed_limit_mph_num")
        aadt = weighted_avg(group, "aadt_num")
        length = group["bin_length_mi_num"].sum(min_count=1)
        exposure = group["aadt_exposure_denominator_num"].sum(min_count=1)
        rows.append(
            {
                "stable_signal_id": stable_signal_id,
                "signal_approach_id": signal_approach_id,
                "signal_window": signal_window,
                "bin_rollup_speed": speed,
                "bin_rollup_aadt": aadt,
                "bin_rollup_length_mi": length,
                "bin_rollup_exposure": exposure,
                "bin_rollup_bin_count": len(group),
                "bin_rollup_source": "analysis_bin.csv",
            }
        )
    return pd.DataFrame(rows)


def build_candidate_approach_windows(aw: pd.DataFrame, bin_rollup: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    candidate = aw.copy()
    candidate.insert(0, "pre_refresh_row_id", range(len(candidate)))
    candidate["pre_refresh_source_table"] = "analysis_signal_approach_window.csv"
    candidate["legacy_signal_approach_id"] = candidate["signal_approach_id"]
    candidate["signal_approach_id_was_missing_pre_refresh"] = ~nonmissing(candidate["signal_approach_id"])
    candidate["source_artifact_paths_used"] = "|".join(rel(p) for p in ARTIFACTS if p.exists())

    existing_mask = nonmissing(candidate["signal_approach_id"])
    candidate["approach_identity_status"] = "existing_valid"
    candidate["approach_identity_method"] = "preserved_existing_signal_approach_id"
    candidate["approach_identity_evidence_fields"] = "legacy_signal_approach_id|stable_signal_id|signal_window"
    candidate["signal_approach_key"] = candidate["signal_approach_id"].astype("string")

    missing = candidate.loc[~existing_mask].copy()
    deterministic_groups = set()
    ambiguous_groups = set()
    if not missing.empty and {"stable_signal_id", "approach_label", "signal_window"}.issubset(missing.columns):
        group_sizes = missing.groupby(["stable_signal_id", "approach_label"], dropna=False)["signal_window"].nunique()
        total_rows = missing.groupby(["stable_signal_id", "approach_label"], dropna=False).size()
        for key, window_count in group_sizes.items():
            # Current canonical windows have two expected rows per approach. Assign
            # only where a stable per-signal approach label repeats across windows.
            if window_count >= 2 and total_rows.loc[key] == window_count:
                deterministic_groups.add(key)
            else:
                ambiguous_groups.add(key)

    for idx, row in candidate.loc[~existing_mask].iterrows():
        key = (row.get("stable_signal_id"), row.get("approach_label"))
        if key in deterministic_groups and pd.notna(key[0]) and pd.notna(key[1]):
            new_id = reconstructed_id(str(key[0]), str(key[1]))
            candidate.at[idx, "signal_approach_id"] = new_id
            candidate.at[idx, "signal_approach_key"] = f"{key[0]}|{key[1]}"
            candidate.at[idx, "approach_identity_status"] = "reconstructed_deterministic"
            candidate.at[idx, "approach_identity_method"] = "stable_signal_id_plus_approach_label_repeated_across_windows"
            candidate.at[idx, "approach_identity_evidence_fields"] = "stable_signal_id|approach_label|signal_window"
        elif key in ambiguous_groups:
            candidate.at[idx, "signal_approach_key"] = pd.NA
            candidate.at[idx, "approach_identity_status"] = "ambiguous_not_assigned"
            candidate.at[idx, "approach_identity_method"] = "missing_approach_label_window_pattern_not_unique"
            candidate.at[idx, "approach_identity_evidence_fields"] = "stable_signal_id|approach_label|signal_window"
        else:
            candidate.at[idx, "signal_approach_key"] = pd.NA
            candidate.at[idx, "approach_identity_status"] = "insufficient_columns_to_assess"
            candidate.at[idx, "approach_identity_method"] = "no_deterministic_canonical_approach_identity"
            candidate.at[idx, "approach_identity_evidence_fields"] = "stable_signal_id|approach_label|signal_window"

    # Numeric context: prefer current bin-level rollup when it can be joined by
    # non-null signal_approach_id. Prevent null-to-null matches by splitting.
    candidate["numeric_speed_pre_refresh"] = pd.to_numeric(candidate.get("representative_speed_limit_mph"), errors="coerce")
    candidate["numeric_aadt_pre_refresh"] = pd.to_numeric(candidate.get("representative_aadt"), errors="coerce")
    candidate["exposure_denominator_pre_refresh"] = pd.to_numeric(candidate.get("exposure_denominator"), errors="coerce")

    nonnull_for_join = candidate[nonmissing(candidate["legacy_signal_approach_id"])].copy()
    null_for_join = candidate[~nonmissing(candidate["legacy_signal_approach_id"])].copy()
    rollup_nonnull = bin_rollup[nonmissing(bin_rollup["signal_approach_id"])].copy()
    merge_cols = ["stable_signal_id", "signal_approach_id", "signal_window"]
    nonnull_for_join = nonnull_for_join.merge(
        rollup_nonnull,
        on=merge_cols,
        how="left",
        validate="many_to_one",
        suffixes=("", "_rollup"),
    )

    # For reconstructed null-key rows, use the null-bin rollup only when there is
    # exactly one null approach candidate per signal/window. This is not a
    # signal_approach_id join and is flagged separately.
    null_rollup = bin_rollup[~nonmissing(bin_rollup["signal_approach_id"])].copy()
    null_counts = null_rollup.groupby(["stable_signal_id", "signal_window"]).size().rename("null_rollup_group_count").reset_index()
    null_rollup = null_rollup.merge(null_counts, on=["stable_signal_id", "signal_window"], how="left")
    null_rollup = null_rollup[null_rollup["null_rollup_group_count"] == 1]
    null_for_join = null_for_join.merge(
        null_rollup.drop(columns=["signal_approach_id"]),
        on=["stable_signal_id", "signal_window"],
        how="left",
        validate="many_to_one",
        suffixes=("", "_rollup"),
    )

    candidate = pd.concat([nonnull_for_join, null_for_join], ignore_index=True).sort_values("pre_refresh_row_id")
    candidate["numeric_speed"] = candidate["bin_rollup_speed"].combine_first(candidate["numeric_speed_pre_refresh"])
    candidate["numeric_aadt"] = candidate["bin_rollup_aadt"].combine_first(candidate["numeric_aadt_pre_refresh"])
    candidate["refreshed_length_mi"] = candidate["bin_rollup_length_mi"]
    candidate["exposure_denominator_candidate"] = candidate["bin_rollup_exposure"].combine_first(candidate["exposure_denominator_pre_refresh"])
    candidate["numeric_context_method"] = "carried_forward_from_pre_refresh"
    candidate.loc[candidate["bin_rollup_bin_count"].notna(), "numeric_context_method"] = "refreshed_from_analysis_bin_rollup"

    candidate["speed_category"] = candidate["numeric_speed"].apply(lambda v: category_from_bins(v, SPEED_BINS))
    candidate["aadt_category"] = candidate["numeric_aadt"].apply(lambda v: category_from_bins(v, AADT_BINS))
    # Preserve original public bands too.
    candidate["speed_band_pre_refresh"] = candidate.get("speed_band")
    candidate["aadt_band_pre_refresh"] = candidate.get("aadt_band")
    candidate["access_count_band_ascii"] = candidate.get("untyped_access_count_band", pd.Series(pd.NA, index=candidate.index)).apply(access_band_ascii)

    length = pd.to_numeric(candidate["refreshed_length_mi"], errors="coerce")
    aadt = pd.to_numeric(candidate["numeric_aadt"], errors="coerce")
    exposure = pd.to_numeric(candidate["exposure_denominator_candidate"], errors="coerce")
    candidate["exposure_status"] = "exposure_ready"
    candidate.loc[aadt.isna(), "exposure_status"] = "missing_aadt"
    candidate.loc[aadt.notna() & (aadt <= 0), "exposure_status"] = "zero_or_invalid_aadt"
    candidate.loc[aadt.notna() & length.isna(), "exposure_status"] = "missing_length_or_window"
    candidate.loc[aadt.notna() & length.notna() & (length <= 0), "exposure_status"] = "zero_or_invalid_length"
    candidate.loc[aadt.notna() & length.notna() & (length > 0) & exposure.isna(), "exposure_status"] = "insufficient_columns_to_compute"
    candidate.loc[aadt.notna() & length.notna() & (length > 0) & exposure.notna() & (exposure <= 0), "exposure_status"] = "zero_or_invalid_aadt"
    candidate["rate_eligibility_status"] = "rate_eligible_inputs_ready"
    candidate.loc[candidate["exposure_status"] != "exposure_ready", "rate_eligibility_status"] = "blocked_by_" + candidate["exposure_status"].astype(str)
    candidate.loc[~nonmissing(candidate["signal_approach_id"]), "rate_eligibility_status"] = "blocked_by_missing_signal_approach_id"

    approach_rows = []
    group_cols = ["stable_signal_id", "signal_approach_id"]
    for keys, group in candidate[nonmissing(candidate["signal_approach_id"])].groupby(group_cols, dropna=False):
        stable_signal_id, signal_approach_id = keys
        status_counts = group["approach_identity_status"].value_counts().to_dict()
        approach_rows.append(
            {
                "signal_approach_id": signal_approach_id,
                "signal_approach_key": group["signal_approach_key"].dropna().astype(str).iloc[0] if group["signal_approach_key"].notna().any() else signal_approach_id,
                "stable_signal_id": stable_signal_id,
                "approach_identity_method": group["approach_identity_method"].dropna().astype(str).iloc[0],
                "approach_identity_status": group["approach_identity_status"].dropna().astype(str).iloc[0],
                "approach_identity_evidence_fields": group["approach_identity_evidence_fields"].dropna().astype(str).iloc[0],
                "legacy_signal_approach_id": group["legacy_signal_approach_id"].dropna().astype(str).iloc[0] if group["legacy_signal_approach_id"].notna().any() else pd.NA,
                "source_artifact_paths_used": group["source_artifact_paths_used"].dropna().astype(str).iloc[0],
                "window_count": group["signal_window"].nunique(),
                "approach_window_row_count": len(group),
                "approach_label": group["approach_label"].dropna().astype(str).iloc[0] if "approach_label" in group and group["approach_label"].notna().any() else pd.NA,
                "status_counts_json": json.dumps(status_counts, ensure_ascii=True),
            }
        )
    approaches = pd.DataFrame(approach_rows)
    return candidate, approaches


def summarize(candidate: pd.DataFrame, pre: pd.DataFrame, approaches: pd.DataFrame) -> dict[str, pd.DataFrame | list[dict]]:
    row_loss = len(pre) - len(candidate)
    existing_valid = int((candidate["approach_identity_status"] == "existing_valid").sum())
    reconstructed = int((candidate["approach_identity_status"] == "reconstructed_deterministic").sum())
    unresolved = int((~nonmissing(candidate["signal_approach_id"])).sum())
    invalid_conflicting = 0

    completeness = []
    for field in ["signal_approach_id", "numeric_speed", "numeric_aadt", "exposure_denominator_candidate", "spatial_50ft_crash_count"]:
        if field in candidate.columns:
            miss = int((~nonmissing(candidate[field])).sum())
            completeness.append({"table": "approach_windows", "field": field, "row_count": len(candidate), "missing_count": miss, "missing_pct": miss / len(candidate) if len(candidate) else 0})

    key_rows = []
    grain = ["stable_signal_id", "signal_approach_id", "signal_window"]
    complete_key = candidate[grain].copy()
    complete_key["_missing_key"] = False
    for col in grain:
        complete_key["_missing_key"] = complete_key["_missing_key"] | (~nonmissing(complete_key[col]))
    checked = complete_key[~complete_key["_missing_key"]]
    dup_groups = checked.duplicated(grain, keep=False).sum()
    key_rows.append(
        {
            "check": "approach_windows_expected_grain",
            "grain_fields": "|".join(grain),
            "row_count": len(candidate),
            "rows_with_complete_key": len(checked),
            "rows_with_missing_key": int(complete_key["_missing_key"].sum()),
            "duplicate_rows_at_grain": int(dup_groups),
            "status": "pass" if dup_groups == 0 and row_loss == 0 else "fail",
        }
    )
    duplicate_approaches = int(approaches.duplicated(["stable_signal_id", "signal_approach_id"], keep=False).sum()) if not approaches.empty else 0
    key_rows.append(
        {
            "check": "signal_approaches_unique_within_signal",
            "grain_fields": "stable_signal_id|signal_approach_id",
            "row_count": len(approaches),
            "duplicate_rows_at_grain": duplicate_approaches,
            "status": "pass" if duplicate_approaches == 0 else "fail",
        }
    )
    window_counts = candidate[nonmissing(candidate["signal_approach_id"])].groupby("signal_approach_id")["signal_window"].nunique()
    key_rows.append(
        {
            "check": "signal_approach_repeats_across_windows",
            "grain_fields": "signal_approach_id",
            "row_count": int(window_counts.size),
            "approaches_with_two_or_more_windows": int((window_counts >= 2).sum()),
            "approaches_with_one_window": int((window_counts == 1).sum()),
            "status": "review",
        }
    )

    recon_summary = (
        candidate.groupby("approach_identity_status", dropna=False)
        .size()
        .rename("row_count")
        .reset_index()
        .sort_values("row_count", ascending=False)
    )
    exposure_summary = candidate.groupby("exposure_status", dropna=False).size().rename("row_count").reset_index()

    pre_vs = []
    for label, df, speed_col, aadt_col, exp_col in [
        ("pre_refresh", pre, "representative_speed_limit_mph", "representative_aadt", "exposure_denominator"),
        ("candidate", candidate, "numeric_speed", "numeric_aadt", "exposure_denominator_candidate"),
    ]:
        pre_vs.append(
            {
                "version": label,
                "row_count": len(df),
                "missing_signal_approach_id": int((~nonmissing(df["signal_approach_id"])).sum()),
                "missing_speed": int((~nonmissing(df[speed_col])).sum()),
                "missing_aadt": int((~nonmissing(df[aadt_col])).sum()),
                "missing_exposure": int((~nonmissing(df[exp_col])).sum()),
                "zero_exposure": int((pd.to_numeric(df[exp_col], errors="coerce") == 0).sum()),
            }
        )
    numeric_summary = []
    for field in ["numeric_speed", "numeric_aadt", "exposure_denominator_candidate", "refreshed_length_mi"]:
        miss = int((~nonmissing(candidate[field])).sum())
        zero = int((pd.to_numeric(candidate[field], errors="coerce") == 0).sum())
        numeric_summary.append({"field": field, "row_count": len(candidate), "missing_count": miss, "zero_count": zero, "complete_count": len(candidate) - miss})

    return {
        "completeness": pd.DataFrame(completeness),
        "key_integrity": pd.DataFrame(key_rows),
        "reconstruction_summary": recon_summary,
        "exposure_summary": exposure_summary,
        "pre_vs_candidate": pd.DataFrame(pre_vs),
        "numeric_summary": pd.DataFrame(numeric_summary),
        "metrics": {
            "pre_refresh_rows": len(pre),
            "candidate_rows": len(candidate),
            "row_loss": row_loss,
            "existing_valid_rows": existing_valid,
            "reconstructed_rows": reconstructed,
            "unresolved_signal_approach_id_rows": unresolved,
            "invalid_or_conflicting_existing_id_rows": invalid_conflicting,
            "exposure_ready_rows": int((candidate["exposure_status"] == "exposure_ready").sum()),
            "duplicate_rows_at_approach_window_grain": int(dup_groups),
            "duplicate_signal_approach_rows": duplicate_approaches,
        },
    }


def write_schema(candidate: pd.DataFrame, approaches: pd.DataFrame) -> None:
    schema = {
        "tables": {
            "approach_windows.parquet": {
                "expected_grain": "stable_signal_id x signal_approach_id x signal_window, for rows with assigned signal_approach_id",
                "primary_key_candidates": ["stable_signal_id", "signal_approach_id", "signal_window"],
                "columns": {col: str(dtype) for col, dtype in candidate.dtypes.items()},
                "required_fields": ["pre_refresh_row_id", "stable_signal_id", "signal_window", "approach_identity_status", "rate_eligibility_status"],
                "nullable_fields": [col for col in candidate.columns if candidate[col].isna().any()],
                "status_provenance_fields": [
                    "legacy_signal_approach_id",
                    "approach_identity_method",
                    "approach_identity_status",
                    "approach_identity_evidence_fields",
                    "source_artifact_paths_used",
                    "numeric_context_method",
                    "exposure_status",
                    "rate_eligibility_status",
                ],
            },
            "signal_approaches.parquet": {
                "expected_grain": "stable_signal_id x signal_approach_id",
                "primary_key_candidates": ["stable_signal_id", "signal_approach_id"],
                "columns": {col: str(dtype) for col, dtype in approaches.dtypes.items()},
                "required_fields": ["signal_approach_id", "signal_approach_key", "stable_signal_id", "approach_identity_status"],
                "nullable_fields": [col for col in approaches.columns if approaches[col].isna().any()],
            },
        }
    }
    (OUT_DIR / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")


def write_readme(metrics: dict) -> None:
    text = f"""# Final-Leg Corrected Analysis Dataset Refresh Candidate

This is a staged final-leg refresh candidate, not a promoted canonical cache. The current canonical root products remain frozen as pre-refresh evidence.

Parquet files in this folder are candidate canonical cache tables. CSV files under `exports/` are derivative review outputs.

`signal_approach_id` is a project-created key. Existing non-null IDs were preserved. Missing IDs were reconstructed only where deterministic from current canonical fields, and unresolved rows are preserved with status flags.

MVP regeneration is deferred until this candidate passes QA.

## Headline QA

- Pre-refresh approach-window rows: {metrics['pre_refresh_rows']}
- Candidate approach-window rows: {metrics['candidate_rows']}
- Row loss: {metrics['row_loss']}
- Existing valid `signal_approach_id` rows: {metrics['existing_valid_rows']}
- Deterministically reconstructed rows: {metrics['reconstructed_rows']}
- Unresolved `signal_approach_id` rows: {metrics['unresolved_signal_approach_id_rows']}
- Exposure-ready rows: {metrics['exposure_ready_rows']}

## Deferred

`bin_context.parquet` is deferred in this candidate. The current bin-level table has extensive missing `signal_approach_id` values and should be refreshed only after this approach identity candidate is reviewed.
"""
    (OUT_DIR / "README.md").write_text(text, encoding="utf-8")


def main() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    EXPORTS.mkdir(parents=True, exist_ok=True)

    artifact_metadata = [read_artifact_metadata(p) for p in ARTIFACTS + OPTIONAL_ARTIFACTS if p.exists()]
    artifacts_read = [m["path"] for m in artifact_metadata]

    inventory = inventory_current_tables()
    aw = pd.read_csv(FINAL_DIR / "analysis_signal_approach_window.csv", low_memory=False)
    bin_cols = [
        "stable_signal_id",
        "signal_approach_id",
        "analysis_window",
        "speed_limit_mph",
        "aadt",
        "bin_length_mi",
        "aadt_exposure_denominator",
    ]
    bins = pd.read_csv(FINAL_DIR / "analysis_bin.csv", usecols=bin_cols, low_memory=False)
    bin_rollup = build_bin_numeric_rollup(bins)

    candidate, approaches = build_candidate_approach_windows(aw, bin_rollup)
    summaries = summarize(candidate, aw, approaches)
    metrics = summaries["metrics"]

    candidate.to_parquet(OUT_DIR / "approach_windows.parquet", index=False)
    approaches.to_parquet(OUT_DIR / "signal_approaches.parquet", index=False)

    candidate.head(500).to_csv(EXPORTS / "approach_windows_sample.csv", index=False)
    summaries["completeness"].to_csv(EXPORTS / "completeness_summary.csv", index=False)
    summaries["key_integrity"].to_csv(EXPORTS / "key_integrity_summary.csv", index=False)
    summaries["reconstruction_summary"].to_csv(EXPORTS / "signal_approach_id_reconstruction_summary.csv", index=False)
    candidate[~nonmissing(candidate["signal_approach_id"])].to_csv(EXPORTS / "signal_approach_id_unresolved_rows.csv", index=False)
    candidate[candidate["approach_identity_status"] == "reconstructed_deterministic"].to_csv(EXPORTS / "signal_approach_id_reconstructed_rows.csv", index=False)
    summaries["numeric_summary"].to_csv(EXPORTS / "numeric_context_summary.csv", index=False)
    summaries["exposure_summary"].to_csv(EXPORTS / "exposure_status_summary.csv", index=False)
    summaries["pre_vs_candidate"].to_csv(EXPORTS / "pre_vs_candidate_comparison.csv", index=False)

    write_schema(candidate, approaches)
    write_readme(metrics)

    candidate_failed = metrics["row_loss"] != 0 or metrics["duplicate_rows_at_approach_window_grain"] != 0 or metrics["duplicate_signal_approach_rows"] != 0
    if candidate_failed:
        recommendation = "candidate_failed_due_to_row_loss_or_key_duplicates"
        next_step = "audit this candidate"
    elif metrics["unresolved_signal_approach_id_rows"] > 0:
        recommendation = "candidate_blocked_needs_more_reconstruction"
        next_step = "refine signal_approach_id reconstruction"
    else:
        recommendation = "candidate_ready_for_review"
        next_step = "audit this candidate"
    if metrics["exposure_ready_rows"] < metrics["candidate_rows"]:
        next_step = "refresh numeric context further" if recommendation == "candidate_ready_for_review" else next_step

    manifest = {
        "generated_utc": now(),
        "producing_script": "src.roadway_graph.build.final_leg_cache_refresh_candidate",
        "staging_candidate_not_promoted": True,
        "input_canonical_products_read": [rel(FINAL_DIR), rel(MVP_DIR)],
        "artifact_files_read": artifacts_read,
        "artifact_metadata": artifact_metadata,
        "current_final_leg_inventory": inventory,
        "output_files_written": sorted(rel(p) for p in OUT_DIR.rglob("*") if p.is_file()),
        "row_counts": {
            "approach_windows": len(candidate),
            "signal_approaches": len(approaches),
            "bin_context": "deferred",
        },
        "key_qa_metrics": metrics,
        "unresolved_blocker_counts": {
            "unresolved_signal_approach_id_rows": metrics["unresolved_signal_approach_id_rows"],
            "not_exposure_ready_rows": metrics["candidate_rows"] - metrics["exposure_ready_rows"],
        },
        "promotion_guardrail": "Do not promote this candidate until QA review passes.",
        "candidate_recommendation": recommendation,
        "recommended_next_step": next_step,
        "bin_context_status": "deferred_due_to_missing_signal_approach_id_in_current_bin_context",
        "null_key_join_rule": "Joins using signal_approach_id were applied only to rows with non-null legacy_signal_approach_id; null-to-null matches were not counted as valid joins.",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({"candidate_recommendation": recommendation, "recommended_next_step": next_step, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    main()
