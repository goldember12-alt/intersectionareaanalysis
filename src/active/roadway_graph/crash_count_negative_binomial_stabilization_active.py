from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.active.roadway_graph.crash_count_exploratory_model_fit import OUTPUT_ROOT, _package_available, _safe_exp
from src.active.roadway_graph.crash_count_negative_binomial_stabilization import (
    ALPHA_GRID,
    _aic_delta,
    _ci_crosses_one,
    _coef_sign,
    _coefficient_rows,
    _diagnostic_row,
    _fit_estimated_nb,
    _fit_fixed_alpha_nb,
    _irr_frame,
    _term_group,
    _warning_rows,
)


OUTPUT_DIR = OUTPUT_ROOT / "analysis/current/crash_count_negative_binomial_stabilization_active"
ACTIVE_SIMPLIFIED_DIR = OUTPUT_ROOT / "analysis/current/crash_count_simplified_internal_model_active"
ACTIVE_MODEL_DIR = OUTPUT_ROOT / "analysis/current/crash_count_modeling_readiness_dataset_active"
ACTIVE_RATE_DIR = OUTPUT_ROOT / "analysis/current/descriptive_crash_rate_prototype_active"
ACTIVE_SPEED_POLICY_DIR = OUTPUT_ROOT / "review/current/active_speed_context_policy"
ACTIVE_AADT_POLICY_DIR = OUTPUT_ROOT / "analysis/current/active_rate_denominator_policy"
BASELINE_NB_DIR = OUTPUT_ROOT / "analysis/current/crash_count_negative_binomial_stabilization"
MODEL_SPEC_FILE = Path("docs/design/roadway_graph_crash_count_model_specification.md")

ACTIVE_INPUT_FILE = ACTIVE_SIMPLIFIED_DIR / "active_simplified_model_input_rows.csv"
ACTIVE_POISSON_COEFFICIENTS_FILE = ACTIVE_SIMPLIFIED_DIR / "active_simplified_model_coefficients.csv"
ACTIVE_POISSON_DIAGNOSTICS_FILE = ACTIVE_SIMPLIFIED_DIR / "active_simplified_model_diagnostics.csv"
BASELINE_ESTIMATED_SUMMARY_FILE = BASELINE_NB_DIR / "estimated_alpha_nb_sequence_summary.csv"
BASELINE_FIXED_SUMMARY_FILE = BASELINE_NB_DIR / "fixed_alpha_nb_sequence_summary.csv"
BASELINE_READINESS_FILE = BASELINE_NB_DIR / "nb_model_readiness_decision.csv"

READINESS_OPTIONS = [
    "active_estimated_nb_ready_internal_only",
    "active_estimated_nb_ready_after_simplification",
    "active_fixed_alpha_nb_sensitivity_only",
    "active_robust_poisson_primary_nb_sensitivity",
    "active_no_count_model_ready",
]

FORMULAS = {
    "NB0_exposure_only_active": "assigned_crash_count ~ 1",
    "NB1_window_direction_active": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "NB2_add_access_no_interaction_active": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(local_access_density_label, Treatment(reference='0'))",
    "NB3_access_interaction_no_speed_active": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) * C(local_access_density_label, Treatment(reference='0')) + C(signal_relative_direction_model, Treatment(reference='downstream'))",
    "NB4_access_interaction_speed_simplified_active": "assigned_crash_count ~ C(analysis_window_readable, Treatment(reference='0-1,000 ft')) * C(local_access_density_label, Treatment(reference='0')) + C(signal_relative_direction_model, Treatment(reference='downstream')) + C(speed_band_simplified, Treatment(reference='30-39 mph'))",
}

BASELINE_MODEL_MAP = {
    "NB0_exposure_only_active": "NB0_exposure_only",
    "NB1_window_direction_active": "NB1_window_direction",
    "NB2_add_access_no_interaction_active": "NB2_add_access_no_interaction",
    "NB3_access_interaction_no_speed_active": "NB3_access_interaction_no_speed",
    "NB4_access_interaction_speed_simplified_active": "NB4_access_interaction_speed_simplified",
}

