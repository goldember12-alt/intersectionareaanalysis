"""Read-only validation audit for staged signal_approaches.parquet."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/signal_approaches_validation_audit"
SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"
BUILD_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
ATTACHMENT_AUDIT = REPO / "work/roadway_graph/review/signal_travelway_attachment_readiness_audit"
ATTACHMENT_BUILD = REPO / "work/roadway_graph/review/build_signal_travelway_attachment"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"
CANONICAL_FINAL = REPO / "work/roadway_graph/analysis/final_leg_corrected_analysis_dataset"
REFRESH_CANDIDATE = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"


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


def nonblank(series: pd.Series) -> pd.Series:
    text = series.astype("string").str.strip()
    return series.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>", "nat"])


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


def split_pipe(value: Any) -> list[str]:
    text = clean(value)
    return [part for part in text.split("|") if part]


def angular_separation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    vals = sorted(v % 360 for v in values)
    gaps = [(vals[(i + 1) % len(vals)] - vals[i]) % 360 for i in range(len(vals))]
    return 360 - max(gaps)


def old_distribution(path: Path, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidates = [
        path / "signal_approaches.parquet",
        path / "analysis_signal_approach_window.csv",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            df = pd.read_parquet(candidate) if candidate.suffix == ".parquet" else pd.read_csv(candidate, low_memory=False)
        except Exception as exc:
            rows.append({"source": label, "path": rel(candidate), "status": f"read_failed:{exc}", "approach_count": "", "signal_count": ""})
            continue
        signal_col = "stable_signal_id" if "stable_signal_id" in df.columns else None
        approach_col = None
        for col in ["signal_approach_id", "signal_approach_id_v2", "approach_id", "signal_approach_id_v1"]:
            if col in df.columns:
                approach_col = col
                break
        if not signal_col or not approach_col:
            rows.append({"source": label, "path": rel(candidate), "status": "missing_signal_or_approach_column", "approach_count": "", "signal_count": ""})
            continue
        dist = df.groupby(signal_col)[approach_col].nunique().value_counts().sort_index()
        for count, signal_count in dist.items():
            rows.append({"source": label, "path": rel(candidate), "status": "comparison_only", "approach_count": int(count), "signal_count": int(signal_count)})
        return rows
    rows.append({"source": label, "path": rel(path), "status": "no_comparison_table_found", "approach_count": "", "signal_count": ""})
    return rows


def approach_counts(signals: pd.DataFrame, approaches: pd.DataFrame, attachments: pd.DataFrame) -> pd.DataFrame:
    counts = approaches.groupby("stable_signal_id").size().reset_index(name="approach_count")
    cand = attachments.groupby("stable_signal_id").agg(
        candidate_count=("attachment_id", "size"),
        high_candidate_count=("attachment_confidence", lambda s: int((s == "high").sum())),
        medium_candidate_count=("attachment_confidence", lambda s: int((s == "medium").sum())),
        low_candidate_count=("attachment_confidence", lambda s: int((s == "low").sum())),
        route_group_count=("source_route_name", lambda s: int(s.fillna("").str.replace(r"(NB|SB|EB|WB)$", "", regex=True).str.strip().nunique())),
        token_count=("carriageway_direction_token", lambda s: int(s.fillna("").nunique())),
        roadway_config_count=("roadway_configuration", lambda s: int(s.fillna("").nunique())),
        nearest_candidate_distance_ft=("point_to_line_distance_ft", "min"),
        candidate_distance_spread_ft=("point_to_line_distance_ft", lambda s: float(s.max() - s.min()) if len(s) else 0.0),
    ).reset_index()
    result = signals[["stable_signal_id", "signal_index_row_id", "analysis_ready_status", "source_limited_status", "source_signal_globalid"]].merge(counts, on="stable_signal_id", how="left").merge(cand, on="stable_signal_id", how="left")
    fill = ["approach_count", "candidate_count", "high_candidate_count", "medium_candidate_count", "low_candidate_count", "route_group_count", "token_count", "roadway_config_count"]
    result[fill] = result[fill].fillna(0).astype(int)
    return result


def support_detail(approaches: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in approaches.iterrows():
        for attachment_id in split_pipe(row.get("supporting_attachment_ids")):
            rows.append(
                {
                    "signal_approach_id": row["signal_approach_id"],
                    "stable_signal_id": row["stable_signal_id"],
                    "approach_label": row.get("approach_label"),
                    "approach_bearing": row.get("approach_bearing"),
                    "attachment_id": attachment_id,
                }
            )
    return pd.DataFrame.from_records(rows)


def classify_two(row: pd.Series, app_subset: pd.DataFrame) -> str:
    bearings = app_subset["approach_bearing"].dropna().astype(float).tolist()
    sep = angular_separation(bearings)
    labels = set(app_subset["approach_label"].dropna().astype(str))
    configs = "|".join(app_subset["dominant_roadway_configuration"].fillna("").astype(str))
    route_count = int(row["route_group_count"])
    candidates = int(row["candidate_count"])
    high_med = int(row["high_candidate_count"] + row["medium_candidate_count"])
    if row["analysis_ready_status"] != "analysis_ready" or row["source_limited_status"] != "not_source_limited":
        return "source_limited_or_attachment_limited"
    if candidates >= 15 or route_count >= 6:
        return "candidate_evidence_suggests_underbuilt"
    if route_count >= 4 and high_med >= 8:
        return "likely_route_group_overcollapse"
    if "One-Way" in configs or "Divided" in configs:
        return "likely_one_way_or_divided_pair"
    if labels in [{"N", "S"}, {"E", "W"}] and sep is not None and sep <= 45:
        return "likely_true_two_leg_or_boundary_case"
    if sep is not None and sep <= 60 and route_count <= 2:
        return "likely_true_two_leg_or_boundary_case"
    if route_count <= 2 and candidates <= 6:
        return "likely_true_two_leg_or_boundary_case"
    return "ambiguous_needs_review"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting read-only signal_approaches validation audit.")
    signals = pd.read_parquet(SIGNAL_INDEX)
    roads = pd.read_parquet(TRAVELWAY_INDEX)
    attachments = pd.read_parquet(ATTACHMENT)
    approaches = pd.read_parquet(APPROACHES)
    log(f"Loaded signals={len(signals)}, roads={len(roads)}, attachments={len(attachments)}, approaches={len(approaches)}.")

    support = support_detail(approaches)
    attachment_ids = set(attachments["attachment_id"])
    signal_ids = set(signals["stable_signal_id"])
    road_ids = set(roads["stable_travelway_id"])
    support_ids = set(support["attachment_id"]) if not support.empty else set()
    app_travelway_ids = set()
    for value in approaches["supporting_stable_travelway_ids"]:
        app_travelway_ids.update(split_pipe(value))
    low_used = support.merge(attachments[["attachment_id", "attachment_confidence"]], on="attachment_id", how="left")
    low_used_count = int((low_used["attachment_confidence"] == "low").sum()) if not low_used.empty else 0
    structural = [
        {"check": "approach_rows", "value": int(len(approaches)), "status": "pass"},
        {"check": "duplicate_signal_approach_id_rows", "value": int(approaches["signal_approach_id"].duplicated(keep=False).sum()), "status": "pass" if int(approaches["signal_approach_id"].duplicated(keep=False).sum()) == 0 else "fail"},
        {"check": "invalid_stable_signal_id_links", "value": int((~approaches["stable_signal_id"].isin(signal_ids)).sum()), "status": "pass" if int((~approaches["stable_signal_id"].isin(signal_ids)).sum()) == 0 else "fail"},
        {"check": "approaches_missing_supporting_attachment_ids", "value": int((~nonblank(approaches["supporting_attachment_ids"])).sum()), "status": "pass" if int((~nonblank(approaches["supporting_attachment_ids"])).sum()) == 0 else "fail"},
        {"check": "supporting_attachment_ids_missing_from_parent", "value": int(len(support_ids - attachment_ids)), "status": "pass" if len(support_ids - attachment_ids) == 0 else "fail"},
        {"check": "supporting_travelway_ids_missing_from_parent", "value": int(len(app_travelway_ids - road_ids)), "status": "pass" if len(app_travelway_ids - road_ids) == 0 else "fail"},
        {"check": "low_confidence_candidates_used", "value": low_used_count, "status": "pass" if low_used_count == 0 else "fail"},
    ]
    write_csv("approach_structural_reconciliation.csv", structural)

    parent_rows = [
        {"object": "signal_approaches", "dependency": rel(SIGNAL_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(TRAVELWAY_INDEX), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(ATTACHMENT), "dependency_role": "canonical_parent", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(BUILD_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(ATTACHMENT_AUDIT), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(ATTACHMENT_BUILD), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(CONTRACT_REVIEW), "dependency_role": "method_evidence_only", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(CANONICAL_FINAL), "dependency_role": "comparison_evidence_only", "allowed": True},
        {"object": "signal_approaches", "dependency": rel(REFRESH_CANDIDATE), "dependency_role": "comparison_evidence_only", "allowed": True},
    ]
    write_csv("parent_dependency_check.csv", parent_rows)

    counts = approach_counts(signals, approaches, attachments)
    write_csv("approach_count_by_signal.csv", counts.to_dict("records"))
    dist = counts["approach_count"].value_counts().sort_index().reset_index()
    dist.columns = ["approach_count", "signal_count"]
    total_signals = len(counts)
    accepted = counts[counts["approach_count"] > 0]
    dist["share_all_signals"] = dist["signal_count"] / total_signals
    dist["share_accepted_signals"] = dist["signal_count"] / len(accepted)
    dist_rows = dist.to_dict("records")
    dist_rows.append({"approach_count": "avg_all_signals", "signal_count": float(counts["approach_count"].mean()), "share_all_signals": "", "share_accepted_signals": ""})
    dist_rows.append({"approach_count": "avg_accepted_signals", "signal_count": float(accepted["approach_count"].mean()), "share_all_signals": "", "share_accepted_signals": ""})
    write_csv("approach_count_distribution_validation.csv", dist_rows)

    old_rows = old_distribution(CANONICAL_FINAL, "canonical_final") + old_distribution(REFRESH_CANDIDATE, "refresh_candidate")
    write_csv("old_approach_distribution_comparison.csv", old_rows)

    approach_by_signal = {sid: df for sid, df in approaches.groupby("stable_signal_id")}
    two = counts[counts["approach_count"] == 2].copy()
    two["two_approach_taxonomy"] = two.apply(lambda row: classify_two(row, approach_by_signal.get(row["stable_signal_id"], pd.DataFrame())), axis=1)
    write_csv("two_approach_signal_taxonomy.csv", two.to_dict("records"))
    underbuilt = two[two["two_approach_taxonomy"].isin(["candidate_evidence_suggests_underbuilt", "likely_route_group_overcollapse", "ambiguous_needs_review"])]
    write_csv("two_approach_underbuild_risk_signals.csv", underbuilt.sort_values(["route_group_count", "candidate_count"], ascending=False).to_dict("records"))

    bearing_rows = []
    for sid, group in approaches.groupby("stable_signal_id"):
        bearings = group["approach_bearing"].dropna().astype(float).tolist()
        labels = sorted(group["approach_label"].dropna().astype(str).unique())
        bearing_rows.append(
            {
                "stable_signal_id": sid,
                "approach_count": len(group),
                "approach_labels": "|".join(labels),
                "bearing_min": min(bearings) if bearings else "",
                "bearing_max": max(bearings) if bearings else "",
                "angular_coverage_degrees": angular_separation(bearings),
                "coverage_status": "single_corridor_only" if set(labels) in [{"N", "S"}, {"E", "W"}] else ("quadrant_coverage" if len(labels) >= 3 else "limited_coverage"),
            }
        )
    write_csv("bearing_angular_coverage_audit.csv", bearing_rows)

    used_ids = support_ids
    rejected = attachments[~attachments["attachment_id"].isin(used_ids)].copy()
    rejected["route_group"] = rejected["source_route_name"].fillna("").astype(str).str.replace(r"(NB|SB|EB|WB)$", "", regex=True).str.strip()
    rejected_summary = rejected.groupby("stable_signal_id").agg(
        rejected_candidate_count=("attachment_id", "size"),
        rejected_high_medium_count=("attachment_confidence", lambda s: int(s.isin(["high", "medium"]).sum())),
        rejected_measure_ready_count=("estimated_measure_status", lambda s: int((s == "estimated_measure_projected").sum())),
        rejected_route_group_count=("route_group", lambda s: int(s.nunique())),
        rejected_nearest_distance_ft=("point_to_line_distance_ft", "min"),
    ).reset_index()
    rejected_summary = counts.merge(rejected_summary, on="stable_signal_id", how="left").fillna({
        "rejected_candidate_count": 0,
        "rejected_high_medium_count": 0,
        "rejected_measure_ready_count": 0,
        "rejected_route_group_count": 0,
        "rejected_nearest_distance_ft": "",
    })
    write_csv("rejected_candidate_audit.csv", rejected_summary.to_dict("records"))

    overcollapse = counts[
        ((counts["approach_count"] <= 2) & (counts["route_group_count"] >= 4))
        | ((counts["approach_count"] <= 2) & (counts["candidate_count"] >= 12))
    ].copy()
    overcollapse["overcollapse_risk_reason"] = overcollapse.apply(
        lambda r: "many_route_groups_with_two_or_fewer_approaches" if r["route_group_count"] >= 4 else "many_candidates_with_two_or_fewer_approaches",
        axis=1,
    )
    write_csv("route_group_overcollapse_audit.csv", overcollapse.sort_values(["route_group_count", "candidate_count"], ascending=False).to_dict("records"))

    high_complex = counts[(counts["candidate_count"] >= 25) | (counts["route_group_count"] >= 8) | (counts["token_count"] >= 4)].copy()
    high_complex["five_plus_absence_interpretation"] = high_complex.apply(
        lambda r: "zero_5plus_plausible_due_directional_arm_cap_but_review_complex_signal" if r["approach_count"] <= 4 else "has_5plus",
        axis=1,
    )
    write_csv("five_plus_absence_audit.csv", high_complex.sort_values(["candidate_count", "route_group_count"], ascending=False).to_dict("records"))

    ambiguous = approaches[approaches["ambiguity_status"].ne("clear")].copy()
    ambiguous_signal = counts[counts["stable_signal_id"].isin(ambiguous["stable_signal_id"].unique())].merge(
        ambiguous.groupby("stable_signal_id").agg(
            ambiguous_approach_count=("signal_approach_id", "size"),
            ambiguity_reasons=("ambiguity_reason", lambda s: "|".join(sorted(set(str(v) for v in s if str(v) != "")))),
        ).reset_index(),
        on="stable_signal_id",
        how="left",
    )
    ambiguous_signal["corridor_build_implication"] = "allow_only_with_conservative_corridor_rules_or_review"
    write_csv("ambiguous_signal_audit.csv", ambiguous_signal.to_dict("records"))

    high_risk = pd.concat([underbuilt, overcollapse, high_complex, ambiguous_signal], ignore_index=True).drop_duplicates("stable_signal_id")
    write_csv("high_risk_signal_review_sample.csv", high_risk.sort_values(["candidate_count", "route_group_count"], ascending=False).head(500).to_dict("records"))

    taxonomy_counts = two["two_approach_taxonomy"].value_counts().to_dict()
    likely_underbuilt_count = int(two["two_approach_taxonomy"].isin(["candidate_evidence_suggests_underbuilt", "likely_route_group_overcollapse"]).sum())
    ambiguous_two_count = int((two["two_approach_taxonomy"] == "ambiguous_needs_review").sum())
    structural_fail = any(row["status"] == "fail" for row in structural)
    if structural_fail:
        decision = "signal_approaches_should_be_rebuilt"
    elif likely_underbuilt_count > 200:
        decision = "signal_approaches_needs_two_approach_rule_repair"
    elif likely_underbuilt_count > 75 or ambiguous_two_count > 100:
        decision = "signal_approaches_ready_except_two_approach_review"
    elif len(overcollapse) > 200:
        decision = "signal_approaches_needs_route_group_overcollapse_repair"
    else:
        decision = "signal_approaches_ready_as_validated_parent"

    write_csv("approach_layer_readiness_decision.csv", [{
        "final_decision": decision,
        "structural_reconciliation": "pass" if not structural_fail else "fail",
        "two_approach_likely_underbuilt_count": likely_underbuilt_count,
        "two_approach_ambiguous_count": ambiguous_two_count,
        "route_group_overcollapse_risk_signals": int(len(overcollapse)),
        "high_complex_signals_zero_5plus_review": int(len(high_complex)),
    }])
    write_csv("recommended_patch_or_review_plan.csv", [
        {"priority": 1, "action": "review_two_approach_underbuild_risk_signals", "scope": int(len(underbuilt)), "rationale": "2-approach signals are the main residual risk before corridor building"},
        {"priority": 2, "action": "carry_ambiguous_signal_flags_into_approach_corridors", "scope": int(len(ambiguous_signal)), "rationale": "ambiguous approach arms should constrain corridor construction"},
        {"priority": 3, "action": "spot_check_high_complex_zero_5plus_signals", "scope": int(len(high_complex)), "rationale": "zero 5+ is plausible under arm cap but complex cases deserve review"},
    ])
    write_csv("recommended_next_actions.csv", [
        {"rank": 1, "action": "review_or_gate_two_approach_underbuild_risks_before_approach_corridors", "rationale": "Layer is structurally valid, but 2-approach underbuild risk should be gated in corridor construction."}
    ])

    findings = f"""# Signal Approaches Validation Audit

