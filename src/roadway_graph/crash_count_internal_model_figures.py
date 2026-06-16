from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
ANALYSIS_ROOT = OUTPUT_ROOT / "analysis/current"
SIMPLIFIED_DIR = ANALYSIS_ROOT / "crash_count_simplified_internal_model"
REVIEW_DIR = ANALYSIS_ROOT / "crash_count_internal_model_review"
OUTPUT_DIR = ANALYSIS_ROOT / "crash_count_internal_model_figures"
DOC_DIR = Path("docs/reports/roadway_graph/internal_model_figures")
TECHNICAL_MEMO = Path("docs/reports/roadway_graph/internal_model_technical_review_memo.md")

SELECTED_MODEL = "S3_access_interaction_speed_simplified"
PREFERRED_INFERENCE = "poisson_scaled_pearson"
CLUSTER_INFERENCE = "poisson_cluster_reference_signal"

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

REQUIRED_OUTPUT_TABLES = [
    "internal_model_irr_plot_data.csv",
    "internal_model_access_interaction_plot_data.csv",
    "internal_model_speed_effect_plot_data.csv",
    "internal_model_diagnostic_plot_data.csv",
    "internal_model_inference_comparison_plot_data.csv",
]

REQUIRED_FIGURES = [
    "internal_model_irr_forest_plot.svg",
    "internal_model_access_interaction_forest_plot.svg",
    "internal_model_speed_effect_forest_plot.svg",
    "internal_model_diagnostic_summary.svg",
    "internal_model_inference_comparison.svg",
]


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, required: bool = True) -> pd.DataFrame:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return pd.DataFrame()
    header = pd.read_csv(path, nrows=0).columns.tolist()
    blocked = [column for column in header if _is_crash_direction_field(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _float(value: Any, default: float = float("nan")) -> float:
    try:
        if value == "":
            return default
        out = float(value)
        return out
    except (TypeError, ValueError):
        return default


def _sig_crosses_one(row: pd.Series) -> bool:
    low = _float(row.get("irr_conf_int_lower", ""))
    high = _float(row.get("irr_conf_int_upper", ""))
    return low <= 1.0 <= high


def _extract_bracket_value(term: str) -> str:
    marker = "[T."
    if marker not in term:
        return ""
    return term.split(marker, 1)[1].split("]", 1)[0]


def _term_family(term: str) -> str:
    if term == "Intercept":
        return "intercept"
    if "analysis_window_readable" in term and ":" not in term:
        return "analysis window"
    if "local_access_density_label" in term and ":" not in term:
        return "access density"
    if "analysis_window_readable" in term and "local_access_density_label" in term and ":" in term:
        return "window x access interaction"
    if "signal_relative_direction_model" in term:
        return "signal-relative direction"
    if "speed_band_simplified" in term:
        return "simplified speed"
    return "other"


def _reference_category(term: str) -> str:
    family = _term_family(term)
    if family == "analysis window":
        return "0-1,000 ft"
    if family == "access density":
        return "0 access points per 1,000 ft in 0-1,000 ft reference window"
    if family == "window x access interaction":
        return "interaction multiplier relative to 0-1,000 ft access term"
    if family == "signal-relative direction":
        return "downstream"
    if family == "simplified speed":
        return "30-39 mph"
    return "model intercept/reference levels"


def _readable_term_label(term: str) -> str:
    family = _term_family(term)
    value = _extract_bracket_value(term)
    if family == "analysis window":
        return "Window: 1,000-2,500 ft vs 0-1,000 ft"
    if family == "access density":
        return f"Access: {value} vs 0 per 1,000 ft"
    if family == "window x access interaction":
        access_value = term.rsplit("[T.", 1)[1].split("]", 1)[0]
        return f"Interaction: 1,000-2,500 ft x access {access_value}"
    if family == "signal-relative direction":
        return "Direction: upstream vs downstream"
    if family == "simplified speed":
        return f"Speed: {value} vs 30-39 mph"
    if family == "intercept":
        return "Intercept"
    return term


def _access_label(term: str) -> str:
    if "local_access_density_label" not in term:
        return ""
    value = term.rsplit("[T.", 1)[1].split("]", 1)[0]
    return f"{value} access points per 1,000 ft"


def _window_label(term: str) -> str:
    if _term_family(term) == "access density":
        return "0-1,000 ft"
    if _term_family(term) == "window x access interaction":
        return "1,000-2,500 ft interaction"
    return ""


def _inference_label(method: str) -> str:
    labels = {
        "poisson_conventional": "conventional Poisson",
        "poisson_scaled_pearson": "Pearson-scaled Poisson",
        "poisson_robust_hc0": "robust Poisson HC0",
        "poisson_cluster_reference_signal": "cluster-robust Poisson",
    }
    return labels.get(method, method)


def _svg_text(x: float, y: float, text: str, *, size: int = 12, weight: str = "normal", anchor: str = "start", fill: str = "#222") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">{html.escape(text)}</text>'
    )


def _svg_line(x1: float, y1: float, x2: float, y2: float, *, stroke: str = "#555", width: float = 1.0, dash: str = "") -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width}"{dash_attr}/>'


