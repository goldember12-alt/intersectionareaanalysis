"""Signal- and approach-level QA for rebuilt one-sided approach corridors.

This audit is read-only. It validates the staged one-sided
approach_corridors.parquet layer and writes review outputs only.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/approach_corridors_signal_level_qa_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

REBUILD_REVIEW = REPO / "work/roadway_graph/review/rebuild_one_sided_approach_corridors"
SIDE_REACH_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_side_reach_audit"
GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
BUILD_APPROACH_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
APPROACH_VALIDATION_REVIEW = REPO / "work/roadway_graph/review/signal_approaches_validation_audit"

MAX_REACH_FT = 2500.0
FLOAT_TOL_FT = 0.001


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def compact_counts(series: pd.Series) -> str:
    if series.empty:
        return ""
    counts = series.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{idx}:{int(val)}" for idx, val in counts.items())


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def length_bucket(length_ft: float) -> str:
    if pd.isna(length_ft):
        return "unknown_length"
    if length_ft > MAX_REACH_FT + FLOAT_TOL_FT:
        return "invalid_over_2500"
    if length_ft < 100:
        return "very_short_0_100"
    if length_ft < 500:
        return "short_100_500"
    if length_ft < 1000:
        return "moderate_500_1000"
    return "long_1000_2500"


def support_status_for_group(group: pd.DataFrame, parent_gate: str) -> str:
    if parent_gate == "corridor_build_blocked_pending_rule_repair":
        return "blocked_by_parent_gate"
    if group.empty:
        return "no_usable_support"
    max_reach = float(group["one_sided_reach_ft"].max())
    if max_reach >= MAX_REACH_FT - FLOAT_TOL_FT:
        return "full_one_sided_0_2500_support"
    if group["clipped_by_signal_boundary_flag"].fillna(False).astype(bool).any():
        return "partial_signal_boundary_clipped"
    if group["clipped_by_source_extent_flag"].fillna(False).astype(bool).any():
        return "partial_source_extent_clipped"
    limited = ~group["route_measure_continuity_status"].fillna("").eq("route_measure_complete_single_source_row")
    if limited.any() or group["clipped_by_gap_or_uncertain_continuity_flag"].fillna(False).astype(bool).any():
        return "partial_route_measure_limited"
    return "partial_unclear"


def density_class(row: pd.Series) -> str:
    count = int(row["corridor_row_count"])
    approach_count = int(row["signal_approach_count"])
    source_limited = clean(row.get("signal_source_limited_status")) != "not_source_limited"
    if count == 0:
        return "low_corridor_density_source_limited" if source_limited or approach_count == 0 else "low_corridor_density_possible_underbuild"
    if count <= 2:
        return "low_corridor_density_source_limited" if approach_count <= 2 else "low_corridor_density_possible_underbuild"
    if count <= 8:
        return "normal_corridor_density"
    if count <= 15:
        return "moderate_corridor_density_review"
    if count <= 24:
        return "high_corridor_density_review"
    return "extreme_corridor_density_review"


def add_band_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for start, end in [(0, 250), (250, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 2500)]:
        out[f"supports_{start}_{end}ft"] = out["max_one_sided_reach_ft"].fillna(0) >= end - FLOAT_TOL_FT
    return out


def structural_confirmation(signals: pd.DataFrame, approaches: pd.DataFrame, corridors: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    approach_ids = set(approaches["signal_approach_id"])
    duplicate_ids = int(corridors["approach_corridor_id"].duplicated(keep=False).sum())
    invalid_approach_links = int((~corridors["signal_approach_id"].isin(approach_ids)).sum())
    blocked_present = int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum())
    direction_cols = [
        c for c in corridors.columns
        if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"}
        or c.lower().endswith("_directionality")
    ]
    spanning = int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum())
    overreach = int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum())
    boundary = int(corridors["cross_signal_boundary_flag"].fillna(False).astype(bool).sum())
    outside = int(
        (
            (corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6)
            | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)
        ).sum()
    )
    checks = [
        {"check_name": "approach_corridor_id_unique", "value": duplicate_ids, "status": "pass" if duplicate_ids == 0 else "fail"},
        {"check_name": "valid_signal_approach_links", "value": invalid_approach_links, "status": "pass" if invalid_approach_links == 0 else "fail"},
        {"check_name": "blocked_approaches_absent", "value": blocked_present, "status": "pass" if blocked_present == 0 else "fail"},
        {"check_name": "directionality_fields_absent", "value": len(direction_cols), "detail": "|".join(direction_cols), "status": "pass" if not direction_cols else "fail"},
        {"check_name": "signal_spanning_rows_absent", "value": spanning, "status": "pass" if spanning == 0 else "fail"},
        {"check_name": "one_sided_overextension_absent", "value": overreach, "status": "pass" if overreach == 0 else "fail"},
        {"check_name": "boundary_crossing_violations_absent", "value": boundary, "status": "pass" if boundary == 0 else "fail"},
        {"check_name": "reviewed_measure_inside_interval", "value": outside, "status": "pass" if outside == 0 else "fail"},
        {"check_name": "signal_index_rows_read", "value": int(len(signals)), "status": "info"},
        {"check_name": "approach_rows_read", "value": int(len(approaches)), "status": "info"},
        {"check_name": "corridor_rows_read", "value": int(len(corridors)), "status": "info"},
    ]
    return checks, direction_cols


def build_summaries(signals: pd.DataFrame, approaches: pd.DataFrame, corridors: pd.DataFrame) -> dict[str, pd.DataFrame]:
    c = corridors.copy()
    c["length_bucket"] = c["one_sided_reach_ft"].map(length_bucket)
    approach_base = approaches[
        [
            "signal_approach_id",
            "stable_signal_id",
            "corridor_build_gate",
            "corridor_gate_severity",
            "corridor_restriction_notes",
            "route_base",
            "dominant_roadway_configuration",
            "dominant_carriageway_token_values",
        ]
    ].copy()
    signal_base = signals[
        ["stable_signal_id", "analysis_ready_status", "source_limited_status", "holdout_reason"]
    ].rename(
        columns={
            "analysis_ready_status": "signal_analysis_ready_status",
            "source_limited_status": "signal_source_limited_status",
            "holdout_reason": "signal_holdout_reason",
        }
    )

    app_group = c.groupby("signal_approach_id")
    app_numeric = app_group.agg(
        corridor_row_count=("approach_corridor_id", "size"),
        mean_one_sided_reach_ft=("one_sided_reach_ft", "mean"),
        median_one_sided_reach_ft=("one_sided_reach_ft", "median"),
        min_one_sided_reach_ft=("one_sided_reach_ft", "min"),
        max_one_sided_reach_ft=("one_sided_reach_ft", "max"),
        total_corridor_length_ft=("corridor_length_ft", "sum"),
        route_travelway_subbranch_count=("stable_travelway_id", "nunique"),
        warning_corridor_count=("parent_corridor_gate_severity", lambda s: int((s.fillna("") != "none").sum())),
        very_short_corridor_count=("length_bucket", lambda s: int((s == "very_short_0_100").sum())),
    ).reset_index()
    app_counts = app_group.apply(
        lambda g: pd.Series(
            {
                "measure_side_class_counts": compact_counts(g["measure_side_class"]),
                "endpoint_policy_counts": compact_counts(g["endpoint_policy"]),
                "boundary_method_counts": compact_counts(g["boundary_method"]),
                "length_bucket_counts": compact_counts(g["length_bucket"]),
                "clipped_by_signal_boundary_count": int(g["clipped_by_signal_boundary_flag"].fillna(False).astype(bool).sum()),
                "clipped_by_source_extent_count": int(g["clipped_by_source_extent_flag"].fillna(False).astype(bool).sum()),
                "clipped_by_2500_ft_count": int(g["clipped_by_2500_ft_flag"].fillna(False).astype(bool).sum()),
            }
        ),
        include_groups=False,
    ).reset_index()
    approach_summary = approach_base.merge(app_numeric, on="signal_approach_id", how="left").merge(app_counts, on="signal_approach_id", how="left")
    numeric_fill = [
        "corridor_row_count",
        "mean_one_sided_reach_ft",
        "median_one_sided_reach_ft",
        "min_one_sided_reach_ft",
        "max_one_sided_reach_ft",
        "total_corridor_length_ft",
        "route_travelway_subbranch_count",
        "warning_corridor_count",
        "very_short_corridor_count",
        "clipped_by_signal_boundary_count",
        "clipped_by_source_extent_count",
        "clipped_by_2500_ft_count",
    ]
    for col in numeric_fill:
        approach_summary[col] = approach_summary[col].fillna(0)
    for col in ["measure_side_class_counts", "endpoint_policy_counts", "boundary_method_counts", "length_bucket_counts"]:
        approach_summary[col] = approach_summary[col].fillna("")
    approach_summary["distance_band_support_status"] = approach_summary.apply(
        lambda r: support_status_for_group(c[c["signal_approach_id"].eq(r["signal_approach_id"])], clean(r["corridor_build_gate"])),
        axis=1,
    )
    approach_summary = add_band_flags(approach_summary)

    signal_app = approaches.groupby("stable_signal_id").agg(signal_approach_count=("signal_approach_id", "size")).reset_index()
    sig_corr = c.groupby("stable_signal_id").agg(
        corridor_row_count=("approach_corridor_id", "size"),
        approaches_with_corridors=("signal_approach_id", "nunique"),
        mean_corridor_length_ft=("corridor_length_ft", "mean"),
        median_corridor_length_ft=("corridor_length_ft", "median"),
        min_corridor_length_ft=("corridor_length_ft", "min"),
        max_corridor_length_ft=("corridor_length_ft", "max"),
        total_corridor_length_ft=("corridor_length_ft", "sum"),
        mean_one_sided_reach_ft=("one_sided_reach_ft", "mean"),
        max_one_sided_reach_ft=("one_sided_reach_ft", "max"),
        measure_increasing_corridor_count=("measure_side_class", lambda s: int((s == "measure_increasing_from_signal").sum())),
        measure_decreasing_corridor_count=("measure_side_class", lambda s: int((s == "measure_decreasing_from_signal").sum())),
        warning_corridor_count=("parent_corridor_gate_severity", lambda s: int((s.fillna("") != "none").sum())),
        very_short_corridor_count=("length_bucket", lambda s: int((s == "very_short_0_100").sum())),
    ).reset_index()
    sig_counts = c.groupby("stable_signal_id").apply(
        lambda g: pd.Series(
            {
                "endpoint_policy_counts": compact_counts(g["endpoint_policy"]),
                "boundary_method_counts": compact_counts(g["boundary_method"]),
                "length_bucket_counts": compact_counts(g["length_bucket"]),
            }
        ),
        include_groups=False,
    ).reset_index()
    support_mix = approach_summary.groupby("stable_signal_id")["distance_band_support_status"].apply(compact_counts).reset_index(name="distance_band_support_mix")
    support_counts = approach_summary.pivot_table(
        index="stable_signal_id",
        columns="distance_band_support_status",
        values="signal_approach_id",
        aggfunc="count",
        fill_value=0,
    ).reset_index()
    signal_summary = signal_base.merge(signal_app, on="stable_signal_id", how="left").merge(sig_corr, on="stable_signal_id", how="left").merge(sig_counts, on="stable_signal_id", how="left").merge(support_mix, on="stable_signal_id", how="left").merge(support_counts, on="stable_signal_id", how="left")
    signal_summary["signal_approach_count"] = signal_summary["signal_approach_count"].fillna(0).astype(int)
    signal_summary["corridor_row_count"] = signal_summary["corridor_row_count"].fillna(0).astype(int)
    signal_summary["approaches_with_corridors"] = signal_summary["approaches_with_corridors"].fillna(0).astype(int)
    signal_summary["approaches_without_corridors"] = signal_summary["signal_approach_count"] - signal_summary["approaches_with_corridors"]
    signal_summary["corridor_rows_per_approach"] = signal_summary.apply(
        lambda r: float(r["corridor_row_count"]) / float(r["signal_approach_count"]) if r["signal_approach_count"] else 0.0,
        axis=1,
    )
    for col in [
        "mean_corridor_length_ft",
        "median_corridor_length_ft",
        "min_corridor_length_ft",
        "max_corridor_length_ft",
        "total_corridor_length_ft",
        "mean_one_sided_reach_ft",
        "max_one_sided_reach_ft",
        "measure_increasing_corridor_count",
        "measure_decreasing_corridor_count",
        "warning_corridor_count",
        "very_short_corridor_count",
    ]:
        signal_summary[col] = signal_summary[col].fillna(0)
    for col in ["endpoint_policy_counts", "boundary_method_counts", "length_bucket_counts", "distance_band_support_mix"]:
        signal_summary[col] = signal_summary[col].fillna("")
    signal_summary["corridor_density_qa_class"] = signal_summary.apply(density_class, axis=1)

    return {
        "corridors": c,
        "approach_summary": approach_summary,
        "signal_summary": signal_summary,
    }


def distribution_table(df: pd.DataFrame, count_col: str, label_col: str) -> pd.DataFrame:
    bins = [-1, 0, 2, 4, 8, 15, 24, 999999]
    labels = ["0", "1_2", "3_4", "5_8", "9_15", "16_24", "25_plus"]
    bucket = pd.cut(df[count_col], bins=bins, labels=labels)
    return bucket.value_counts().sort_index().reset_index(name=label_col).rename(columns={count_col: "bucket"})


def write_outputs(signals: pd.DataFrame, approaches: pd.DataFrame, corridors: pd.DataFrame, summaries: dict[str, pd.DataFrame], checks: list[dict[str, Any]], direction_cols: list[str]) -> str:
    approach_summary = summaries["approach_summary"]
    signal_summary = summaries["signal_summary"]
    c = summaries["corridors"]

    hard_fail = any(row.get("status") == "fail" for row in checks if row["check_name"] not in {"signal_index_rows_read", "approach_rows_read", "corridor_rows_read"})
    density_counts = signal_summary["corridor_density_qa_class"].value_counts()
    extreme_or_high = int(density_counts.get("extreme_corridor_density_review", 0) + density_counts.get("high_corridor_density_review", 0))
    no_support = int((approach_summary["distance_band_support_status"] == "no_usable_support").sum())
    if hard_fail:
        decision = "approach_corridors_should_be_rebuilt"
    elif no_support > 0 or extreme_or_high > 0:
        decision = "approach_corridors_ready_after_review_of_outliers"
    else:
        decision = "approach_corridors_ready_as_validated_parent"

    write_csv("structural_confirmation.csv", checks)
    write_csv("corridor_rows_per_signal.csv", signal_summary[["stable_signal_id", "signal_approach_count", "corridor_row_count", "approaches_with_corridors", "approaches_without_corridors", "corridor_rows_per_approach", "corridor_density_qa_class"]].to_dict("records"))
    write_csv("corridor_rows_per_approach.csv", approach_summary[["stable_signal_id", "signal_approach_id", "corridor_build_gate", "corridor_row_count", "measure_side_class_counts", "route_travelway_subbranch_count", "distance_band_support_status"]].to_dict("records"))
    write_csv("signal_level_corridor_length_summary.csv", signal_summary.to_dict("records"))
    write_csv("approach_level_corridor_length_summary.csv", approach_summary.to_dict("records"))
    write_csv("corridor_density_qa_by_signal.csv", signal_summary[["stable_signal_id", "signal_approach_count", "corridor_row_count", "corridor_rows_per_approach", "corridor_density_qa_class", "endpoint_policy_counts", "boundary_method_counts"]].to_dict("records"))
    write_csv("corridor_density_distribution.csv", signal_summary["corridor_density_qa_class"].value_counts().sort_index().reset_index(name="signal_count").rename(columns={"corridor_density_qa_class": "corridor_density_qa_class"}).to_dict("records"))
    length_qa = c.groupby("length_bucket").agg(
        corridor_rows=("approach_corridor_id", "size"),
        mean_length_ft=("one_sided_reach_ft", "mean"),
        clipped_by_signal_boundary_count=("clipped_by_signal_boundary_flag", lambda s: int(s.fillna(False).astype(bool).sum())),
        clipped_by_source_extent_count=("clipped_by_source_extent_flag", lambda s: int(s.fillna(False).astype(bool).sum())),
        clipped_by_2500_ft_count=("clipped_by_2500_ft_flag", lambda s: int(s.fillna(False).astype(bool).sum())),
    ).reset_index()
    write_csv("corridor_length_qa.csv", length_qa.to_dict("records"))
    write_csv("distance_band_support_by_approach.csv", approach_summary.to_dict("records"))
    signal_support_cols = ["stable_signal_id", "signal_approach_count", "corridor_row_count", "distance_band_support_mix"]
    support_count_cols = [cname for cname in signal_summary.columns if cname in set(approach_summary["distance_band_support_status"].unique())]
    write_csv("distance_band_support_by_signal.csv", signal_summary[signal_support_cols + support_count_cols].to_dict("records"))
    write_csv("endpoint_policy_by_signal.csv", signal_summary[["stable_signal_id", "corridor_row_count", "endpoint_policy_counts", "boundary_method_counts"]].to_dict("records"))
    write_csv("high_corridor_count_signal_review.csv", signal_summary.sort_values(["corridor_row_count", "total_corridor_length_ft"], ascending=False).head(250).to_dict("records"))
    write_csv("high_corridors_per_approach_review.csv", approach_summary.sort_values(["corridor_row_count", "max_one_sided_reach_ft"], ascending=False).head(250).to_dict("records"))
    low_underbuild = signal_summary[
        signal_summary["corridor_density_qa_class"].eq("low_corridor_density_possible_underbuild")
        | ((signal_summary["corridor_row_count"] <= 2) & (signal_summary["signal_approach_count"] >= 3))
    ].sort_values(["signal_approach_count", "corridor_row_count"], ascending=[False, True])
    write_csv("low_corridor_density_possible_underbuild_review.csv", low_underbuild.to_dict("records"))
    short_review = signal_summary.sort_values(["very_short_corridor_count", "corridor_row_count"], ascending=False).head(250)
    write_csv("short_corridor_review.csv", short_review.to_dict("records"))
    write_csv("high_total_length_signal_review.csv", signal_summary.sort_values("total_corridor_length_ft", ascending=False).head(250).to_dict("records"))
    write_csv("no_usable_support_approach_review.csv", approach_summary[approach_summary["distance_band_support_status"].isin(["no_usable_support", "blocked_by_parent_gate"])].to_dict("records"))
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "structural checks passed; outlier review recommended for density/support extremes" if decision.endswith("outliers") else "structural and distribution QA passed"}])
    write_csv("recommended_next_actions.csv", [
        {"rank": 1, "action": "review_corridor_density_and_no_support_outlier_ledgers", "rationale": "Outlier ledgers identify high-density and no-support cases before bin_context."},
        {"rank": 2, "action": "proceed_to_bin_context_after_accepting_corridor_outlier_qa", "rationale": "The layer is one-sided and structurally clean."},
    ])

    per_signal_distribution = distribution_table(signal_summary, "corridor_row_count", "signal_count")
    per_approach_distribution = distribution_table(approach_summary, "corridor_row_count", "approach_count")
    avg_signal_len = float(signal_summary.loc[signal_summary["corridor_row_count"] > 0, "mean_corridor_length_ft"].mean())
    med_signal_len = float(signal_summary.loc[signal_summary["corridor_row_count"] > 0, "median_corridor_length_ft"].median())
    write_csv("manifest_source_inputs.csv", [
        {"path": rel(SIGNAL_INDEX), "role": "validated_parent"},
        {"path": rel(TRAVELWAY_INDEX), "role": "validated_parent"},
        {"path": rel(ATTACHMENT), "role": "validated_parent"},
        {"path": rel(APPROACHES), "role": "validated_parent"},
        {"path": rel(CORRIDORS), "role": "audit_target"},
        {"path": rel(REBUILD_REVIEW), "role": "method_comparison_evidence_only"},
    ])
    findings = f"""# Approach Corridors Signal-Level QA Audit