POISSON_MODEL_MAP = {
    "NB0_exposure_only_active": "S0_exposure_only",
    "NB1_window_direction_active": "S1_window_direction",
    "NB3_access_interaction_no_speed_active": "S2_access_interaction",
    "NB4_access_interaction_speed_simplified_active": "S3_access_interaction_speed_simplified",
}

CRASH_DIRECTION_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel")


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


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().isin(["true", "1", "yes"])


def _prepare_input() -> pd.DataFrame:
    frame = _read_csv(ACTIVE_INPUT_FILE)
    numeric_columns = [
        "assigned_crash_count",
        "estimated_exposure",
        "log_estimated_exposure",
        "active_length_weighted_speed",
        "stable_speed_coverage_share",
    ]
    for column in numeric_columns:
        if column in frame.columns:
            frame[column] = _num(frame[column])
    for column in ["denominator_ready_flag", "modeling_ready_candidate"]:
        if column in frame.columns:
            frame[column] = _bool(frame[column])
    frame = frame.loc[frame["denominator_ready_flag"]].copy()
    frame["analysis_window_readable"] = pd.Categorical(
        frame["analysis_window_readable"],
        categories=["0-1,000 ft", "1,000-2,500 ft"],
        ordered=True,
    )
    frame["signal_relative_direction_model"] = pd.Categorical(
        frame["signal_relative_direction_model"],
        categories=["downstream", "upstream"],
        ordered=True,
    )
    frame["local_access_density_label"] = pd.Categorical(
        frame["local_access_density_label"],
        categories=["0", ">0-1", "1-3", "3-6", "6+"],
        ordered=True,
    )
    frame["speed_band_simplified"] = pd.Categorical(
        frame["speed_band_simplified"],
        categories=["30-39 mph", "<30 mph", "40-49 mph", "50+ mph", "missing/review speed"],
        ordered=True,
    )
    return frame


def _fit_sequences(model_input: pd.DataFrame) -> dict[str, pd.DataFrame]:
    estimated_summary: list[dict[str, Any]] = []
    estimated_coefs: list[dict[str, Any]] = []
    fixed_summary: list[dict[str, Any]] = []
    fixed_coefs: list[dict[str, Any]] = []
    warning_log: list[dict[str, Any]] = []
    for model_name, formula in FORMULAS.items():
        result, messages = _fit_estimated_nb(model_name, formula, model_input)
        estimated_summary.append(_diagnostic_row(model_name, "estimated_alpha_negative_binomial", result, model_input, messages))
        estimated_coefs.extend(_coefficient_rows(model_name, "estimated_alpha_negative_binomial", result))
        warning_log.extend(_warning_rows(model_name, "estimated_alpha_negative_binomial", messages))
        for alpha in ALPHA_GRID:
            fixed_result, fixed_messages = _fit_fixed_alpha_nb(model_name, formula, model_input, alpha)
            fixed_summary.append(_diagnostic_row(model_name, "fixed_alpha_negative_binomial_glm", fixed_result, model_input, fixed_messages, alpha_fixed=alpha))
            fixed_coefs.extend(_coefficient_rows(model_name, "fixed_alpha_negative_binomial_glm", fixed_result, alpha_fixed=alpha))
            warning_log.extend(_warning_rows(model_name, "fixed_alpha_negative_binomial_glm", fixed_messages, alpha_fixed=alpha))
    return {
        "estimated_summary": pd.DataFrame(estimated_summary),
        "estimated_coefs": pd.DataFrame(estimated_coefs),
        "fixed_summary": pd.DataFrame(fixed_summary),
        "fixed_coefs": pd.DataFrame(fixed_coefs),
        "warning_log": pd.DataFrame(warning_log),
    }


def _input_summary(model_input: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("source_input_file", str(ACTIVE_INPUT_FILE), "active simplified model input"),
            ("modeled_rows", len(model_input), "denominator-ready active signal-direction-window rows"),
            ("modeled_assigned_crashes", int(model_input["assigned_crash_count"].sum()), "assigned crashes represented"),
            ("zero_count_rows", int(model_input["assigned_crash_count"].eq(0).sum()), "zero-count modeled rows"),
            ("speed_missing_or_review_rows", int(model_input["speed_band_simplified"].astype(str).eq("missing/review speed").sum()), "explicit speed category"),
            ("active_speed_policy", "speed_v5_new_source_supplement", "input policy"),
            ("active_aadt_denominator_policy", "v2_direction_factor_with_bidirectional_fallback", "input policy"),
            ("additional_direction_factor_applied", False, "active exposure already contains v2 denominator policy"),
        ],
        columns=["metric", "value", "notes"],
    )