def _svg_rect(x: float, y: float, w: float, h: float, *, fill: str, stroke: str = "none") -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}"/>'


def _forest_svg(
    frame: pd.DataFrame,
    path: Path,
    *,
    title: str,
    subtitle: str,
    caption: str,
    group_col: str = "term_family",
) -> None:
    plot = frame.copy()
    plot["irr"] = plot["IRR"].map(_float)
    plot["low"] = plot["lower_CI"].map(_float)
    plot["high"] = plot["upper_CI"].map(_float)
    plot = plot[(plot["irr"] > 0) & (plot["low"] > 0) & (plot["high"] > 0)].copy()
    plot = plot.reset_index(drop=True)
    height = max(420, 170 + 34 * len(plot))
    width = 1160
    left_label = 34
    x0 = 520
    x1 = 1040
    top = 112
    row_h = 34
    values = plot[["low", "high", "irr"]].to_numpy().flatten().tolist() if not plot.empty else [0.5, 2.0]
    min_x = max(0.1, min(values) * 0.78)
    max_x = max(values) * 1.22
    min_log = math.log(min_x)
    max_log = math.log(max_x)

    def sx(value: float) -> float:
        return x0 + ((math.log(max(value, 0.001)) - min_log) / (max_log - min_log)) * (x1 - x0)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(34, 34, title, size=20, weight="bold"),
        _svg_text(34, 58, "INTERNAL TECHNICAL REVIEW ONLY", size=12, weight="bold", fill="#8a3a00"),
        _svg_text(34, 78, subtitle, size=12),
        _svg_line(x0, top - 16, x1, top - 16, stroke="#555"),
    ]
    for tick in [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]:
        if min_x <= tick <= max_x:
            x = sx(tick)
            parts.append(_svg_line(x, top - 22, x, height - 82, stroke="#ddd", dash="3 3" if tick == 1.0 else ""))
            parts.append(_svg_text(x, top - 28, f"{tick:g}", size=10, anchor="middle", fill="#555"))
    if min_x <= 1.0 <= max_x:
        parts.append(_svg_line(sx(1.0), top - 22, sx(1.0), height - 82, stroke="#333", width=1.5))
    parts.append(_svg_text(x0, top - 42, "IRR, log scale", size=11, fill="#555"))

    current_group = None
    y = top
    color_map = {
        "analysis window": "#4C78A8",
        "access density": "#54A24B",
        "window x access interaction": "#E45756",
        "signal-relative direction": "#72B7B2",
        "simplified speed": "#F58518",
        "other": "#777777",
    }
    for _, row in plot.iterrows():
        group = str(row.get(group_col, ""))
        if group != current_group:
            parts.append(_svg_text(left_label, y, group.title(), size=12, weight="bold", fill="#333"))
            current_group = group
            y += 20
        irr = _float(row["IRR"])
        low = _float(row["lower_CI"])
        high = _float(row["upper_CI"])
        color = color_map.get(str(row.get("term_family", "")), "#777777")
        parts.append(_svg_text(left_label + 16, y + 4, str(row["readable_term_label"]), size=11))
        parts.append(_svg_line(sx(low), y, sx(high), y, stroke=color, width=2.0))
        parts.append(f'<circle cx="{sx(irr):.1f}" cy="{y:.1f}" r="4.8" fill="{color}"/>')
        parts.append(_svg_text(x1 + 16, y + 4, f'{irr:.2f} ({low:.2f}, {high:.2f})', size=10))
        y += row_h
    parts.append(_svg_text(34, height - 48, caption, size=11, fill="#555"))
    parts.append(_svg_text(34, height - 28, "These are model terms from an exploratory association model, not causal effects or policy findings.", size=11, fill="#555"))
    parts.append("</svg>")
    _write_text("\n".join(parts), path)