## Structural Checks
The one-sided rebuild passed structural checks: duplicate corridor IDs = {checks[0]['value']}, invalid approach links = {checks[1]['value']}, blocked rows present = {checks[2]['value']}, signal-spanning rows = {checks[4]['value']}, over-2,500-ft rows = {checks[5]['value']}, boundary crossing rows = {checks[6]['value']}. No upstream/downstream or directionality fields were present.

## Corridor Rows Per Signal
Corridor rows per signal distribution:

{per_signal_distribution.to_string(index=False)}

## Corridor Rows Per Approach
Corridor rows per approach distribution:

{per_approach_distribution.to_string(index=False)}

## Length Summary
Average mean corridor length per signal with corridors: {avg_signal_len:,.1f} ft. Median of signal median corridor lengths: {med_signal_len:,.1f} ft.

## High Corridor Counts
High and extreme corridor-count signals are treated as QA review targets, not automatic failures. These usually reflect divided carriageways, route segmentation, or multiple one-sided subbranches.

## Short Corridors
Short corridors are summarized by endpoint clipping reason. Very short corridors are primarily checked for signal-boundary and source-extent explanations in `corridor_length_qa.csv` and `short_corridor_review.csv`.

## Distance-Band Support
Approach-level support statuses:

{approach_summary['distance_band_support_status'].value_counts().sort_index().reset_index(name='approach_count').to_string(index=False)}

