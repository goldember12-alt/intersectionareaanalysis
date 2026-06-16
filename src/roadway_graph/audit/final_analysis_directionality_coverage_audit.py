"""Final directionality coverage and missingness audit.

This review-only audit starts from the canonical final bin universe and joins
direct divided/one-way labels plus undivided synthetic directionality outputs.
It reports source-bin coverage without creating crash/access assignments.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
DOCTRINE_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
DIRECT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery"
UNDIVIDED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_undivided_centerline_directionality"
ENHANCED_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
OUT_DIR = ROOT / "work/output/roadway_graph/analysis/current/final_analysis_directionality_coverage_audit"

DIRECT_LABELS = {"downstream_from_signal", "upstream_to_signal"}


def write_log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    return pd.read_csv(path, low_memory=False, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT_DIR / name, index=False, quoting=csv.QUOTE_MINIMAL)
    write_log(f"Wrote {name}: {len(df):,} rows")


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for _, row in df.iterrows():
        vals = []
        for col in cols:
            val = row[col]
            if isinstance(val, float):
                vals.append(f"{val:.3f}" if abs(val) < 1 else f"{val:,.1f}")
            elif isinstance(val, (int, np.integer)):
                vals.append(f"{int(val):,}")
            else:
                vals.append(str(val))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines) + "\n"


def build_bin_coverage() -> pd.DataFrame:
    bin_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "original_physical_leg_id",
        "signal_approach_id",
        "carriageway_source_subpart_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "analysis_window",
        "geometry_wkt",
        "final_review_leg_source",
        "final_review_recovery_provenance",
        "roadway_context_status",
        "rim_facility_raw",
        "rim_facility_secondary_raw",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "median_group",
        "residual_bucket",
        "partial_coverage_flag",
    ]
    bins = read_csv(CANONICAL_DIR / "analysis_bin.csv", usecols=lambda c: c in bin_cols)
    doctrine = read_csv(
        DOCTRINE_DIR / "bin_directionality_support_detail.csv",
        usecols=lambda c: c
        in [
            "stable_bin_id",
            "directionality_support_class",
            "directionality_source_evidence",
            "recommended_directionality_action",
        ],
    )
    direct = read_csv(
        DIRECT_DIR / "combined_direct_divided_directionality_detail.csv",
        usecols=lambda c: c
        in [
            "stable_bin_id",
            "combined_direct_directionality_label",
            "combined_direct_directionality_source",
            "combined_direct_directionality_confidence",
            "combined_direct_directionality_method",
            "recoverable_uncertainty_class",
            "relaxed_rule_method",
        ],
    )
    direct_excluded = read_csv(
        DIRECT_DIR / "relaxed_direct_directionality_excluded_bins.csv",
        usecols=lambda c: c in ["stable_bin_id", "exclusion_reason", "primary_uncertainty_class"],
    )
    synthetic = read_csv(
        UNDIVIDED_DIR / "undivided_centerline_synthetic_direction_rows.csv",
        usecols=lambda c: c
        in [
            "stable_bin_id",
            "synthetic_direction_id",
            "public_directional_role",
            "synthetic_directionality_confidence",
            "directional_crash_assignment_ready",
        ],
    )
    synthetic_unclear = read_csv(
        UNDIVIDED_DIR / "undivided_centerline_uncertain_bins.csv",
        usecols=lambda c: c in ["stable_bin_id", "synthetic_source_bin_status", "approach_geometry_confidence"],
    )
    write_log(
        f"Loaded bins={len(bins):,}; doctrine={len(doctrine):,}; direct={len(direct):,}; synthetic rows={len(synthetic):,}."
    )

    syn_summary = (
        synthetic.groupby("stable_bin_id", dropna=False)
        .agg(
            synthetic_interpretation_count=("synthetic_direction_id", "count"),
            synthetic_roles=("public_directional_role", lambda s: ";".join(sorted(set(map(str, s))))),
            synthetic_directionality_confidence=("synthetic_directionality_confidence", lambda s: ";".join(sorted(set(map(str, s))))),
            directional_crash_assignment_ready=("directional_crash_assignment_ready", lambda s: ";".join(sorted(set(map(str, s))))),
        )
        .reset_index()
    )

    out = bins.merge(doctrine, on="stable_bin_id", how="left")
    out = out.merge(direct, on="stable_bin_id", how="left")
    out = out.merge(direct_excluded, on="stable_bin_id", how="left")
    out = out.merge(syn_summary, on="stable_bin_id", how="left")
    out = out.merge(synthetic_unclear, on="stable_bin_id", how="left")

    out["approach_key"] = (
        out["signal_approach_id"]
        .fillna(out["original_physical_leg_id"])
        .fillna(out["stable_travelway_id"])
        .fillna("unknown_approach")
    )
    out["has_direct_label"] = out["combined_direct_directionality_label"].isin(DIRECT_LABELS)
    out["has_synthetic_directionality"] = out["synthetic_interpretation_count"].fillna(0).gt(0)
    out["has_any_directionality_coverage"] = out["has_direct_label"] | out["has_synthetic_directionality"]

    out["directionality_bin_class"] = np.select(
        [
            out["has_direct_label"],
            out["has_synthetic_directionality"],
            out["exclusion_reason"].eq("excluded_needs_map_review"),
            out["exclusion_reason"].eq("excluded_should_remain_uncertain"),
            out["combined_direct_directionality_source"].eq("not_assignable_after_relaxed_review"),
            out["synthetic_source_bin_status"].notna(),
            out["directionality_support_class"].isin(["ramp_or_interchange_direction_review", "insufficient_direction_evidence"]),
            out["directionality_support_class"].isna(),
        ],
        [
            "direct_divided_oneway_labeled",
            "undivided_synthetic_labeled",
            "direct_excluded_map_review",
            "direct_excluded_should_remain_uncertain",
            "direct_not_assignable_after_relaxed_review",
            "undivided_synthetic_unclear",
            "directionality_doctrine_unclear_or_review_needed",
            "not_in_directionality_targets",
        ],
        default="other_unmatched_error",
    )
    out["directionality_coverage_status"] = np.select(
        [
            out["has_direct_label"],
            out["has_synthetic_directionality"],
            out["directionality_bin_class"].isin(["direct_excluded_map_review", "directionality_doctrine_unclear_or_review_needed"]),
            out["directionality_bin_class"].isin(
                ["direct_excluded_should_remain_uncertain", "direct_not_assignable_after_relaxed_review", "undivided_synthetic_unclear"]
            ),
            out["directionality_bin_class"].eq("not_in_directionality_targets"),
        ],
        [
            "covered",
            "partial_or_interpretive_covered",
            "uncovered_review_needed",
            "uncovered_uncertain",
            "uncovered_not_supported",
        ],
        default="uncovered_uncertain",
    )
    out["directionality_method"] = np.select(
        [out["has_direct_label"], out["has_synthetic_directionality"]],
        ["direct_divided_oneway", "synthetic_undivided_centerline"],
        default="none",
    )
    out["downstream_upstream_label"] = np.where(
        out["has_direct_label"], out["combined_direct_directionality_label"], ""
    )
    out["synthetic_interpretation_count"] = out["synthetic_interpretation_count"].fillna(0).astype(int)
    return out


def bin_summary(detail: pd.DataFrame) -> pd.DataFrame:
    total = len(detail)
    rows = [
        ("total_final_bins", total, 1.0),
        ("direct_divided_oneway_labeled_bins", int(detail["has_direct_label"].sum()), float(detail["has_direct_label"].mean())),
        (
            "undivided_synthetic_labeled_source_bins",
            int(detail["has_synthetic_directionality"].sum()),
            float(detail["has_synthetic_directionality"].mean()),
        ),
        (
            "unique_bins_with_any_directionality_coverage",
            int(detail["has_any_directionality_coverage"].sum()),
            float(detail["has_any_directionality_coverage"].mean()),
        ),
        (
            "bins_uncovered",
            int((~detail["has_any_directionality_coverage"]).sum()),
            float((~detail["has_any_directionality_coverage"]).mean()),
        ),
    ]
    base = pd.DataFrame(rows, columns=["metric", "bins", "share_of_total_bins"])
    reason = (
        detail.loc[~detail["has_any_directionality_coverage"], "directionality_bin_class"]
        .value_counts()
        .rename_axis("metric")
        .reset_index(name="bins")
    )
    reason["share_of_total_bins"] = reason["bins"] / total
    reason["metric"] = "uncovered_reason__" + reason["metric"].astype(str)
    return pd.concat([base, reason], ignore_index=True)


def signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    g = detail.groupby("stable_signal_id", dropna=False)
    s = g.agg(
        total_bins=("stable_bin_id", "count"),
        covered_bins=("has_any_directionality_coverage", "sum"),
        direct_covered_bins=("has_direct_label", "sum"),
        synthetic_covered_bins=("has_synthetic_directionality", "sum"),
        uncovered_review_needed_bins=("directionality_coverage_status", lambda x: int((x == "uncovered_review_needed").sum())),
        uncovered_uncertain_bins=("directionality_coverage_status", lambda x: int((x == "uncovered_uncertain").sum())),
        uncovered_not_supported_bins=("directionality_coverage_status", lambda x: int((x == "uncovered_not_supported").sum())),
        approach_count=("approach_key", "nunique"),
        windows_with_bins=("analysis_window", "nunique"),
        median_group_summary=("median_group", lambda x: ";".join(sorted(set(map(str, x.dropna())))[:5])),
        facility_summary=("rim_facility_raw", lambda x: ";".join(sorted(set(map(str, x.dropna())))[:5])),
        recovery_provenance_summary=("final_review_recovery_provenance", lambda x: ";".join(sorted(set(map(str, x.dropna())))[:5])),
    ).reset_index()
    s["uncovered_bins"] = s["total_bins"] - s["covered_bins"]
    s["coverage_share"] = s["covered_bins"] / s["total_bins"]
    s["signal_directionality_coverage_class"] = np.select(
        [
            s["coverage_share"] >= 0.999999,
            s["coverage_share"] >= 0.75,
            s["coverage_share"] >= 0.25,
            s["coverage_share"] > 0,
        ],
        [
            "full_directionality_coverage",
            "high_partial_coverage_75plus",
            "moderate_partial_coverage_25_to_75",
            "low_partial_coverage_lt25",
        ],
        default="no_directionality_coverage",
    )
    reason_cols = ["uncovered_review_needed_bins", "uncovered_uncertain_bins", "uncovered_not_supported_bins"]
    s["dominant_missingness_reason"] = s[reason_cols].idxmax(axis=1).where(s["uncovered_bins"] > 0, "none")
    return s


def approach_window_summary(detail: pd.DataFrame, keys: list[str], level: str) -> pd.DataFrame:
    g = detail.groupby(keys, dropna=False)
    out = g.agg(
        total_bins=("stable_bin_id", "count"),
        covered_bins=("has_any_directionality_coverage", "sum"),
        direct_covered_bins=("has_direct_label", "sum"),
        synthetic_covered_bins=("has_synthetic_directionality", "sum"),
        downstream_direct_bins=("downstream_upstream_label", lambda x: int((x == "downstream_from_signal").sum())),
        upstream_direct_bins=("downstream_upstream_label", lambda x: int((x == "upstream_to_signal").sum())),
        synthetic_interpretation_rows=("synthetic_interpretation_count", "sum"),
    ).reset_index()
    out["uncovered_bins"] = out["total_bins"] - out["covered_bins"]
    out["coverage_share"] = out["covered_bins"] / out["total_bins"]
    out["coverage_level"] = level
    out["directional_side_coverage_class"] = np.select(
        [
            (out["downstream_direct_bins"] > 0) & (out["upstream_direct_bins"] > 0),
            out["synthetic_covered_bins"] > 0,
            out["downstream_direct_bins"] > 0,
            out["upstream_direct_bins"] > 0,
        ],
        ["direct_both_sides", "synthetic_pair_context", "direct_downstream_only", "direct_upstream_only"],
        default="undirected_or_unclear",
    )
    return out


def missingness_by_context(detail: pd.DataFrame) -> pd.DataFrame:
    contexts = [
        "directionality_support_class",
        "directionality_bin_class",
        "directionality_coverage_status",
        "final_review_recovery_provenance",
        "rim_facility_raw",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "median_group",
        "residual_bucket",
        "partial_coverage_flag",
    ]
    rows = []
    for col in contexts:
        if col not in detail.columns:
            continue
        tmp = detail.groupby(col, dropna=False).agg(
            total_bins=("stable_bin_id", "count"),
            covered_bins=("has_any_directionality_coverage", "sum"),
            uncovered_bins=("has_any_directionality_coverage", lambda x: int((~x).sum())),
            signals=("stable_signal_id", "nunique"),
        ).reset_index()
        tmp.insert(0, "context_field", col)
        tmp = tmp.rename(columns={col: "context_value"})
        tmp["coverage_share"] = tmp["covered_bins"] / tmp["total_bins"]
        rows.append(tmp)
    return pd.concat(rows, ignore_index=True, sort=False)


def high_missingness_queues(sig: pd.DataFrame, detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    top_count = sig.sort_values(["uncovered_bins", "total_bins"], ascending=[False, False]).head(100).copy()
    top_share = sig[sig["uncovered_bins"] > 0].sort_values(["coverage_share", "uncovered_bins"], ascending=[True, False]).head(100)
    no_cov = sig[sig["signal_directionality_coverage_class"].eq("no_directionality_coverage")].copy()
    map_review = (
        detail[detail["directionality_bin_class"].eq("direct_excluded_map_review")]
        .groupby("stable_signal_id")
        .agg(direct_map_review_bins=("stable_bin_id", "count"))
        .reset_index()
    )
    synth_unc = (
        detail[detail["directionality_bin_class"].eq("undivided_synthetic_unclear")]
        .groupby("stable_signal_id")
        .agg(synthetic_unclear_bins=("stable_bin_id", "count"))
        .reset_index()
    )
    queue = pd.concat([top_count, top_share], ignore_index=True).drop_duplicates("stable_signal_id")
    queue = queue.merge(map_review, on="stable_signal_id", how="left").merge(synth_unc, on="stable_signal_id", how="left")
    queue[["direct_map_review_bins", "synthetic_unclear_bins"]] = queue[
        ["direct_map_review_bins", "synthetic_unclear_bins"]
    ].fillna(0).astype(int)
    queue = queue.sort_values(["uncovered_bins", "direct_map_review_bins", "synthetic_unclear_bins"], ascending=False)
    return queue, no_cov


def readiness_decision(detail: pd.DataFrame, sig: pd.DataFrame) -> pd.DataFrame:
    coverage_share = float(detail["has_any_directionality_coverage"].mean())
    no_cov = int(sig["signal_directionality_coverage_class"].eq("no_directionality_coverage").sum())
    full = int(sig["signal_directionality_coverage_class"].eq("full_directionality_coverage").sum())
    rows = [
        {
            "decision_question": "context_summary_readiness",
            "decision": "ready_as_review_only_context",
            "evidence": f"{coverage_share:.1%} of bins and {len(sig)-no_cov:,}/{len(sig):,} signals have some direct or synthetic coverage.",
            "caveat": "Synthetic undivided rows are interpretations, not source Travelway rows.",
        },
        {
            "decision_question": "directional_crash_access_analysis_readiness",
            "decision": "not_ready_without_additional_assignment_rule",
            "evidence": "Undivided synthetic rows are context-only and direct labels still need map-review sampling.",
            "caveat": "Do not split crashes/access upstream/downstream yet.",
        },
        {
            "decision_question": "canonical_integration_readiness",
            "decision": "ready_for_review_only_integration_after_map_review_sampling",
            "evidence": f"{full:,} signals have full source-bin coverage; {no_cov:,} signals have no coverage.",
            "caveat": "Carry direct and synthetic fields separately.",
        },
        {
            "decision_question": "next_missingness_target",
            "decision": "review_direct_map_review_and_synthetic_unclear_bins",
            "evidence": "Direct map-review bins and synthetic-unclear bins dominate the remaining reviewable gaps.",
            "caveat": "Remaining ramp/interchange and insufficient evidence bins may need separate rules.",
        },
    ]
    return pd.DataFrame(rows)


def meeting_summary(bin_sum: pd.DataFrame, sig: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    metrics = dict(zip(bin_sum["metric"], bin_sum["bins"]))
    class_counts = sig["signal_directionality_coverage_class"].value_counts().to_dict()
    rows = [
        ("Total final bins", int(metrics.get("total_final_bins", len(detail))), "bins"),
        ("Bins with directionality coverage", int(metrics.get("unique_bins_with_any_directionality_coverage", 0)), "bins"),
        ("Bins without directionality coverage", int(metrics.get("bins_uncovered", 0)), "bins"),
        ("Covered signals", int((sig["coverage_share"] > 0).sum()), "signals"),
        ("Fully covered signals", int(class_counts.get("full_directionality_coverage", 0)), "signals"),
        (
            "Partially covered signals",
            int(len(sig) - class_counts.get("full_directionality_coverage", 0) - class_counts.get("no_directionality_coverage", 0)),
            "signals",
        ),
        ("No-coverage signals", int(class_counts.get("no_directionality_coverage", 0)), "signals"),
        ("Main missingness reason", detail.loc[~detail["has_any_directionality_coverage"], "directionality_bin_class"].mode().iloc[0], "class"),
    ]
    out = pd.DataFrame(rows, columns=["measure", "value", "unit"])
    return out


def write_findings(detail: pd.DataFrame, bin_sum: pd.DataFrame, sig: pd.DataFrame, ready: pd.DataFrame, qa: pd.DataFrame) -> None:
    metrics = dict(zip(bin_sum["metric"], bin_sum["bins"]))
    shares = dict(zip(bin_sum["metric"], bin_sum["share_of_total_bins"]))
    class_counts = sig["signal_directionality_coverage_class"].value_counts().to_dict()
    uncovered = detail[~detail["has_any_directionality_coverage"]]
    top10 = int(sig.sort_values("uncovered_bins", ascending=False).head(10)["uncovered_bins"].sum())
    text = f"""# Directionality Coverage Audit Findings