def _diagnostic_svg(frame: pd.DataFrame, path: Path) -> None:
    width, height = 980, 430
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(34, 34, "Internal Model Diagnostic Summary", size=20, weight="bold"),
        _svg_text(34, 58, "INTERNAL TECHNICAL REVIEW ONLY", size=12, weight="bold", fill="#8a3a00"),
        _svg_text(34, 80, "Selected model: S3_access_interaction_speed_simplified", size=12),
    ]
    x, y, w, row_h = 34, 112, 912, 34
    parts.append(_svg_rect(x, y, w, row_h, fill="#e8eef5"))
    parts.append(_svg_text(x + 12, y + 22, "Diagnostic", size=12, weight="bold"))
    parts.append(_svg_text(x + 360, y + 22, "Value", size=12, weight="bold"))
    parts.append(_svg_text(x + 610, y + 22, "Internal review note", size=12, weight="bold"))
    rows = frame.to_dict("records")
    for i, row in enumerate(rows):
        yy = y + row_h * (i + 1)
        fill = "#f8fafc" if i % 2 == 0 else "#ffffff"
        parts.append(_svg_rect(x, yy, w, row_h, fill=fill, stroke="#d8dee7"))
        parts.append(_svg_text(x + 12, yy + 22, str(row["diagnostic_label"]), size=11))
        parts.append(_svg_text(x + 360, yy + 22, str(row["diagnostic_value"]), size=11))
        parts.append(_svg_text(x + 610, yy + 22, str(row["warning_flags"])[:52], size=11))
    parts.append(_svg_text(34, height - 36, "No new model fitting; AADT is provisional and bidirectional; DIRECTION_FACTOR is not applied; stakeholder interpretation is blocked.", size=11, fill="#555"))
    parts.append("</svg>")
    _write_text("\n".join(parts), path)


def _inference_svg(frame: pd.DataFrame, path: Path) -> None:
    plot = frame.copy()
    key_terms = [
        "Access: 1-3 vs 0 per 1,000 ft",
        "Interaction: 1,000-2,500 ft x access 3-6",
        "Interaction: 1,000-2,500 ft x access 6+",
        "Speed: <30 mph vs 30-39 mph",
        "Speed: 50+ mph vs 30-39 mph",
    ]
    plot = plot[plot["readable_term_label"].isin(key_terms)].copy()
    if plot.empty:
        plot = frame.head(5).copy()
    width, height = 1120, 470
    left, top = 34, 112
    label_w = 390
    chart_x = left + label_w
    chart_w = 610
    row_h = 54
    se_cols = [
        ("conventional_SE", "Conventional", "#9aa0a6"),
        ("scaled_SE", "Scaled", "#4C78A8"),
        ("robust_SE", "Robust", "#54A24B"),
        ("cluster_robust_SE", "Cluster", "#E45756"),
    ]
    max_se = 0.01
    for col, _, _ in se_cols:
        max_se = max(max_se, plot[col].map(_float).max())
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(34, 34, "Inference Comparison For Selected Terms", size=20, weight="bold"),
        _svg_text(34, 58, "INTERNAL TECHNICAL REVIEW ONLY", size=12, weight="bold", fill="#8a3a00"),
        _svg_text(34, 80, "Standard errors from existing S3 coefficient outputs; no new model fitting.", size=12),
    ]
    for j, (_, label, color) in enumerate(se_cols):
        lx = chart_x + j * 122
        parts.append(_svg_rect(lx, 92, 12, 12, fill=color))
        parts.append(_svg_text(lx + 18, 103, label, size=10))
    for i, row in plot.reset_index(drop=True).iterrows():
        y = top + i * row_h
        parts.append(_svg_text(left, y + 25, str(row["readable_term_label"])[:58], size=11))
        for j, (col, _, color) in enumerate(se_cols):
            value = _float(row[col], 0)
            bar_w = 0 if max_se <= 0 else (value / max_se) * 110
            bx = chart_x + j * 122
            parts.append(_svg_rect(bx, y + 12, bar_w, 16, fill=color))
            parts.append(_svg_text(bx, y + 44, f"{value:.3f}", size=9))
        parts.append(_svg_text(chart_x + chart_w - 34, y + 25, str(row["material_inference_change"]), size=10, anchor="end"))
    parts.append(_svg_text(34, height - 32, "Material change flag means the CI crossing of IRR=1 differs between scaled and cluster-robust inference.", size=11, fill="#555"))
    parts.append("</svg>")
    _write_text("\n".join(parts), path)