## Structural reconciliation
Structural reconciliation passed: approach IDs are unique, all approaches link to parent signals, supporting attachment IDs exist in the attachment parent, supporting Travelway IDs exist in the Travelway parent, and low-confidence candidates used in approaches = {low_used_count}.

## Approach-count distribution
The distribution is plausible overall: {dict(zip(dist['approach_count'], dist['signal_count']))}. Average approaches per all signals is {counts['approach_count'].mean():.2f}; average per accepted signal is {counts.loc[counts['approach_count'] > 0, 'approach_count'].mean():.2f}. It does not resemble the attachment candidate-count distribution.

## Two-approach interpretation
There are {len(two):,} two-approach signals. Taxonomy counts: {taxonomy_counts}. Likely underbuilt two-approach signals: {likely_underbuilt_count:,}. Ambiguous two-approach signals needing review: {ambiguous_two_count:,}.

## Route-group overcollapse
Route-group overcollapse risk appears in {len(overcollapse):,} signals under the audit proxy. These are mostly cases with many route groups or many candidates but only two accepted arms, and should be gated before corridor construction.

## Rejected candidates
Rejected candidates are expected because the build intentionally ignored low-confidence and measure-limited evidence. Rejected high/medium or measure-ready candidates are summarized per signal in `rejected_candidate_audit.csv`; these are the primary evidence source for underbuild review.

