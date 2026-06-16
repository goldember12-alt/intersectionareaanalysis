from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.roadway_graph.crash_count_exploratory_model_fit import OUTPUT_ROOT


OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/internal_modeling_conclusion_readiness_active"
ACTIVE_MODEL_DIR = OUTPUT_ROOT / "analysis/current/crash_count_simplified_internal_model_active"
ACTIVE_NB_DIR = OUTPUT_ROOT / "analysis/current/crash_count_negative_binomial_stabilization_active"
ACTIVE_REFRESH_DIR = OUTPUT_ROOT / "analysis/current/active_refresh_impact_summary"
ACTIVE_RATE_POLICY_DIR = OUTPUT_ROOT / "analysis/current/active_rate_denominator_policy"
ACTIVE_SPEED_POLICY_DIR = OUTPUT_ROOT / "review/current/active_speed_context_policy"
BASELINE_CONCLUSION_DIR = OUTPUT_ROOT / "analysis/current/internal_modeling_conclusion_readiness"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _metric(frame: pd.DataFrame, key: str, value_column: str = "value") -> str:
    if "metric" in frame.columns:
        matched = frame.loc[frame["metric"].eq(key)]
    elif "check_name" in frame.columns:
        matched = frame.loc[frame["check_name"].eq(key)]
        value_column = "observed"
    else:
        return ""
    if matched.empty or value_column not in matched.columns:
        return ""
    return str(matched.iloc[0][value_column])


def _family_delta(family: pd.DataFrame, model_name: str) -> str:
    matched = family.loc[family["model_name"].eq(model_name)]
    if matched.empty:
        return ""
    return str(matched.iloc[0].get("delta_aic_vs_previous", ""))


def _baseline_delta(compare: pd.DataFrame, model_name: str, metric: str = "delta_aic_vs_previous") -> str:
    matched = compare.loc[
        compare["comparison_type"].eq("family_comparison")
        & compare["model_name"].eq(model_name)
        & compare["metric"].eq(metric)
    ]
    if matched.empty:
        return ""
    return str(matched.iloc[0].get("baseline_value", ""))


def _active_delta(compare: pd.DataFrame, model_name: str, metric: str = "delta_aic_vs_previous") -> str:
    matched = compare.loc[
        compare["comparison_type"].eq("family_comparison")
        & compare["model_name"].eq(model_name)
        & compare["metric"].eq(metric)
    ]
    if matched.empty:
        return ""
    return str(matched.iloc[0].get("active_value", ""))