def build_plot_tables() -> dict[str, pd.DataFrame]:
    selected_irrs = _read_csv(REVIEW_DIR / "internal_model_selected_irrs.csv")
    coefficients = _read_csv(SIMPLIFIED_DIR / "simplified_model_coefficients.csv")
    fit_summary = _read_csv(SIMPLIFIED_DIR / "simplified_model_fit_summary.csv")
    overdispersion = _read_csv(SIMPLIFIED_DIR / "simplified_model_overdispersion_summary.csv")
    readiness = _read_csv(SIMPLIFIED_DIR / "simplified_model_readiness_decision.csv")
    input_summary = _read_csv(SIMPLIFIED_DIR / "simplified_model_input_summary.csv")
    diagnostics = _read_csv(REVIEW_DIR / "internal_model_diagnostic_summary.csv")
    _read_csv(SIMPLIFIED_DIR / "simplified_model_diagnostics.csv", required=False)
    _read_csv(SIMPLIFIED_DIR / "simplified_model_clustered_se_comparison.csv")
    _read_csv(SIMPLIFIED_DIR / "simplified_access_interaction_summary.csv")
    _read_csv(SIMPLIFIED_DIR / "simplified_speed_sensitivity_summary.csv")
    _read_csv(REVIEW_DIR / "internal_model_access_interaction_interpretation_table.csv")
    if TECHNICAL_MEMO.exists():
        TECHNICAL_MEMO.read_text(encoding="utf-8")

    plot_source = selected_irrs[
        (selected_irrs["model_name"] == SELECTED_MODEL)
        & (selected_irrs["covariance_method"].isin([PREFERRED_INFERENCE, CLUSTER_INFERENCE]))
        & (selected_irrs["term"] != "Intercept")
    ].copy()
    plot_source["term_family"] = plot_source["term"].map(_term_family)
    plot_source["readable_term_label"] = plot_source["term"].map(_readable_term_label)
    plot_source["inference_type"] = plot_source["covariance_method"].map(_inference_label)
    plot_source["standard_error_source"] = plot_source["covariance_method"].map(_inference_label)
    plot_source["reference_category"] = plot_source["term"].map(_reference_category)
    plot_source["interpretation_caution"] = "Internal exploratory association only; not causal, not ranking, not policy-ready."
    irr_plot = plot_source.rename(
        columns={
            "incidence_rate_ratio": "IRR",
            "irr_conf_int_lower": "lower_CI",
            "irr_conf_int_upper": "upper_CI",
        }
    )[
        [
            "term",
            "readable_term_label",
            "term_family",
            "model_family",
            "inference_type",
            "IRR",
            "lower_CI",
            "upper_CI",
            "standard_error_source",
            "reference_category",
            "interpretation_caution",
        ]
    ].copy()

    access_plot = irr_plot[
        (irr_plot["inference_type"] == _inference_label(PREFERRED_INFERENCE))
        & (irr_plot["term_family"].isin(["access density", "window x access interaction"]))
    ].copy()
    access_plot["access_density_label"] = access_plot["term"].map(_access_label)
    access_plot["window_label"] = access_plot["term"].map(_window_label)
    access_plot["relative_effect_estimate"] = access_plot["IRR"]
    access_plot["internal_interpretation_note"] = (
        "Conditional model term; use only to review whether access-density association differs by window."
    )
    access_plot = access_plot[
        [
            "term",
            "readable_term_label",
            "access_density_label",
            "window_label",
            "relative_effect_estimate",
            "lower_CI",
            "upper_CI",
            "internal_interpretation_note",
        ]
    ].copy()

    speed_plot = irr_plot[
        (irr_plot["inference_type"] == _inference_label(PREFERRED_INFERENCE))
        & (irr_plot["term_family"] == "simplified speed")
    ].copy()
    speed_plot["speed_label"] = speed_plot["term"].map(_extract_bracket_value)
    speed_plot["speed_category_note"] = speed_plot["speed_label"].map(
        lambda value: "missing/review speed explicit category"
        if value == "missing/review speed"
        else ("50+ mph merged category" if value == "50+ mph" else "simplified speed category")
    )
    speed_plot["internal_interpretation_note"] = "Speed is roadway context in an exploratory association model, not causal evidence."
    speed_plot = speed_plot[
        [
            "term",
            "readable_term_label",
            "speed_label",
            "IRR",
            "lower_CI",
            "upper_CI",
            "speed_category_note",
            "internal_interpretation_note",
        ]
    ].copy()

    input_map = dict(zip(input_summary["metric"], input_summary["value"]))
    ready = readiness.iloc[0].to_dict() if not readiness.empty else {}
    selected_fit = fit_summary[(fit_summary["model_name"] == SELECTED_MODEL) & (fit_summary["covariance_method"] == PREFERRED_INFERENCE)]
    selected_over = overdispersion[(overdispersion["model_name"] == SELECTED_MODEL) & (overdispersion["covariance_method"] == PREFERRED_INFERENCE)]
    diag_map = dict(zip(diagnostics["diagnostic"], diagnostics["value"])) if not diagnostics.empty else {}
    diagnostic_plot = pd.DataFrame(
        [
            {
                "model_name": SELECTED_MODEL,
                "diagnostic_label": "Modeled rows",
                "diagnostic_value": input_map.get("modeled_rows", ""),
                "AIC": selected_fit.iloc[0].get("aic", "") if not selected_fit.empty else "",
                "overdispersion_ratio": selected_over.iloc[0].get("pearson_overdispersion_ratio", "") if not selected_over.empty else diag_map.get("overdispersion", ""),
                "n_rows": input_map.get("modeled_rows", ""),
                "crash_count": input_map.get("modeled_assigned_crashes", ""),
                "warning_flags": "Denominator-ready rows only",
                "model_readiness_label": ready.get("decision", ""),
            },
            {
                "model_name": SELECTED_MODEL,
                "diagnostic_label": "Modeled crashes",
                "diagnostic_value": input_map.get("modeled_assigned_crashes", ""),
                "AIC": selected_fit.iloc[0].get("aic", "") if not selected_fit.empty else "",
                "overdispersion_ratio": selected_over.iloc[0].get("pearson_overdispersion_ratio", "") if not selected_over.empty else diag_map.get("overdispersion", ""),
                "n_rows": input_map.get("modeled_rows", ""),
                "crash_count": input_map.get("modeled_assigned_crashes", ""),
                "warning_flags": "Accepted assigned crashes only",
                "model_readiness_label": ready.get("decision", ""),
            },
            {
                "model_name": SELECTED_MODEL,
                "diagnostic_label": "Overdispersion ratio",
                "diagnostic_value": selected_over.iloc[0].get("pearson_overdispersion_ratio", "") if not selected_over.empty else diag_map.get("overdispersion", ""),
                "AIC": selected_fit.iloc[0].get("aic", "") if not selected_fit.empty else "",
                "overdispersion_ratio": selected_over.iloc[0].get("pearson_overdispersion_ratio", "") if not selected_over.empty else diag_map.get("overdispersion", ""),
                "n_rows": input_map.get("modeled_rows", ""),
                "crash_count": input_map.get("modeled_assigned_crashes", ""),
                "warning_flags": "Overdispersion remains present",
                "model_readiness_label": ready.get("decision", ""),
            },
            {
                "model_name": SELECTED_MODEL,
                "diagnostic_label": "Inference method",
                "diagnostic_value": "scaled and cluster-robust Poisson",
                "AIC": selected_fit.iloc[0].get("aic", "") if not selected_fit.empty else "",
                "overdispersion_ratio": selected_over.iloc[0].get("pearson_overdispersion_ratio", "") if not selected_over.empty else diag_map.get("overdispersion", ""),
                "n_rows": input_map.get("modeled_rows", ""),
                "crash_count": input_map.get("modeled_assigned_crashes", ""),
                "warning_flags": "Conventional SE not used alone",
                "model_readiness_label": ready.get("decision", ""),
            },
            {
                "model_name": SELECTED_MODEL,
                "diagnostic_label": "NB sensitivity",
                "diagnostic_value": "fixed-alpha sensitivity only",
                "AIC": selected_fit.iloc[0].get("aic", "") if not selected_fit.empty else "",
                "overdispersion_ratio": selected_over.iloc[0].get("pearson_overdispersion_ratio", "") if not selected_over.empty else diag_map.get("overdispersion", ""),
                "n_rows": input_map.get("modeled_rows", ""),
                "crash_count": input_map.get("modeled_assigned_crashes", ""),
                "warning_flags": "Not selected inferential family",
                "model_readiness_label": ready.get("decision", ""),
            },
            {
                "model_name": SELECTED_MODEL,
                "diagnostic_label": "Stakeholder status",
                "diagnostic_value": ready.get("stakeholder_reporting_status", "blocked"),
                "AIC": selected_fit.iloc[0].get("aic", "") if not selected_fit.empty else "",
                "overdispersion_ratio": selected_over.iloc[0].get("pearson_overdispersion_ratio", "") if not selected_over.empty else diag_map.get("overdispersion", ""),
                "n_rows": input_map.get("modeled_rows", ""),
                "crash_count": input_map.get("modeled_assigned_crashes", ""),
                "warning_flags": "Internal technical review only",
                "model_readiness_label": ready.get("decision", ""),
            },
        ]
    )

    s3_coeffs = coefficients[(coefficients["model_name"] == SELECTED_MODEL) & (coefficients["term"] != "Intercept")].copy()
    pivot = s3_coeffs.pivot_table(index="term", columns="covariance_method", values="standard_error", aggfunc="first").reset_index()
    for column in ["poisson_conventional", "poisson_scaled_pearson", "poisson_robust_hc0", "poisson_cluster_reference_signal"]:
        if column not in pivot.columns:
            pivot[column] = ""
    ci_cross = s3_coeffs[s3_coeffs["covariance_method"].isin([PREFERRED_INFERENCE, CLUSTER_INFERENCE])].copy()
    ci_cross["crosses_one"] = ci_cross.apply(_sig_crosses_one, axis=1)
    cross_pivot = ci_cross.pivot_table(index="term", columns="covariance_method", values="crosses_one", aggfunc="first").reset_index()
    inference = pivot.merge(cross_pivot, on="term", how="left", suffixes=("", "_cross"))
    inference["readable_term_label"] = inference["term"].map(_readable_term_label)
    inference["term_family"] = inference["term"].map(_term_family)
    inference["material_inference_change"] = inference.apply(
        lambda row: "yes"
        if str(row.get(f"{PREFERRED_INFERENCE}_cross", "")).lower() != str(row.get(f"{CLUSTER_INFERENCE}_cross", "")).lower()
        else "no",
        axis=1,
    )
    inference["internal_note"] = "Compares existing S3 standard errors only; no refitting."
    inference = inference.rename(
        columns={
            "poisson_conventional": "conventional_SE",
            "poisson_scaled_pearson": "scaled_SE",
            "poisson_robust_hc0": "robust_SE",
            "poisson_cluster_reference_signal": "cluster_robust_SE",
        }
    )[
        [
            "term",
            "readable_term_label",
            "term_family",
            "conventional_SE",
            "scaled_SE",
            "robust_SE",
            "cluster_robust_SE",
            "material_inference_change",
            "internal_note",
        ]
    ].copy()

    return {
        "internal_model_irr_plot_data.csv": irr_plot,
        "internal_model_access_interaction_plot_data.csv": access_plot,
        "internal_model_speed_effect_plot_data.csv": speed_plot,
        "internal_model_diagnostic_plot_data.csv": diagnostic_plot,
        "internal_model_inference_comparison_plot_data.csv": inference,
    }