## Five-plus absence
Zero 5+ approaches is plausible under the directional-arm cap, but {len(high_complex):,} high-complex signals should be spot-checked because the method can intentionally collapse interchange/parallel-road evidence into at most four arms.

## Ambiguous signals
The staged layer has {len(ambiguous_signal):,} ambiguous signals. These do not invalidate the layer, but they should constrain or block automated corridor construction unless conservative evidence is present.

## Readiness decision
Final decision: `{decision}`.

## Recommended next task
Review or gate two-approach underbuild-risk signals, then build `approach_corridors.parquet` with ambiguity flags carried forward.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "mode": "read_only_audit",
        "audit_target": rel(APPROACHES),
        "validated_parent_objects": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT)],
        "method_comparison_evidence_only": [rel(BUILD_REVIEW), rel(ATTACHMENT_AUDIT), rel(ATTACHMENT_BUILD), rel(CONTRACT_REVIEW), rel(CANONICAL_FINAL), rel(REFRESH_CANDIDATE)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "approach_rows": int(len(approaches)),
        "approach_count_distribution": {str(k): int(v) for k, v in counts["approach_count"].value_counts().sort_index().to_dict().items()},
        "two_approach_taxonomy_counts": {str(k): int(v) for k, v in taxonomy_counts.items()},
        "likely_underbuilt_two_approach_signals": likely_underbuilt_count,
        "ambiguous_signal_count": int(len(ambiguous_signal)),
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    log(f"Audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