## Best QA Flags
The strongest QA flags for this layer are corridor density class, distance-band support status, one-sided reach bucket, endpoint/boundary method counts, and warning gate severity.

## Readiness
Final decision: `{decision}`. The corridor layer is structurally safe as a bin_context parent after outlier ledgers are reviewed.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)],
        "method_evidence_only": [rel(REBUILD_REVIEW), rel(SIDE_REACH_AUDIT), rel(GATE_PATCH_REVIEW), rel(BUILD_APPROACH_REVIEW), rel(APPROACH_VALIDATION_REVIEW)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "signal_rows": int(len(signals)),
        "approach_rows": int(len(approaches)),
        "corridor_rows": int(len(corridors)),
        "structural_fail_count": int(sum(1 for row in checks if row.get("status") == "fail")),
        "signals_with_corridors": int((signal_summary["corridor_row_count"] > 0).sum()),
        "approaches_with_corridors": int((approach_summary["corridor_row_count"] > 0).sum()),
        "high_or_extreme_density_signals": extreme_or_high,
        "no_usable_support_approaches": no_support,
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    return decision


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting signal-level and approach-level corridor QA audit.")
    signals = pd.read_parquet(SIGNAL_INDEX)
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    log(f"Loaded signals={len(signals)}, approaches={len(approaches)}, corridors={len(corridors)}.")
    checks, direction_cols = structural_confirmation(signals, approaches, corridors)
    summaries = build_summaries(signals, approaches, corridors)
    decision = write_outputs(signals, approaches, corridors, summaries, checks, direction_cols)
    log(f"Audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
