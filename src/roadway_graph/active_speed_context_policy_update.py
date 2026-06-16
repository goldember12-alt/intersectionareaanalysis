from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = OUTPUT_ROOT / "review/current/active_speed_context_policy"

SPEED_V4_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v4_identity_enriched"
SPEED_V5_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v5_new_source_supplement"
NORMALIZED_SPEED_FILE = Path("artifacts/normalized/speed.parquet")

SPEED_V4_CONTEXT_FILE = SPEED_V4_DIR / "directional_bin_speed_context_v4.csv"
SPEED_V4_SUMMARY_FILE = SPEED_V4_DIR / "speed_context_v4_summary.csv"
SPEED_V4_MANIFEST_FILE = SPEED_V4_DIR / "speed_context_v4_manifest.json"
SPEED_V5_SUMMARY_FILE = SPEED_V5_DIR / "speed_context_v5_summary.csv"
SPEED_V5_COMPARISON_FILE = SPEED_V5_DIR / "speed_v5_comparison_to_v4.csv"
SPEED_V5_CONFLICT_FILE = SPEED_V5_DIR / "speed_v5_conflict_with_v4_stable.csv"
SPEED_V5_REVIEW_FILE = SPEED_V5_DIR / "speed_v5_ambiguous_or_review_bins.csv"
SPEED_V5_MISSING_FILE = SPEED_V5_DIR / "speed_v5_missing_bins.csv"
SPEED_V5_MANIFEST_FILE = SPEED_V5_DIR / "speed_context_v5_manifest.json"

OUTPUTS = {
    "summary": "active_speed_context_policy_summary.csv",
    "rules": "active_speed_context_policy_rules.csv",
    "comparison": "active_speed_context_v4_v5_comparison.csv",
    "conflict": "active_speed_context_conflict_summary.csv",
    "refresh": "active_speed_context_downstream_refresh_requirements.csv",
    "findings": "active_speed_context_policy_findings.md",
    "manifest": "active_speed_context_policy_manifest.json",
}

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    columns = header if usecols is None else usecols
    blocked = [column for column in columns if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _metric(summary: pd.DataFrame, name: str) -> Any:
    row = summary.loc[summary["metric"].eq(name)]
    if row.empty:
        return ""
    value = row.iloc[0].get("count", "")
    return value if str(value) != "" else row.iloc[0].get("value", "")


def _summary(v5_summary: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"metric": "active_speed_context_policy", "value": "speed_v5_new_source_supplement", "count": ""},
        {"metric": "baseline_speed_context_policy", "value": "speed_v4_identity_enriched", "count": ""},
        {"metric": "active_speed_source_preference", "value": "Speed_Limit_RNS route_measure_evidence_preferred", "count": ""},
        {"metric": "v4_stable_speed_bins", "value": "", "count": int(_metric(v5_summary, "v4_stable_speed_bins"))},
        {"metric": "v5_stable_speed_bins", "value": "", "count": int(_metric(v5_summary, "v5_stable_speed_bins"))},
        {"metric": "newly_recovered_stable_bins_from_v4_missing_review", "value": "", "count": int(_metric(v5_summary, "newly_recovered_stable_bins_from_v4_missing_review"))},
        {"metric": "v5_missing_review_bins_remaining", "value": "", "count": int(_metric(v5_summary, "v5_missing_review_bins_remaining"))},
        {"metric": "v4_stable_bins_confirmed_by_v5", "value": "", "count": int(_metric(v5_summary, "v4_stable_bins_confirmed_by_v5"))},
        {"metric": "v4_stable_bins_conflicting_with_v5", "value": "", "count": int(_metric(v5_summary, "v4_stable_bins_conflicting_with_v5"))},
        {"metric": "crash_rows_inheriting_stable_v5_speed", "value": "", "count": int(_metric(v5_summary, "crash_rows_inheriting_stable_v5_speed"))},
        {"metric": "reference_signals_with_stable_v5_speed", "value": "", "count": int(_metric(v5_summary, "reference_signals_with_stable_v5_speed"))},
        {"metric": "v5_conflicts_block_promotion", "value": False, "count": ""},
        {"metric": "speed_values_imputed", "value": False, "count": ""},
        {"metric": "downstream_outputs_refreshed", "value": False, "count": ""},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
    ]
    for row in v5_summary.loc[v5_summary["metric"].str.contains("by_distance_window", na=False)].itertuples(index=False):
        rows.append({"metric": row.metric, "value": row.value, "count": row.count})
    return pd.DataFrame(rows)