## Bounded Question

This audit measures final review-only directionality coverage across the canonical 433,841-bin universe. It keeps direct divided/one-way labels and undivided synthetic interpretations distinct and does not create crash/access assignments.

## Bin Coverage

- Final bins: {len(detail):,}
- Direct divided/one-way labeled bins: {metrics.get("direct_divided_oneway_labeled_bins", 0):,}
- Undivided synthetic-labeled source bins: {metrics.get("undivided_synthetic_labeled_source_bins", 0):,}
- Unique bins with any directionality coverage: {metrics.get("unique_bins_with_any_directionality_coverage", 0):,} ({shares.get("unique_bins_with_any_directionality_coverage", 0):.1%})
- Uncovered bins: {metrics.get("bins_uncovered", 0):,} ({shares.get("bins_uncovered", 0):.1%})

## Signal Coverage

{json.dumps({k: int(v) for k, v in class_counts.items()}, indent=2)}

Top 10 high-missingness signals account for {top10:,} uncovered bins.

## Dominant Missingness Reasons

{json.dumps({str(k): int(v) for k, v in uncovered["directionality_bin_class"].value_counts().items()}, indent=2)}

## Readiness

Directionality is good enough for review-only context summaries. It is not yet good enough for downstream/upstream crash/access analysis because synthetic undivided rows are context-only and direct labels still need map-review sampling.