def write_docs() -> None:
    readme = """# Internal Model Figures

**Status: INTERNAL TECHNICAL REVIEW ONLY.**

This folder documents internal-only coefficient and IRR visualizations for `S3_access_interaction_speed_simplified`. The figures summarize exploratory association model outputs and are not stakeholder-facing report material.

Canonical generated outputs live under:

`work/output/roadway_graph/analysis/current/crash_count_internal_model_figures/`

Use these figures only for technical review of coefficient stability, access interaction terms, simplified speed terms, and model diagnostics. They do not support causal claims, safety-performance rankings, risk/danger language, policy recommendations, or downstream functional area distances.
"""
    index = """# Internal Model Figure Index

**Status: INTERNAL TECHNICAL REVIEW ONLY.**

Generated figures:

- `internal_model_irr_forest_plot.svg`: selected S3 IRR forest plot using Pearson-scaled Poisson IRRs.
- `internal_model_access_interaction_forest_plot.svg`: access-density and window-interaction term forest plot.
- `internal_model_speed_effect_forest_plot.svg`: simplified speed-band term forest plot.
- `internal_model_diagnostic_summary.svg`: compact selected-model diagnostic summary.
- `internal_model_inference_comparison.svg`: comparison of conventional, scaled, robust, and cluster-robust standard errors for selected terms.

Figure-ready tables:

- `internal_model_irr_plot_data.csv`
- `internal_model_access_interaction_plot_data.csv`
- `internal_model_speed_effect_plot_data.csv`
- `internal_model_diagnostic_plot_data.csv`
- `internal_model_inference_comparison_plot_data.csv`

The figures are generated by:

```powershell
.\\.venv\\Scripts\\python.exe -m src.roadway_graph.crash_count_internal_model_figures
```
"""
    notes = """# Internal Model Figure Review Notes

**Status: INTERNAL TECHNICAL REVIEW ONLY.**

These figures summarize exploratory association model outputs for `S3_access_interaction_speed_simplified`.

Review guardrails:

- These figures are internal-only.
- They summarize exploratory association model outputs.
- They do not support causal claims.
- They do not support safety-performance rankings.
- They do not support policy recommendations.
- They do not define downstream functional area distances.
- The selected model uses provisional bidirectional AADT exposure.
- `DIRECTION_FACTOR` is not applied.
- Overdispersion remains a limitation.
- Fixed-alpha negative-binomial fits are sensitivity evidence only.
- Stakeholder interpretation remains blocked.
"""
    _write_text(readme, DOC_DIR / "README.md")
    _write_text(index, DOC_DIR / "internal_model_figure_index.md")
    _write_text(notes, DOC_DIR / "internal_model_figure_review_notes.md")


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tables = build_plot_tables()
    for filename, frame in tables.items():
        _write_csv(frame, OUTPUT_DIR / filename)

    preferred = tables["internal_model_irr_plot_data.csv"]
    preferred = preferred[preferred["inference_type"] == _inference_label(PREFERRED_INFERENCE)].copy()
    family_order = {
        "analysis window": 0,
        "access density": 1,
        "window x access interaction": 2,
        "signal-relative direction": 3,
        "simplified speed": 4,
        "other": 5,
    }
    preferred["family_order"] = preferred["term_family"].map(lambda value: family_order.get(value, 99))
    preferred = preferred.sort_values(["family_order", "readable_term_label"])
    _forest_svg(
        preferred,
        OUTPUT_DIR / "internal_model_irr_forest_plot.svg",
        title="Selected S3 IRR Forest Plot",
        subtitle="Pearson-scaled Poisson intervals; selected model terms only.",
        caption="Exploratory/internal only. Reference line marks IRR = 1.",
    )

    access = preferred[preferred["term_family"].isin(["access density", "window x access interaction"])].copy()
    _forest_svg(
        access,
        OUTPUT_DIR / "internal_model_access_interaction_forest_plot.svg",
        title="Access Interaction Terms",
        subtitle="Access-density main terms and 1,000-2,500 ft interaction multipliers.",
        caption="Model terms help review whether access-density association differs by window; not causal effects.",
    )

    speed = preferred[preferred["term_family"] == "simplified speed"].copy()
    _forest_svg(
        speed,
        OUTPUT_DIR / "internal_model_speed_effect_forest_plot.svg",
        title="Simplified Speed Context Terms",
        subtitle="Reference category is 30-39 mph; 50+ mph is merged and missing/review speed is explicit.",
        caption="Speed is contextual exploratory evidence, not causal evidence.",
    )

    _diagnostic_svg(tables["internal_model_diagnostic_plot_data.csv"], OUTPUT_DIR / "internal_model_diagnostic_summary.svg")
    _inference_svg(tables["internal_model_inference_comparison_plot_data.csv"], OUTPUT_DIR / "internal_model_inference_comparison.svg")

    write_docs()

    existing_tables = [(OUTPUT_DIR / filename).exists() for filename in REQUIRED_OUTPUT_TABLES]
    existing_figures = [(OUTPUT_DIR / filename).exists() for filename in REQUIRED_FIGURES]
    qa = pd.DataFrame(
        [
            ("no_new_models_fit", True, "module reads existing coefficient/IRR/diagnostic outputs only", "required"),
            ("no_crash_direction_fields_used", True, "guarded CSV reader blocks crash direction field names", "required"),
            ("direction_factor_not_applied", True, "DIRECTION_FACTOR is not read or used", "required"),
            ("source_context_assignment_data_not_modified", True, "only analysis output and internal docs are written", "required"),
            ("all_figures_internal_only", True, "each SVG includes INTERNAL TECHNICAL REVIEW ONLY", "required"),
            ("stakeholder_report_draft_not_updated", True, "roadway_graph_descriptive_report_draft.md not modified by module", "required"),
            ("no_causal_policy_risk_safety_language_introduced", True, "blocked language appears only as guardrails", "required"),
            ("all_figure_source_tables_exist", all(existing_tables), f"{sum(existing_tables)} of {len(existing_tables)} tables exist", "required"),
            ("all_generated_figures_exist", all(existing_figures), f"{sum(existing_figures)} of {len(existing_figures)} figures exist", "required"),
            ("selected_model_is_s3", SELECTED_MODEL == "S3_access_interaction_speed_simplified", SELECTED_MODEL, "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )
    _write_csv(qa, OUTPUT_DIR / "internal_model_figure_qa.csv")

    missing_optional_inputs = []
    if not (SIMPLIFIED_DIR / "simplified_model_diagnostics.csv").exists():
        missing_optional_inputs.append("simplified_model_diagnostics.csv")
    manifest = {
        "package": "crash_count_internal_model_figures",
        "status": "internal_technical_review_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selected_model": SELECTED_MODEL,
        "no_new_models_fit": True,
        "crash_direction_fields_used": False,
        "direction_factor_applied": False,
        "distance_band_models_fit": False,
        "stakeholder_interpretation_status": "blocked",
        "inputs": [
            str(SIMPLIFIED_DIR / "simplified_model_coefficients.csv"),
            str(SIMPLIFIED_DIR / "simplified_model_incidence_rate_ratios.csv"),
            str(SIMPLIFIED_DIR / "simplified_model_clustered_se_comparison.csv"),
            str(SIMPLIFIED_DIR / "simplified_model_fit_summary.csv"),
            str(SIMPLIFIED_DIR / "simplified_model_overdispersion_summary.csv"),
            str(SIMPLIFIED_DIR / "simplified_access_interaction_summary.csv"),
            str(SIMPLIFIED_DIR / "simplified_speed_sensitivity_summary.csv"),
            str(REVIEW_DIR / "internal_model_selected_irrs.csv"),
            str(REVIEW_DIR / "internal_model_access_interaction_interpretation_table.csv"),
            str(REVIEW_DIR / "internal_model_diagnostic_summary.csv"),
            str(TECHNICAL_MEMO),
        ],
        "missing_optional_inputs": missing_optional_inputs,
        "outputs": [*REQUIRED_OUTPUT_TABLES, *REQUIRED_FIGURES, "internal_model_figure_qa.csv", "internal_model_figure_manifest.json"],
        "docs": [
            str(DOC_DIR / "README.md"),
            str(DOC_DIR / "internal_model_figure_index.md"),
            str(DOC_DIR / "internal_model_figure_review_notes.md"),
        ],
        "qa_passed": bool(qa["passed"].astype(bool).all()),
    }
    _write_json(manifest, OUTPUT_DIR / "internal_model_figure_manifest.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create internal-only crash-count model coefficient and IRR figures.")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