def _rules() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rule_id": "active_context",
                "active_policy": "speed_v5_new_source_supplement",
                "rule": "Use speed v5 as the active speed context going forward.",
                "implementation_status": "active_for_future_refresh",
            },
            {
                "rule_id": "baseline_retention",
                "active_policy": "speed_v5_new_source_supplement",
                "rule": "Retain speed v4 identity-enriched outputs as baseline and legacy comparison artifacts.",
                "implementation_status": "required_boundary",
            },
            {
                "rule_id": "source_preference",
                "active_policy": "speed_v5_new_source_supplement",
                "rule": "Prefer Speed_Limit_RNS route+measure evidence over speed v4 when v5 provides stable speed assignment.",
                "implementation_status": "approved",
            },
            {
                "rule_id": "conflicts",
                "active_policy": "speed_v5_new_source_supplement",
                "rule": "Preserve v4/v5 conflicts as QA comparison evidence; do not treat them as blockers to v5 promotion.",
                "implementation_status": "approved_qa_evidence",
            },
            {
                "rule_id": "remaining_review",
                "active_policy": "speed_v5_new_source_supplement",
                "rule": "Keep v5 remaining review and missing statuses visible; do not force labels.",
                "implementation_status": "required_boundary",
            },
            {
                "rule_id": "no_imputation",
                "active_policy": "speed_v5_new_source_supplement",
                "rule": "Do not impute speed values. Stable v5 assignment requires route+measure evidence from Speed_Limit_RNS.",
                "implementation_status": "required_boundary",
            },
            {
                "rule_id": "downstream_refresh",
                "active_policy": "speed_v5_new_source_supplement",
                "rule": "Refresh downstream context, descriptive, rate, and model outputs before treating them as using active v5 speed.",
                "implementation_status": "required_next_step",
            },
        ]
    )


def _comparison(v5_comparison: pd.DataFrame) -> pd.DataFrame:
    out = v5_comparison.copy()
    out.insert(0, "active_interpretation", out["comparison_group"].map(_comparison_interpretation))
    return out


def _comparison_interpretation(group: str) -> str:
    mapping = {
        "not_recovered": "remaining_v5_missing_or_review",
        "v4_missing_review_recovered_by_rns": "new_v5_active_recovery",
        "v4_stable_retained_confirmed_by_rns": "v4_baseline_confirmed_by_active_v5",
        "v4_stable_retained_conflict_preserved": "v4_baseline_conflicts_with_active_v5_preserve_for_qa",
        "v4_stable_retained_no_rns_confirmation": "v4_baseline_no_stable_v5_candidate_preserve_for_qa",
        "v4_status_to_v5_status": "status_crosswalk",
    }
    return mapping.get(str(group), "review")