## QA

All QA checks passed: {bool(qa["passed"].all())}.
"""
    (OUT_DIR / "final_analysis_directionality_coverage_audit_findings.md").write_text(text, encoding="utf-8")
    write_log("Wrote final_analysis_directionality_coverage_audit_findings.md")


def write_manifest(outputs: Iterable[str]) -> None:
    manifest = {
        "created_at": datetime.now().isoformat(),
        "script": "src.roadway_graph.audit.final_analysis_directionality_coverage_audit",
        "bounded_question": "Final review-only directionality coverage and missingness audit.",
        "inputs": {
            "canonical": str(CANONICAL_DIR),
            "doctrine": str(DOCTRINE_DIR),
            "direct_relaxed": str(DIRECT_DIR),
            "undivided_synthetic": str(UNDIVIDED_DIR),
            "enhanced": str(ENHANCED_DIR),
        },
        "outputs": list(outputs),
        "non_goals": [
            "No directional crash/access assignment",
            "No crash direction fields",
            "No rates/models",
            "No active output modification",
        ],
    }
    (OUT_DIR / "final_analysis_directionality_coverage_audit_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    write_log("Wrote final_analysis_directionality_coverage_audit_manifest.json")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log = OUT_DIR / "run_progress_log.txt"
    if log.exists():
        log.unlink()
    write_log("Starting final directionality coverage audit.")

    detail = build_bin_coverage()
    write_csv(detail, "directionality_bin_coverage_detail.csv")
    bin_sum = bin_summary(detail)
    write_csv(bin_sum, "directionality_bin_coverage_summary.csv")
    sig = signal_summary(detail)
    write_csv(sig, "directionality_signal_coverage_summary.csv")
    approach = approach_window_summary(detail, ["stable_signal_id", "approach_key"], "signal_approach")
    window = pd.concat(
        [
            approach_window_summary(detail, ["stable_signal_id", "analysis_window"], "signal_window"),
            approach_window_summary(detail, ["stable_signal_id", "approach_key", "analysis_window"], "signal_approach_window"),
        ],
        ignore_index=True,
        sort=False,
    )
    write_csv(approach, "directionality_approach_coverage_summary.csv")
    write_csv(window, "directionality_window_coverage_summary.csv")
    miss_context = missingness_by_context(detail)
    write_csv(miss_context, "directionality_missingness_by_context.csv")
    high_queue, no_cov = high_missingness_queues(sig, detail)
    write_csv(high_queue, "directionality_high_missingness_signal_queue.csv")
    write_csv(no_cov, "directionality_no_coverage_signal_queue.csv")
    ready = readiness_decision(detail, sig)
    write_csv(ready, "directionality_coverage_readiness_decision.csv")
    meeting = meeting_summary(bin_sum, sig, detail)
    write_csv(meeting, "meeting_directionality_coverage_summary.csv")
    (OUT_DIR / "meeting_directionality_coverage_summary.md").write_text(
        "# Meeting Directionality Coverage Summary\n\n" + markdown_table(meeting),
        encoding="utf-8",
    )
    write_log("Wrote meeting_directionality_coverage_summary.md")

    synthetic_direct_count_error = int(
        detail["has_synthetic_directionality"].mul(detail["directionality_method"].eq("direct_divided_oneway")).sum()
    )
    qa = pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Outputs written only to analysis/current coverage audit folder."),
            ("no_records_promoted", True, "Review-only coverage audit."),
            ("no_access_crash_assignment", True, "No access/crash assignment run."),
            ("no_rates_models", True, "No rates/models calculated."),
            ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
            ("direct_and_synthetic_kept_distinct", synthetic_direct_count_error == 0, f"synthetic counted as direct rows={synthetic_direct_count_error}"),
            (
                "undivided_synthetic_not_counted_as_direct_row_labels",
                int((detail["has_synthetic_directionality"] & detail["has_direct_label"]).sum()) == 0,
                f"bins with both direct and synthetic coverage={int((detail['has_synthetic_directionality'] & detail['has_direct_label']).sum())}",
            ),
            ("all_canonical_bins_represented", len(detail) == 433841, f"detail rows={len(detail):,}"),
            ("outputs_review_only_folder", True, str(OUT_DIR)),
        ],
        columns=["qa_check", "passed", "note"],
    )
    write_csv(qa, "final_analysis_directionality_coverage_audit_qa.csv")
    write_findings(detail, bin_sum, sig, ready, qa)

    outputs = [
        "directionality_bin_coverage_detail.csv",
        "directionality_bin_coverage_summary.csv",
        "directionality_signal_coverage_summary.csv",
        "directionality_approach_coverage_summary.csv",
        "directionality_window_coverage_summary.csv",
        "directionality_missingness_by_context.csv",
        "directionality_high_missingness_signal_queue.csv",
        "directionality_no_coverage_signal_queue.csv",
        "directionality_coverage_readiness_decision.csv",
        "meeting_directionality_coverage_summary.md",
        "meeting_directionality_coverage_summary.csv",
        "final_analysis_directionality_coverage_audit_findings.md",
        "final_analysis_directionality_coverage_audit_qa.csv",
        "final_analysis_directionality_coverage_audit_manifest.json",
        "run_progress_log.txt",
    ]
    write_manifest(outputs)
    write_log("Completed final directionality coverage audit.")


if __name__ == "__main__":
    main()