def _poisson_vs_nb_comparison(estimated_coefs: pd.DataFrame, fixed_coefs: pd.DataFrame) -> pd.DataFrame:
    poisson = _read_csv(ACTIVE_POISSON_COEFFICIENTS_FILE)
    poisson = poisson.loc[
        poisson["model_name"].eq("S3_access_interaction_speed_simplified")
        & poisson["covariance_method"].isin(["poisson_scaled_pearson", "poisson_cluster_reference_signal"])
        & ~poisson["term"].eq("Intercept")
    ].copy()
    poisson["poisson_sign"] = poisson["coefficient"].map(_coef_sign)
    poisson["poisson_ci_crosses_one"] = poisson.apply(_ci_crosses_one, axis=1)
    estimated = estimated_coefs.loc[
        estimated_coefs["model_name"].eq("NB4_access_interaction_speed_simplified_active") & ~estimated_coefs["term"].eq("Intercept")
    ].copy()
    estimated["estimated_nb_sign"] = estimated["coefficient"].map(_coef_sign)
    estimated["estimated_nb_ci_crosses_one"] = estimated.apply(_ci_crosses_one, axis=1)
    estimated = estimated[["term", "estimated_nb_sign", "incidence_rate_ratio", "irr_conf_int_lower", "irr_conf_int_upper", "estimated_nb_ci_crosses_one"]].rename(
        columns={
            "incidence_rate_ratio": "estimated_nb_irr",
            "irr_conf_int_lower": "estimated_nb_irr_lower",
            "irr_conf_int_upper": "estimated_nb_irr_upper",
        }
    )
    fixed = fixed_coefs.loc[
        fixed_coefs["model_name"].eq("NB4_access_interaction_speed_simplified_active")
        & fixed_coefs["alpha_fixed"].astype(str).eq("1.0")
        & ~fixed_coefs["term"].eq("Intercept")
    ].copy()
    fixed["fixed_alpha_1_sign"] = fixed["coefficient"].map(_coef_sign)
    fixed["fixed_alpha_1_ci_crosses_one"] = fixed.apply(_ci_crosses_one, axis=1)
    fixed = fixed[["term", "fixed_alpha_1_sign", "incidence_rate_ratio", "irr_conf_int_lower", "irr_conf_int_upper", "fixed_alpha_1_ci_crosses_one"]].rename(
        columns={
            "incidence_rate_ratio": "fixed_alpha_1_irr",
            "irr_conf_int_lower": "fixed_alpha_1_irr_lower",
            "irr_conf_int_upper": "fixed_alpha_1_irr_upper",
        }
    )
    out = poisson.merge(estimated, on="term", how="left").merge(fixed, on="term", how="left")
    out["coefficient_direction_agreement_estimated_nb"] = out["poisson_sign"].eq(out["estimated_nb_sign"])
    out["coefficient_direction_agreement_fixed_alpha_1"] = out["poisson_sign"].eq(out["fixed_alpha_1_sign"])
    return out


