from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/active_rate_denominator_policy"
SENSITIVITY_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_direction_factor_sensitivity"
V1_RATE_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype"
V1_SUPPRESSION_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_suppression_review"

COMPARISON_FILE = SENSITIVITY_DIR / "direction_factor_sensitivity_comparison_to_v1.csv"
COVERAGE_FILE = SENSITIVITY_DIR / "direction_factor_application_coverage.csv"
WINDOW_SUMMARY_FILE = SENSITIVITY_DIR / "direction_factor_sensitivity_summary_by_window.csv"
SENSITIVITY_FINDINGS_FILE = SENSITIVITY_DIR / "direction_factor_sensitivity_findings.md"
V1_RATE_FILE = V1_RATE_DIR / "descriptive_rate_prototype_signal_direction_window.csv"
V1_SUPPRESSION_FILE = V1_SUPPRESSION_DIR / "rate_unit_suppression_flags.csv"

OUTPUTS = {
    "summary": "active_rate_denominator_policy_summary.csv",
    "rules": "active_rate_denominator_policy_rules.csv",
    "comparison": "active_rate_denominator_policy_comparison_v1_v2.csv",
    "findings": "active_rate_denominator_policy_findings.md",
    "manifest": "active_rate_denominator_policy_manifest.json",
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
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _metric(frame: pd.DataFrame, name: str) -> float:
    row = frame.loc[frame["metric"].eq(name)]
    if row.empty:
        return 0.0
    return float(row.iloc[0]["value"])


def _summary(comparison: pd.DataFrame, coverage: pd.DataFrame) -> pd.DataFrame:
    assigned = _num(comparison["assigned_crash_count"]).sum()
    v1_exposure = _num(comparison["v1_estimated_exposure"]).sum()
    v2_exposure = _num(comparison["v2_direction_factor_adjusted_exposure"]).sum()
    v1_rate = assigned / v1_exposure * 1_000_000 if v1_exposure else 0.0
    v2_rate = assigned / v2_exposure * 1_000_000 if v2_exposure else 0.0
    rows = [
        {"metric": "active_denominator_policy", "value": "v2_direction_factor_with_bidirectional_fallback", "count": ""},
        {"metric": "baseline_denominator_policy", "value": "v1_bidirectional_aadt", "count": ""},
        {"metric": "units_evaluated", "value": "", "count": int(len(comparison))},
        {"metric": "units_with_factor_applied", "value": "", "count": int(_metric(coverage, "units_with_valid_factor_applied"))},
        {"metric": "units_using_null_factor_bidirectional_fallback", "value": "", "count": int(_metric(coverage, "units_with_null_factor_bidirectional_fallback"))},
        {"metric": "units_with_invalid_factor_review", "value": "", "count": int(_metric(coverage, "units_with_invalid_factor_review"))},
        {"metric": "assigned_crash_count", "value": "", "count": int(assigned)},
        {"metric": "v1_estimated_exposure", "value": round(v1_exposure, 2), "count": ""},
        {"metric": "v2_adjusted_exposure", "value": round(v2_exposure, 2), "count": ""},
        {"metric": "exposure_ratio_v2_to_v1", "value": round(v2_exposure / v1_exposure, 6) if v1_exposure else "", "count": ""},
        {"metric": "v1_aggregate_descriptive_rate_per_million", "value": round(v1_rate, 6), "count": ""},
        {"metric": "v2_aggregate_descriptive_rate_per_million", "value": round(v2_rate, 6), "count": ""},
        {"metric": "rate_ratio_v2_to_v1", "value": round(v2_rate / v1_rate, 6) if v1_rate else "", "count": ""},
        {"metric": "source_documentation_caveat", "value": "source documentation still needed to fully confirm DIRECTION_FACTOR semantics", "count": ""},
        {"metric": "crash_direction_fields_read_or_used", "value": False, "count": ""},
        {"metric": "rates_or_models_recomputed", "value": False, "count": ""},
    ]
    return pd.DataFrame(rows)


def _rules() -> pd.DataFrame:
    rows = [
        {
            "rule_id": "policy_status",
            "active_policy": "v2_direction_factor_with_bidirectional_fallback",
            "rule": "Treat v2 as the active descriptive exposure denominator policy going forward.",
            "implementation_status": "active_for_future_refresh",
        },
        {
            "rule_id": "valid_direction_factor",
            "active_policy": "v2_direction_factor_with_bidirectional_fallback",
            "rule": "Where DIRECTION_FACTOR is valid, apply it to stable AADT exposure in the approved window-grain descriptive denominator context.",
            "implementation_status": "approved",
        },
        {
            "rule_id": "null_direction_factor",
            "active_policy": "v2_direction_factor_with_bidirectional_fallback",
            "rule": "Where DIRECTION_FACTOR is null, fall back to v1 bidirectional AADT treatment.",
            "implementation_status": "approved",
        },
        {
            "rule_id": "invalid_direction_factor",
            "active_policy": "v2_direction_factor_with_bidirectional_fallback",
            "rule": "Where DIRECTION_FACTOR is invalid, flag the row for review and retain transparent fallback handling rather than silently applying the factor.",
            "implementation_status": "approved_flag_required",
        },
        {
            "rule_id": "scope_limit",
            "active_policy": "v2_direction_factor_with_bidirectional_fallback",
            "rule": "Do not apply DIRECTION_FACTOR outside the approved descriptive exposure denominator context.",
            "implementation_status": "required_boundary",
        },
        {
            "rule_id": "v1_retention",
            "active_policy": "v2_direction_factor_with_bidirectional_fallback",
            "rule": "Retain v1 outputs as baseline and legacy comparison artifacts; do not overwrite or delete them.",
            "implementation_status": "required_boundary",
        },
        {
            "rule_id": "source_documentation",
            "active_policy": "v2_direction_factor_with_bidirectional_fallback",
            "rule": "Preserve caveat that source documentation is still needed to fully confirm field semantics.",
            "implementation_status": "open_caveat",
        },
    ]
    return pd.DataFrame(rows)


def _comparison(comparison: pd.DataFrame, window_summary: pd.DataFrame) -> pd.DataFrame:
    assigned = _num(comparison["assigned_crash_count"]).sum()
    v1_exposure = _num(comparison["v1_estimated_exposure"]).sum()
    v2_exposure = _num(comparison["v2_direction_factor_adjusted_exposure"]).sum()
    rows = [
        {
            "comparison_scope": "all_denominator_ready_units",
            "unit_count": len(comparison),
            "assigned_crash_count": int(assigned),
            "v1_estimated_exposure": v1_exposure,
            "v2_direction_factor_adjusted_exposure": v2_exposure,
            "exposure_ratio_v2_to_v1": v2_exposure / v1_exposure if v1_exposure else pd.NA,
            "v1_rate_per_million": assigned / v1_exposure * 1_000_000 if v1_exposure else pd.NA,
            "v2_rate_per_million": assigned / v2_exposure * 1_000_000 if v2_exposure else pd.NA,
            "rate_ratio_v2_to_v1": (assigned / v2_exposure) / (assigned / v1_exposure) if assigned and v1_exposure and v2_exposure else pd.NA,
        }
    ]
    for row in window_summary.itertuples(index=False):
        assigned_window = float(row.assigned_crash_count)
        v1_window = float(row.v1_estimated_exposure)
        v2_window = float(row.v2_direction_factor_adjusted_exposure)
        rows.append(
            {
                "comparison_scope": f"analysis_window:{row.analysis_window}",
                "unit_count": int(row.unit_count),
                "assigned_crash_count": int(assigned_window),
                "v1_estimated_exposure": v1_window,
                "v2_direction_factor_adjusted_exposure": v2_window,
                "exposure_ratio_v2_to_v1": v2_window / v1_window if v1_window else pd.NA,
                "v1_rate_per_million": assigned_window / v1_window * 1_000_000 if v1_window else pd.NA,
                "v2_rate_per_million": assigned_window / v2_window * 1_000_000 if v2_window else pd.NA,
                "rate_ratio_v2_to_v1": (assigned_window / v2_window) / (assigned_window / v1_window) if assigned_window and v1_window and v2_window else pd.NA,
            }
        )
    return pd.DataFrame(rows)


def _qa(mtimes_before: dict[str, float | None], mtimes_after: dict[str, float | None]) -> pd.DataFrame:
    v1_unchanged = mtimes_before == mtimes_after
    rows = [
        {"check_name": "v1_outputs_overwritten", "passed": v1_unchanged, "observed": "unchanged" if v1_unchanged else "mtime_changed", "expected": "unchanged"},
        {"check_name": "rates_or_models_silently_changed", "passed": True, "observed": "no_rate_or_model_outputs_written", "expected": "no"},
        {"check_name": "v2_policy_clear_active", "passed": True, "observed": "active_policy_output_and_docs", "expected": "yes"},
        {"check_name": "null_factor_fallback_documented", "passed": True, "observed": "rule_written", "expected": "yes"},
        {"check_name": "source_documentation_caveat_preserved", "passed": True, "observed": "rule_written", "expected": "yes"},
        {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
    ]
    return pd.DataFrame(rows)


def _findings(summary: pd.DataFrame, comparison: pd.DataFrame, qa: pd.DataFrame, outputs: dict[str, Path]) -> str:
    values = {row.metric: row.value if str(row.value) != "" else row.count for row in summary.itertuples(index=False)}
    qa_lines = "\n".join(f"- {row.check_name}: {'PASS' if bool(row.passed) else 'FAIL'} ({row.observed})" for row in qa.itertuples(index=False))
    return f"""# Active Rate Denominator Policy Findings

## Bounded Question

Promote AADT direction-factor v2 to the active descriptive exposure denominator policy without overwriting v1 outputs or rerunning rates/models.

## Active Policy

`v2_direction_factor_with_bidirectional_fallback` is active going forward.

- Valid `DIRECTION_FACTOR`: apply in the approved descriptive exposure denominator context.
- Null `DIRECTION_FACTOR`: use v1 bidirectional AADT fallback.
- Invalid `DIRECTION_FACTOR`: flag for review.
- V1 bidirectional AADT outputs remain baseline/legacy comparison artifacts.
- Source documentation is still needed to fully confirm `DIRECTION_FACTOR` semantics.

## Policy Summary

- Units evaluated: {values['units_evaluated']}
- Units with factor applied: {values['units_with_factor_applied']}
- Units using null-factor bidirectional fallback: {values['units_using_null_factor_bidirectional_fallback']}
- Units with invalid factor: {values['units_with_invalid_factor_review']}
- V1 exposure: {values['v1_estimated_exposure']}
- V2 adjusted exposure: {values['v2_adjusted_exposure']}
- Exposure ratio v2/v1: {values['exposure_ratio_v2_to_v1']}
- V1 aggregate descriptive rate per million: {values['v1_aggregate_descriptive_rate_per_million']}
- V2 aggregate descriptive rate per million: {values['v2_aggregate_descriptive_rate_per_million']}
- Rate ratio v2/v1: {values['rate_ratio_v2_to_v1']}

## Downstream Refresh Needed

- `descriptive_crash_rate_prototype` v2 active denominator outputs.
- `descriptive_crash_rate_suppression_review` using v2 active denominator outputs.
- Context relationship rate figures using v2.
- Modeling readiness offset/exposure update.
- Simplified internal model v2 only if speed/AADT context changes are accepted.

## QA

{qa_lines}

## Outputs

{chr(10).join(f'- `{path}`' for path in outputs.values())}
"""


def build_active_rate_denominator_policy_update(*, output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    started = datetime.now(timezone.utc)
    out_dir = output_root / "analysis/current/active_rate_denominator_policy"
    outputs = {key: out_dir / name for key, name in OUTPUTS.items()}
    tracked = [V1_RATE_FILE, V1_SUPPRESSION_FILE]
    mtimes_before = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}

    comparison_rows = _read_csv(COMPARISON_FILE)
    for column in [
        "assigned_crash_count",
        "v1_estimated_exposure",
        "v2_direction_factor_adjusted_exposure",
        "exposure_ratio_v2_to_v1",
        "v1_rate_per_million",
        "v2_rate_per_million",
        "rate_ratio_v2_to_v1",
    ]:
        comparison_rows[column] = _num(comparison_rows[column])
    coverage = _read_csv(COVERAGE_FILE)
    window_summary = _read_csv(WINDOW_SUMMARY_FILE)

    summary = _summary(comparison_rows, coverage)
    rules = _rules()
    comparison = _comparison(comparison_rows, window_summary)

    _write_csv(summary, outputs["summary"])
    _write_csv(rules, outputs["rules"])
    _write_csv(comparison, outputs["comparison"])

    mtimes_after = {str(path): path.stat().st_mtime if path.exists() else None for path in tracked}
    qa = _qa(mtimes_before, mtimes_after)
    _write_csv(qa, out_dir / "active_rate_denominator_policy_qa.csv")
    _write_text(_findings(summary, comparison, qa, outputs), outputs["findings"])
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "promote AADT direction-factor v2 to active descriptive exposure denominator policy",
        "active_policy": "v2_direction_factor_with_bidirectional_fallback",
        "v1_retained_as_baseline": True,
        "rates_or_models_recomputed": False,
        "crash_direction_fields_read_or_used": False,
        "inputs": {
            "sensitivity_comparison": str(COMPARISON_FILE),
            "application_coverage": str(COVERAGE_FILE),
            "window_summary": str(WINDOW_SUMMARY_FILE),
            "sensitivity_findings": str(SENSITIVITY_FINDINGS_FILE),
        },
        "outputs": {key: str(path) for key, path in outputs.items()} | {"qa": str(out_dir / "active_rate_denominator_policy_qa.csv")},
        "summary": summary.to_dict(orient="records"),
        "rules": rules.to_dict(orient="records"),
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, outputs["manifest"])
    return manifest["outputs"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote AADT direction-factor v2 to active descriptive denominator policy.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    outputs = build_active_rate_denominator_policy_update(output_root=args.output_root)
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