def _conflict_summary(conflicts: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if not conflicts.empty:
        for keys, group in conflicts.groupby(["distance_window", "v5_v4_comparison_status"], dropna=False):
            distance_window, status = keys
            rows.append(
                {
                    "summary_group": "v4_v5_conflict",
                    "distance_window": distance_window,
                    "status": status,
                    "bin_count": len(group),
                    "unique_route_count": group["stable_route_name_normalized"].nunique() if "stable_route_name_normalized" in group.columns else "",
                    "qa_interpretation": "v4 conflicts with improved active v5 source; preserve for QA, not a promotion blocker",
                }
            )
    if not review.empty:
        for keys, group in review.groupby(["distance_window", "v5_refined_speed_context_status"], dropna=False):
            distance_window, status = keys
            rows.append(
                {
                    "summary_group": "remaining_v5_review_missing",
                    "distance_window": distance_window,
                    "status": status,
                    "bin_count": len(group),
                    "unique_route_count": group["stable_route_name_normalized"].nunique() if "stable_route_name_normalized" in group.columns else "",
                    "qa_interpretation": "remaining missing/review status preserved",
                }
            )
    return pd.DataFrame(rows)


def _refresh_requirements() -> pd.DataFrame:
    rows = [
        ("directional_bin_context_table", "Refresh combined context table to replace speed v4 fields with accepted speed v5 fields.", "required_before_current_context_claim"),
        ("directional_context_descriptive_summaries", "Refresh descriptive summaries using active v5 speed context.", "required"),
        ("signal_context_review_queue", "Refresh review queues where speed missing/review status influences priority.", "required"),
        ("distance_band_and_signal_direction_profiles", "Refresh profiles and stakeholder package speed context summaries.", "required"),
        ("report_figures_and_tables", "Refresh any context relationship figures/tables using speed bands or speed coverage.", "required"),
        ("rate_outputs", "Refresh rate outputs only after active denominator v2 and active speed v5 are both integrated in the accepted context product.", "required_before_rate_current_claim"),
        ("modeling_readiness_and_internal_models", "Refresh exposure/model matrices and internal models before interpreting speed terms under v5.", "required_before_model_current_claim"),
        ("speed_v4_outputs", "Do not overwrite or delete; retain as baseline/legacy comparison.", "preserve"),
    ]
    return pd.DataFrame(rows, columns=["downstream_area", "refresh_requirement", "status"])


def _qa(mtimes_before: dict[str, float | None], mtimes_after: dict[str, float | None], summary: pd.DataFrame, rules: pd.DataFrame, refresh: pd.DataFrame) -> pd.DataFrame:
    v4_unchanged = all(mtimes_before.get(str(path)) == mtimes_after.get(str(path)) for path in [SPEED_V4_CONTEXT_FILE, SPEED_V4_SUMMARY_FILE, SPEED_V4_MANIFEST_FILE])
    normalized_unchanged = mtimes_before.get(str(NORMALIZED_SPEED_FILE)) == mtimes_after.get(str(NORMALIZED_SPEED_FILE))
    rows = [
        {"check_name": "speed_v4_outputs_overwritten", "passed": v4_unchanged, "observed": "unchanged" if v4_unchanged else "mtime_changed", "expected": "unchanged"},
        {"check_name": "normalized_speed_parquet_overwritten", "passed": normalized_unchanged, "observed": "unchanged" if normalized_unchanged else "mtime_changed", "expected": "unchanged"},
        {"check_name": "graph_context_rate_model_outputs_silently_changed", "passed": True, "observed": "policy_record_only", "expected": "no"},
        {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
        {"check_name": "v5_clearly_labeled_active_going_forward", "passed": summary["value"].astype(str).str.contains("speed_v5_new_source_supplement").any(), "observed": "speed_v5_new_source_supplement", "expected": "active"},
        {"check_name": "v4_retained_as_baseline_legacy", "passed": rules["rule_id"].eq("baseline_retention").any(), "observed": "baseline_retention_rule", "expected": "present"},
        {"check_name": "downstream_refresh_requirements_explicit", "passed": len(refresh) > 0, "observed": len(refresh), "expected": ">0"},
    ]
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    values = {row.metric: row.value if str(row.value) != "" else row.count for row in summary.itertuples(index=False)}
    qa_lines = "\n".join(f"- {row.check_name}: {'PASS' if bool(row.passed) else 'FAIL'} ({row.observed})" for row in qa.itertuples(index=False))
    return f"""# Active Speed Context Policy Findings

## Bounded Question

Promote speed v5 as the active speed context going forward, while preserving speed v4 as baseline/legacy comparison and avoiding downstream reruns in this task.

## Active Policy

`speed_v5_new_source_supplement` is active going forward.

- Speed_Limit_RNS route+measure evidence is preferred.
- Speed v4 is retained as baseline/legacy comparison.
- V4/v5 conflicts are QA evidence, not blockers to v5 promotion.
- Remaining v5 review/missing statuses stay visible.
- No speed values are imputed.

## Policy Summary

- v4 stable speed bins: {values['v4_stable_speed_bins']}
- v5 stable speed bins: {values['v5_stable_speed_bins']}
- newly recovered stable bins from v4 missing/review: {values['newly_recovered_stable_bins_from_v4_missing_review']}
- v5 missing/review bins remaining: {values['v5_missing_review_bins_remaining']}
- v4 stable bins confirmed by v5: {values['v4_stable_bins_confirmed_by_v5']}
- v4 stable bins conflicting with v5: {values['v4_stable_bins_conflicting_with_v5']}
- crash rows inheriting stable v5 speed: {values['crash_rows_inheriting_stable_v5_speed']}
- reference signals with stable v5 speed: {values['reference_signals_with_stable_v5_speed']}

## QA

{qa_lines}

## Outputs

{chr(10).join(f'- `{path}`' for path in outputs.values())}
"""


def build_active_speed_context_policy_update(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / "review/current/active_speed_context_policy"
    outputs = {key: out_dir / name for key, name in OUTPUTS.items()}
    tracked = [NORMALIZED_SPEED_FILE, SPEED_V4_CONTEXT_FILE, SPEED_V4_SUMMARY_FILE, SPEED_V4_MANIFEST_FILE]
    mtimes_before = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}

    v5_summary = _read_csv(SPEED_V5_SUMMARY_FILE)
    v5_comparison = _read_csv(SPEED_V5_COMPARISON_FILE)
    conflicts = _read_csv(SPEED_V5_CONFLICT_FILE)
    review = _read_csv(SPEED_V5_REVIEW_FILE)

    summary = _summary(v5_summary)
    rules = _rules()
    comparison = _comparison(v5_comparison)
    conflict_summary = _conflict_summary(conflicts, review)
    refresh = _refresh_requirements()

    _write_csv(summary, outputs["summary"])
    _write_csv(rules, outputs["rules"])
    _write_csv(comparison, outputs["comparison"])
    _write_csv(conflict_summary, outputs["conflict"])
    _write_csv(refresh, outputs["refresh"])

    mtimes_after = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}
    qa = _qa(mtimes_before, mtimes_after, summary, rules, refresh)
    _write_csv(qa, out_dir / "active_speed_context_policy_qa.csv")
    _write_text(_findings(summary, qa, outputs), outputs["findings"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "promote speed v5 as active speed context without overwriting v4 or downstream outputs",
        "active_speed_context": "speed_v5_new_source_supplement",
        "baseline_speed_context": "speed_v4_identity_enriched",
        "speed_v4_outputs_overwritten": False,
        "normalized_speed_parquet_overwritten": False,
        "graph_context_rate_model_outputs_modified": False,
        "crash_direction_fields_read_or_used": False,
        "inputs": {
            "speed_v5_summary": str(SPEED_V5_SUMMARY_FILE),
            "speed_v5_comparison": str(SPEED_V5_COMPARISON_FILE),
            "speed_v5_conflicts": str(SPEED_V5_CONFLICT_FILE),
            "speed_v5_review": str(SPEED_V5_REVIEW_FILE),
            "speed_v5_manifest": str(SPEED_V5_MANIFEST_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()} | {"qa": str(out_dir / "active_speed_context_policy_qa.csv")},
        "summary": summary.to_dict(orient="records"),
        "rules": rules.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return manifest["outputs"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote speed v5 as active speed context policy.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_active_speed_context_policy_update(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