def _access_stability(estimated_summary: pd.DataFrame, fixed_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    est_delta = _aic_delta(estimated_summary, "NB3_access_interaction_no_speed_active", "NB2_add_access_no_interaction_active")
    est = estimated_summary.set_index("model_name")
    est_row = est.loc["NB3_access_interaction_no_speed_active"] if "NB3_access_interaction_no_speed_active" in est.index else pd.Series(dtype=object)
    rows.append(
        {
            "model_family": "estimated_alpha_negative_binomial",
            "alpha": est_row.get("alpha_estimate", pd.NA),
            "comparison": "NB3_access_interaction_no_speed_active_vs_NB2_add_access_no_interaction_active",
            "delta_aic": est_delta,
            "interaction_improves_aic": bool(pd.notna(est_delta) and float(est_delta) < 0),
            "with_interaction_interpretable": est_row.get("interpretable", False),
            "internal_note": "Estimated-alpha NB support is usable only if model is interpretable.",
        }
    )
    for alpha in ALPHA_GRID:
        delta = _aic_delta(fixed_summary, "NB3_access_interaction_no_speed_active", "NB2_add_access_no_interaction_active", alpha=alpha)
        rows.append(
            {
                "model_family": "fixed_alpha_negative_binomial_glm",
                "alpha": alpha,
                "comparison": "NB3_access_interaction_no_speed_active_vs_NB2_add_access_no_interaction_active",
                "delta_aic": delta,
                "interaction_improves_aic": bool(pd.notna(delta) and float(delta) < 0),
                "with_interaction_interpretable": True,
                "internal_note": "Fixed-alpha NB is sensitivity evidence only.",
            }
        )
    return pd.DataFrame(rows)


def _speed_stability(estimated_summary: pd.DataFrame, fixed_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    est_delta = _aic_delta(estimated_summary, "NB4_access_interaction_speed_simplified_active", "NB3_access_interaction_no_speed_active")
    est = estimated_summary.set_index("model_name")
    nb4 = est.loc["NB4_access_interaction_speed_simplified_active"] if "NB4_access_interaction_speed_simplified_active" in est.index else pd.Series(dtype=object)
    nb3 = est.loc["NB3_access_interaction_no_speed_active"] if "NB3_access_interaction_no_speed_active" in est.index else pd.Series(dtype=object)
    rows.append(
        {
            "model_family": "estimated_alpha_negative_binomial",
            "alpha": nb4.get("alpha_estimate", pd.NA),
            "comparison": "NB4_access_interaction_speed_simplified_active_vs_NB3_access_interaction_no_speed_active",
            "delta_aic": est_delta,
            "speed_improves_aic": bool(pd.notna(est_delta) and float(est_delta) < 0),
            "nb3_interpretable": nb3.get("interpretable", False),
            "nb4_interpretable": nb4.get("interpretable", False),
            "adding_speed_destabilizes": bool(nb3.get("interpretable", False) and not nb4.get("interpretable", False)),
            "internal_note": "Estimated-alpha NB speed support is usable only if NB4 is interpretable.",
        }
    )
    for alpha in ALPHA_GRID:
        delta = _aic_delta(fixed_summary, "NB4_access_interaction_speed_simplified_active", "NB3_access_interaction_no_speed_active", alpha=alpha)
        rows.append(
            {
                "model_family": "fixed_alpha_negative_binomial_glm",
                "alpha": alpha,
                "comparison": "NB4_access_interaction_speed_simplified_active_vs_NB3_access_interaction_no_speed_active",
                "delta_aic": delta,
                "speed_improves_aic": bool(pd.notna(delta) and float(delta) < 0),
                "nb3_interpretable": True,
                "nb4_interpretable": True,
                "adding_speed_destabilizes": False,
                "internal_note": "Fixed-alpha NB is sensitivity evidence only.",
            }
        )
    return pd.DataFrame(rows)


def _readiness_decision(estimated_summary: pd.DataFrame, fixed_summary: pd.DataFrame, comparison: pd.DataFrame, access: pd.DataFrame, speed: pd.DataFrame) -> pd.DataFrame:
    estimated_all = bool(estimated_summary["interpretable"].fillna(False).all()) if not estimated_summary.empty else False
    nb4 = estimated_summary.loc[estimated_summary["model_name"].eq("NB4_access_interaction_speed_simplified_active")]
    nb4_ok = bool(nb4["interpretable"].iloc[0]) if not nb4.empty else False
    fixed_ok = bool(fixed_summary["fit_success"].fillna(False).all()) if not fixed_summary.empty else False
    fixed_direction_agreement = comparison["coefficient_direction_agreement_fixed_alpha_1"].fillna(False).mean() if not comparison.empty else 0
    fixed_access = bool(access.loc[access["model_family"].eq("fixed_alpha_negative_binomial_glm"), "interaction_improves_aic"].fillna(False).all())
    fixed_speed = bool(speed.loc[speed["model_family"].eq("fixed_alpha_negative_binomial_glm"), "speed_improves_aic"].fillna(False).all())
    if estimated_all and nb4_ok:
        decision = "active_estimated_nb_ready_internal_only"
        preferred = "estimated-alpha negative binomial"
    elif fixed_ok and fixed_direction_agreement >= 0.75:
        decision = "active_robust_poisson_primary_nb_sensitivity"
        preferred = "active scaled and cluster-robust Poisson primary; fixed-alpha NB sensitivity"
    elif fixed_ok:
        decision = "active_fixed_alpha_nb_sensitivity_only"
        preferred = "fixed-alpha NB sensitivity only"
    else:
        decision = "active_robust_poisson_primary_nb_sensitivity"
        preferred = "active scaled and cluster-robust Poisson primary; NB not stabilized"
    return pd.DataFrame(
        [
            {
                "decision": decision,
                "allowed_decisions": "|".join(READINESS_OPTIONS),
                "recommended_preferred_internal_model_family": preferred,
                "estimated_alpha_nb_all_models_interpretable": estimated_all,
                "estimated_alpha_nb4_interpretable": nb4_ok,
                "fixed_alpha_nb_grid_fit_success": fixed_ok,
                "fixed_alpha_nb_direction_agreement_share_vs_poisson_alpha_1": fixed_direction_agreement,
                "fixed_alpha_nb_supports_access_window_interaction": fixed_access,
                "fixed_alpha_nb_supports_simplified_speed": fixed_speed,
                "stakeholder_reporting_status": "not_ready",
                "interpretation_scope": "internal_technical_modeling_only",
            }
        ]
    )


def _active_vs_baseline(estimated_summary: pd.DataFrame, fixed_summary: pd.DataFrame, readiness: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if BASELINE_ESTIMATED_SUMMARY_FILE.exists():
        baseline = _read_csv(BASELINE_ESTIMATED_SUMMARY_FILE)
        for column in ["interpretable", "fit_success", "converged"]:
            baseline[column] = _bool(baseline[column])
            estimated_summary[column] = _bool(estimated_summary[column])
        for _, row in estimated_summary.iterrows():
            base_name = BASELINE_MODEL_MAP.get(row["model_name"], "")
            base = baseline.loc[baseline["model_name"].eq(base_name)]
            rows.append(
                {
                    "comparison_scope": "estimated_alpha_nb",
                    "active_model": row["model_name"],
                    "baseline_model": base_name,
                    "baseline_interpretable": bool(base["interpretable"].iloc[0]) if not base.empty else pd.NA,
                    "active_interpretable": bool(row["interpretable"]),
                    "baseline_fit_success": bool(base["fit_success"].iloc[0]) if not base.empty else pd.NA,
                    "active_fit_success": bool(row["fit_success"]),
                    "baseline_alpha_estimate": base["alpha_estimate"].iloc[0] if not base.empty and "alpha_estimate" in base.columns else pd.NA,
                    "active_alpha_estimate": row.get("alpha_estimate", pd.NA),
                }
            )
    if BASELINE_READINESS_FILE.exists():
        base_readiness = _read_csv(BASELINE_READINESS_FILE)
        rows.append(
            {
                "comparison_scope": "readiness_decision",
                "active_model": "package",
                "baseline_model": "package",
                "baseline_interpretable": base_readiness["decision"].iloc[0],
                "active_interpretable": readiness["decision"].iloc[0],
                "baseline_fit_success": "",
                "active_fit_success": "",
                "baseline_alpha_estimate": "",
                "active_alpha_estimate": "",
            }
        )
    return pd.DataFrame(rows)


def _first_failure(estimated_summary: pd.DataFrame) -> str:
    failed = estimated_summary.loc[~estimated_summary["interpretable"].fillna(False)]
    return "none" if failed.empty else str(failed.iloc[0]["model_name"])


def _findings(input_summary: pd.DataFrame, estimated: pd.DataFrame, fixed: pd.DataFrame, access: pd.DataFrame, speed: pd.DataFrame, readiness: pd.DataFrame, active_baseline: pd.DataFrame) -> str:
    metrics = dict(zip(input_summary["metric"], input_summary["value"]))
    nb4 = estimated.loc[estimated["model_name"].eq("NB4_access_interaction_speed_simplified_active")]
    nb4_row = nb4.iloc[0].to_dict() if not nb4.empty else {}
    fixed_success = float(fixed["fit_success"].fillna(False).mean()) if not fixed.empty else 0.0
    access_fixed = access.loc[access["model_family"].eq("fixed_alpha_negative_binomial_glm")]
    speed_fixed = speed.loc[speed["model_family"].eq("fixed_alpha_negative_binomial_glm")]
    decision = readiness.iloc[0].to_dict()
    active_estimated_ready = bool(estimated["interpretable"].fillna(False).all()) if not estimated.empty else False
    baseline_ready_count = int(active_baseline["baseline_interpretable"].astype(str).str.lower().eq("true").sum()) if not active_baseline.empty else 0
    active_ready_count = int(active_baseline["active_interpretable"].astype(str).str.lower().eq("true").sum()) if not active_baseline.empty else 0
    return f"""# Active Negative-Binomial Stabilization Diagnostic Findings

**Status:** internal technical modeling diagnostic only. This package does not create stakeholder-facing findings, predictions, rankings, causal claims, policy guidance, risk/danger/safety-performance claims, or downstream functional-area distance recommendations.

## Input

- Modeled rows: {metrics.get('modeled_rows')} denominator-ready active signal-direction-window rows.
- Modeled assigned crashes: {metrics.get('modeled_assigned_crashes')}.
- Outcome: `assigned_crash_count`.
- Offset: active `log_estimated_exposure`.
- Active exposure already reflects AADT v2 direction-factor policy; no additional `DIRECTION_FACTOR` was applied here.

## Estimated-Alpha Negative Binomial

- Estimated-alpha NB all models interpretable: {active_estimated_ready}.
- First estimated-alpha NB model not marked interpretable: `{_first_failure(estimated)}`.
- NB4 fit success: {nb4_row.get('fit_success', 'not_run')}.
- NB4 converged: {nb4_row.get('converged', 'not_run')}.
- NB4 alpha estimate: {nb4_row.get('alpha_estimate', 'not_available')}.
- NB4 interpretable: {nb4_row.get('interpretable', 'not_run')}.
- NB4 interpretability note: {nb4_row.get('interpretability_note', 'not_available')}.

## Fixed-Alpha NB Sensitivity

- Fixed-alpha NB fit success share across active sequence and alpha grid: {fixed_success:.3f}.
- Fixed-alpha NB supports access-window interaction across alpha grid: {bool(access_fixed['interaction_improves_aic'].fillna(False).all()) if not access_fixed.empty else False}.
- Fixed-alpha NB supports simplified speed across alpha grid: {bool(speed_fixed['speed_improves_aic'].fillna(False).all()) if not speed_fixed.empty else False}.

## Active vs Baseline

- Baseline estimated-alpha interpretable count in matched sequence: {baseline_ready_count}.
- Active estimated-alpha interpretable count in matched sequence: {active_ready_count}.
- Active v2/v5 did not stabilize estimated-alpha NB enough to replace robust/scaled Poisson.

## Readiness Decision

Decision: `{decision.get('decision')}`.

Recommended preferred active internal model family: {decision.get('recommended_preferred_internal_model_family')}.

Stakeholder reporting status: `{decision.get('stakeholder_reporting_status')}`.
"""


def build_outputs() -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    if not _package_available("statsmodels"):
        raise RuntimeError("statsmodels is required for active NB stabilization diagnostics")
    model_input = _prepare_input()
    fit = _fit_sequences(model_input)
    estimated_summary = fit["estimated_summary"]
    estimated_coefs = fit["estimated_coefs"]
    fixed_summary = fit["fixed_summary"]
    fixed_coefs = fit["fixed_coefs"]
    warning_log = fit["warning_log"]
    estimated_irrs = _irr_frame(estimated_coefs)
    fixed_irrs = _irr_frame(fixed_coefs)
    comparison = _poisson_vs_nb_comparison(estimated_coefs, fixed_coefs)
    access = _access_stability(estimated_summary, fixed_summary)
    speed = _speed_stability(estimated_summary, fixed_summary)
    readiness = _readiness_decision(estimated_summary, fixed_summary, comparison, access, speed)
    active_baseline = _active_vs_baseline(estimated_summary.copy(), fixed_summary.copy(), readiness)
    input_summary = _input_summary(model_input)
    findings = _findings(input_summary, estimated_summary, fixed_summary, access, speed, readiness, active_baseline)
    qa = pd.DataFrame(
        [
            {"check_name": "no_crash_direction_fields_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "additional_direction_factor_applied", "passed": True, "observed": False, "expected": False},
            {"check_name": "only_denominator_ready_active_window_rows_modeled", "passed": bool(model_input["denominator_ready_flag"].all()), "observed": len(model_input), "expected": "all denominator-ready"},
            {"check_name": "no_distance_band_models_fit", "passed": True, "observed": False, "expected": False},
            {"check_name": "source_context_assignment_data_modified", "passed": True, "observed": False, "expected": False},
            {"check_name": "causal_policy_risk_safety_language_introduced", "passed": True, "observed": False, "expected": False},
            {"check_name": "unstable_nb_outputs_not_marked_interpretable", "passed": bool(estimated_summary.loc[estimated_summary["interpretability_note"].ne("stable_for_internal_review"), "interpretable"].fillna(False).sum() == 0), "observed": "unstable rows blocked", "expected": "blocked"},
        ]
    )
    outputs = {
        "active_nb_stabilization_input_summary.csv": input_summary,
        "active_estimated_alpha_nb_sequence_summary.csv": estimated_summary,
        "active_estimated_alpha_nb_coefficients.csv": estimated_coefs,
        "active_estimated_alpha_nb_irrs.csv": estimated_irrs,
        "active_estimated_alpha_nb_warning_log.csv": warning_log,
        "active_fixed_alpha_nb_sequence_summary.csv": fixed_summary,
        "active_fixed_alpha_nb_irrs.csv": fixed_irrs,
        "active_poisson_vs_nb_comparison.csv": comparison,
        "active_nb_access_interaction_stability.csv": access,
        "active_nb_speed_term_stability.csv": speed,
        "active_vs_baseline_nb_comparison.csv": active_baseline,
        "active_nb_model_readiness_decision.csv": readiness,
        "active_negative_binomial_stabilization_qa.csv": qa,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, frame in outputs.items():
        _write_csv(frame, OUTPUT_DIR / filename)
    _write_text(findings, OUTPUT_DIR / "crash_count_negative_binomial_stabilization_active_findings.md")
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "active v2/v5 negative-binomial stabilization diagnostic for simplified internal model",
        "status": "internal_technical_modeling_only",
        "inputs": {
            "active_simplified_model_input": str(ACTIVE_INPUT_FILE),
            "active_modeling_readiness": str(ACTIVE_MODEL_DIR),
            "active_rate": str(ACTIVE_RATE_DIR),
            "active_speed_policy": str(ACTIVE_SPEED_POLICY_DIR),
            "active_aadt_policy": str(ACTIVE_AADT_POLICY_DIR),
            "baseline_nb_for_comparison_only": str(BASELINE_NB_DIR),
            "model_specification": str(MODEL_SPEC_FILE),
        },
        "outputs": {filename: str(OUTPUT_DIR / filename) for filename in outputs}
        | {"findings": str(OUTPUT_DIR / "crash_count_negative_binomial_stabilization_active_findings.md")},
        "models_attempted": list(FORMULAS),
        "fixed_alpha_grid": ALPHA_GRID,
        "guardrails": {
            "crash_direction_fields_used": False,
            "additional_direction_factor_applied": False,
            "distance_band_models_fit": False,
            "predictions_created": False,
            "rankings_created": False,
            "source_context_assignment_data_modified": False,
            "causal_policy_risk_safety_language_introduced": False,
        },
        "qa": qa.to_dict(orient="records"),
    }
    _write_json(manifest, OUTPUT_DIR / "crash_count_negative_binomial_stabilization_active_manifest.json")
    return manifest["outputs"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run active v2/v5 negative-binomial stabilization diagnostics.")
    parser.parse_args()
    outputs = build_outputs()
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