def build_outputs() -> list[Path]:
    created_at = datetime.now(timezone.utc).isoformat()

    input_summary = _read_csv(ACTIVE_NB_DIR / "active_nb_stabilization_input_summary.csv")
    model_decision = _read_csv(ACTIVE_MODEL_DIR / "active_simplified_model_readiness_decision.csv")
    family = _read_csv(ACTIVE_MODEL_DIR / "active_simplified_model_family_comparison.csv")
    active_vs_baseline = _read_csv(ACTIVE_MODEL_DIR / "active_vs_baseline_model_comparison.csv")
    nb_decision = _read_csv(ACTIVE_NB_DIR / "active_nb_model_readiness_decision.csv")
    nb_compare = _read_csv(ACTIVE_NB_DIR / "active_vs_baseline_nb_comparison.csv")
    nb_estimated = _read_csv(ACTIVE_NB_DIR / "active_estimated_alpha_nb_sequence_summary.csv")
    nb_access = _read_csv(ACTIVE_NB_DIR / "active_nb_access_interaction_stability.csv")
    nb_speed = _read_csv(ACTIVE_NB_DIR / "active_nb_speed_term_stability.csv")
    model_matrix = _read_csv(ACTIVE_REFRESH_DIR / "active_refresh_modeling_matrix_comparison.csv")
    context_counts = _read_csv(ACTIVE_REFRESH_DIR / "active_refresh_context_count_comparison.csv")

    rows_modeled = _metric(input_summary, "modeled_rows")
    crashes_modeled = _metric(input_summary, "modeled_assigned_crashes")
    stable_speed_baseline = _metric(context_counts, "stable_speed_bins", "baseline_v1_v4")
    stable_speed_active = _metric(context_counts, "stable_speed_bins", "active_v2_v5")
    modeling_ready_baseline = model_matrix.loc[
        model_matrix["metric"].eq("modeling_ready_units")
        & model_matrix["grain"].eq("signal_direction_window"),
        "baseline_v1_v4",
    ].iloc[0]
    modeling_ready_active = model_matrix.loc[
        model_matrix["metric"].eq("modeling_ready_units")
        & model_matrix["grain"].eq("signal_direction_window"),
        "active_v2_v5",
    ].iloc[0]

    s2_delta = _family_delta(family, "S2_access_interaction")
    s3_delta = _family_delta(family, "S3_access_interaction_speed_simplified")
    s2_delta_baseline = _baseline_delta(active_vs_baseline, "S2_access_interaction")
    s3_delta_baseline = _baseline_delta(active_vs_baseline, "S3_access_interaction_speed_simplified")
    estimated_interpretable_count = str(nb_estimated["interpretable"].astype(str).str.lower().eq("true").sum())
    estimated_nb4 = nb_estimated.loc[
        nb_estimated["model_name"].eq("NB4_access_interaction_speed_simplified_active")
    ].iloc[0]

    conclusion_summary = pd.DataFrame(
        [
            {
                "topic": "active_model_scope",
                "active_value": "active_v2_v5_internal_modeling",
                "baseline_or_comparison": "prior v1/v4 model packages retained as baseline/history",
                "conclusion": "active v2/v5 replaces baseline for current internal modeling review",
            },
            {
                "topic": "modeled_rows",
                "active_value": rows_modeled,
                "baseline_or_comparison": "",
                "conclusion": "denominator-ready active signal-direction-window rows modeled",
            },
            {
                "topic": "modeled_assigned_crashes",
                "active_value": crashes_modeled,
                "baseline_or_comparison": "",
                "conclusion": "assigned crashes represented in active modeled rows",
            },
            {
                "topic": "selected_model",
                "active_value": "S3_access_interaction_speed_simplified",
                "baseline_or_comparison": "same selected internal model name as baseline",
                "conclusion": "selected active internal model remains unchanged",
            },
            {
                "topic": "preferred_model_family",
                "active_value": "scaled and cluster-robust Poisson primary; fixed-alpha NB sensitivity",
                "baseline_or_comparison": "same family decision as baseline",
                "conclusion": "estimated-alpha NB still does not replace Poisson-family inference",
            },
            {
                "topic": "access_window_interaction",
                "active_value": s2_delta,
                "baseline_or_comparison": s2_delta_baseline,
                "conclusion": "access-window interaction remains useful under active v2/v5 but weaker than baseline by scaled-Poisson delta AIC",
            },
            {
                "topic": "simplified_speed",
                "active_value": s3_delta,
                "baseline_or_comparison": s3_delta_baseline,
                "conclusion": "simplified speed remains useful under active v2/v5 but weaker than baseline by scaled-Poisson delta AIC",
            },
            {
                "topic": "estimated_alpha_nb",
                "active_value": f"{estimated_interpretable_count} of 5 estimated-alpha NB models interpretable",
                "baseline_or_comparison": "0 of 5 matched baseline estimated-alpha NB models interpretable",
                "conclusion": "active v2/v5 improved stability, but NB4 remains non-interpretable",
            },
            {
                "topic": "fixed_alpha_nb",
                "active_value": str(nb_decision.iloc[0]["fixed_alpha_nb_grid_fit_success"]),
                "baseline_or_comparison": "fixed-alpha NB also sensitivity-only in baseline",
                "conclusion": "supports access-window and simplified speed as sensitivity evidence only",
            },
            {
                "topic": "speed_coverage",
                "active_value": stable_speed_active,
                "baseline_or_comparison": stable_speed_baseline,
                "conclusion": "active speed v5 increases stable speed coverage for context/model readiness",
            },
            {
                "topic": "window_modeling_ready_units",
                "active_value": modeling_ready_active,
                "baseline_or_comparison": modeling_ready_baseline,
                "conclusion": "active v2/v5 increases window-grain modeling-ready units",
            },
            {
                "topic": "stakeholder_status",
                "active_value": "blocked",
                "baseline_or_comparison": "blocked",
                "conclusion": "no causal, risk, safety-performance, policy, ranking, prediction, or downstream-distance claims are supported",
            },
        ]
    )

    family_table = pd.DataFrame(
        [
            {
                "model_family": "scaled Poisson GLM",
                "active_readiness": "primary_internal_review",
                "evidence": "S0-S3 active sequence fit; overdispersion handled through scaled Pearson inference",
                "limitation": "association model only; not stakeholder-facing",
            },
            {
                "model_family": "cluster-robust Poisson GLM",
                "active_readiness": "primary_internal_review",
                "evidence": "active S3 cluster-robust inference available by reference signal",
                "limitation": "used for coefficient stability review, not final claims",
            },
            {
                "model_family": "estimated-alpha negative binomial",
                "active_readiness": "not_primary_not_interpretable_for_full_selected_model",
                "evidence": f"NB4 converged={estimated_nb4['converged']}; interpretable={estimated_nb4['interpretable']}; alpha={estimated_nb4['alpha_estimate']}",
                "limitation": "NB4 incomplete covariance/non-convergence blocks selected full-speed NB interpretation",
            },
            {
                "model_family": "fixed-alpha negative binomial",
                "active_readiness": "sensitivity_only",
                "evidence": "alpha grid 0.25, 0.5, 1.0, 2.0 fit successfully and supports access-window plus speed additions",
                "limitation": "alpha is imposed rather than stably estimated",
            },
        ]
    )

    artifacts = pd.DataFrame(
        [
            {
                "artifact": "Active simplified internal model package",
                "path": str(ACTIVE_MODEL_DIR),
                "status": "ready_internal_review",
                "use": "active v2/v5 S3 model diagnostics, coefficients, IRRs, and comparisons",
                "restriction": "internal technical review only",
            },
            {
                "artifact": "Active NB stabilization diagnostic",
                "path": str(ACTIVE_NB_DIR),
                "status": "ready_internal_review",
                "use": "NB readiness and sensitivity evidence",
                "restriction": "estimated-alpha NB full model not interpretable",
            },
            {
                "artifact": "Active refresh impact summary",
                "path": str(ACTIVE_REFRESH_DIR),
                "status": "ready_internal_review",
                "use": "baseline-to-active context, exposure, and model-matrix changes",
                "restriction": "not a model result",
            },
            {
                "artifact": "Active internal modeling conclusion memo",
                "path": "docs/reports/roadway_graph/internal_modeling_conclusion_and_presentation_readiness.md",
                "status": "ready_internal_review_after_doc_update",
                "use": "synthesis for internal discussion",
                "restriction": "not stakeholder report language",
            },
            {
                "artifact": "Existing model presentation figures",
                "path": "docs/reports/roadway_graph/modeling_figures/",
                "status": "baseline_historical_until_regenerated",
                "use": "visual style/reference only unless regenerated from active outputs",
                "restriction": "do not present as active v2/v5 figures without refresh",
            },
        ]
    )

    blocked = pd.DataFrame(
        [
            {
                "blocked_claim_type": "causal interpretation",
                "status": "blocked",
                "reason": "exploratory association model only",
            },
            {
                "blocked_claim_type": "risk, danger, or safety-performance language",
                "status": "blocked",
                "reason": "model is internal technical review only",
            },
            {
                "blocked_claim_type": "policy guidance",
                "status": "blocked",
                "reason": "no policy or treatment recommendations are supported",
            },
            {
                "blocked_claim_type": "downstream functional-area distance recommendation",
                "status": "blocked",
                "reason": "window model is not a distance-selection model",
            },
            {
                "blocked_claim_type": "signal rankings or predictions",
                "status": "blocked",
                "reason": "no predictions or rankings were created",
            },
            {
                "blocked_claim_type": "stakeholder model coefficient findings",
                "status": "blocked",
                "reason": "method/language approval and further diagnostic review are still needed",
            },
        ]
    )

    next_steps = pd.DataFrame(
        [
            {
                "priority": 1,
                "recommended_next_step": "Hold internal technical review of active v2/v5 S3 diagnostics and NB stabilization.",
                "purpose": "decide whether any model status language belongs in stakeholder materials",
                "non_goal": "do not turn coefficients into stakeholder findings",
            },
            {
                "priority": 2,
                "recommended_next_step": "Regenerate internal model figures from active v2/v5 outputs before using visuals in review.",
                "purpose": "avoid showing baseline v1/v4 figures as current active evidence",
                "non_goal": "do not update stakeholder report conclusions with model findings",
            },
            {
                "priority": 3,
                "recommended_next_step": "Keep fixed-alpha NB as sensitivity evidence and do not promote estimated-alpha NB.",
                "purpose": "preserve model-family decision discipline",
                "non_goal": "do not treat non-interpretable NB4 as usable",
            },
            {
                "priority": 4,
                "recommended_next_step": "Continue documenting AADT v2 source-semantics caveat and speed v5 QA conflicts.",
                "purpose": "keep active exposure and speed limitations visible",
                "non_goal": "do not create causal or policy claims",
            },
        ]
    )

    outputs = {
        "active_internal_modeling_conclusion_summary.csv": conclusion_summary,
        "active_model_family_readiness_table.csv": family_table,
        "active_presentable_internal_artifacts_table.csv": artifacts,
        "active_blocked_stakeholder_claims_table.csv": blocked,
        "active_recommended_next_steps_modeling.csv": next_steps,
    }

    paths: list[Path] = []
    for filename, frame in outputs.items():
        path = OUTPUT_DIR / filename
        _write_csv(frame, path)
        paths.append(path)

    manifest = {
        "package": "internal_modeling_conclusion_readiness_active",
        "created_at_utc": created_at,
        "bounded_question": "active v2/v5 internal modeling conclusion and presentation-readiness support tables",
        "inputs": {
            "active_simplified_internal_model": str(ACTIVE_MODEL_DIR),
            "active_nb_stabilization": str(ACTIVE_NB_DIR),
            "active_refresh_impact_summary": str(ACTIVE_REFRESH_DIR),
            "active_rate_denominator_policy": str(ACTIVE_RATE_POLICY_DIR),
            "active_speed_context_policy": str(ACTIVE_SPEED_POLICY_DIR),
            "baseline_conclusion_for_comparison_only": str(BASELINE_CONCLUSION_DIR),
        },
        "outputs": {filename: str(OUTPUT_DIR / filename) for filename in outputs},
        "guardrails": {
            "new_models_fit": False,
            "new_rates_computed": False,
            "crash_direction_fields_used": False,
            "additional_direction_factor_applied": False,
            "predictions_created": False,
            "rankings_created": False,
            "causal_policy_risk_safety_language_introduced": False,
            "stakeholder_report_model_findings_updated": False,
        },
        "active_conclusion": {
            "selected_model": "S3_access_interaction_speed_simplified",
            "preferred_family": "scaled and cluster-robust Poisson primary; fixed-alpha NB sensitivity",
            "estimated_alpha_nb_full_model_interpretable": False,
            "stakeholder_interpretation": "blocked",
        },
    }
    manifest_path = OUTPUT_DIR / "active_internal_modeling_conclusion_manifest.json"
    _write_json(manifest, manifest_path)
    paths.append(manifest_path)
    return paths


def main() -> None:
    paths = build_outputs()
    print("Created active internal modeling conclusion support outputs:")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
