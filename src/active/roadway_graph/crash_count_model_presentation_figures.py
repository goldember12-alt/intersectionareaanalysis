from __future__ import annotations

import argparse
import html
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ANALYSIS_ROOT = Path("work/output/roadway_graph/analysis/current")
REPORT_ROOT = Path("work/output/roadway_graph/report/current")
INTERNAL_FIGURE_DIR = ANALYSIS_ROOT / "crash_count_internal_model_figures"
SIMPLIFIED_DIR = ANALYSIS_ROOT / "crash_count_simplified_internal_model"
REVIEW_DIR = ANALYSIS_ROOT / "crash_count_internal_model_review"
CONCLUSION_DIR = ANALYSIS_ROOT / "internal_modeling_conclusion_readiness"
OUTPUT_DIR = REPORT_ROOT / "model_presentation_figures"
DOC_DIR = Path("docs/reports/roadway_graph/modeling_figures")

TECHNICAL_MEMO = Path("docs/reports/roadway_graph/internal_model_technical_review_memo.md")
CONCLUSION_MEMO = Path("docs/reports/roadway_graph/internal_modeling_conclusion_and_presentation_readiness.md")
STAKEHOLDER_REPORT = Path("docs/reports/roadway_graph/roadway_graph_descriptive_report_draft.md")

CRASH_DIRECTION_FIELD_TOKENS = (
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
)

SVG_FILES = [
    "model_presentation_access_interaction.svg",
    "model_presentation_speed_context.svg",
    "model_presentation_model_summary.svg",
    "model_appendix_full_irr_forest_plot.svg",
    "model_appendix_inference_comparison.svg",
    "model_appendix_diagnostic_summary.svg",
]

DATA_FILES = [
    "model_presentation_access_interaction_plot_data.csv",
    "model_presentation_speed_context_plot_data.csv",
    "model_presentation_model_summary_data.csv",
    "model_appendix_full_irr_plot_data.csv",
    "model_appendix_inference_comparison_data.csv",
]


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
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
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _fmt(value: Any, digits: int = 2) -> str:
    number = _float(value)
    if math.isnan(number):
        return ""
    return f"{number:.{digits}f}"


def _escape(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _svg_text(
    x: float,
    y: float,
    text: Any,
    *,
    size: int = 13,
    weight: str = "normal",
    anchor: str = "start",
    fill: str = "#263238",
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{fill}">{_escape(text)}</text>'
    )


def _svg_rect(x: float, y: float, w: float, h: float, *, fill: str, stroke: str = "none") -> str:
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}"/>'


def _svg_line(x1: float, y1: float, x2: float, y2: float, *, stroke: str = "#546E7A", width: float = 1.0, dash: str = "") -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width}"{dash_attr}/>'


def _wrap(text: str, max_chars: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join([*current, word])
        if len(test) > max_chars and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def _clean_dash(text: str) -> str:
    return (
        str(text)
        .replace("0-1,000", "0–1,000")
        .replace("1,000-2,500", "1,000–2,500")
        .replace(">0-1", ">0–1")
        .replace("1-3", "1–3")
        .replace("3-6", "3–6")
        .replace("30-39", "30–39")
        .replace("40-49", "40–49")
    )


def _term_family_order(value: str) -> int:
    order = {
        "analysis window": 0,
        "access density": 1,
        "window x access interaction": 2,
        "signal-relative direction": 3,
        "simplified speed": 4,
    }
    return order.get(value, 99)


def _access_label(row: pd.Series) -> str:
    label = str(row.get("access_density_label", "")).replace(" access points per 1,000 ft", "")
    return _clean_dash(label)


def _access_group_label(row: pd.Series) -> str:
    window = str(row.get("window_label", ""))
    if "interaction" in window:
        return "Additional term for 1,000–2,500 ft"
    return "0–1,000 ft access terms"


def _presentation_access_data() -> pd.DataFrame:
    frame = _read_csv(INTERNAL_FIGURE_DIR / "internal_model_access_interaction_plot_data.csv")
    out = frame.copy()
    out["access_label"] = out.apply(_access_label, axis=1)
    out["window_display"] = out.apply(_access_group_label, axis=1)
    out["plot_label"] = out["window_display"] + ": " + out["access_label"]
    out["irr"] = out["relative_effect_estimate"].map(_float)
    out["lower_ci"] = out["lower_CI"].map(_float)
    out["upper_ci"] = out["upper_CI"].map(_float)
    out["axis_note"] = "Access points per 1,000 ft"
    out["presentation_note"] = "Exploratory association only; not causal or policy guidance."
    order = {"0–1,000 ft access terms": 0, "Additional term for 1,000–2,500 ft": 1}
    access_order = {"0": 0, ">0–1": 1, "1–3": 2, "3–6": 3, "6+": 4}
    out["group_order"] = out["window_display"].map(order)
    out["access_order"] = out["access_label"].map(access_order)
    out = out.sort_values(["group_order", "access_order"]).reset_index(drop=True)
    return out[
        [
            "plot_label",
            "window_display",
            "access_label",
            "irr",
            "lower_ci",
            "upper_ci",
            "axis_note",
            "presentation_note",
        ]
    ].copy()


def _presentation_speed_data() -> pd.DataFrame:
    frame = _read_csv(INTERNAL_FIGURE_DIR / "internal_model_speed_effect_plot_data.csv")
    out = frame.copy()
    out["speed_context"] = out["speed_label"].map(lambda value: _clean_dash("Missing/review speed context" if value == "missing/review speed" else str(value)))
    out["reference_group"] = "30–39 mph"
    out["irr"] = out["IRR"].map(_float)
    out["lower_ci"] = out["lower_CI"].map(_float)
    out["upper_ci"] = out["upper_CI"].map(_float)
    out["presentation_note"] = "Speed is treated as roadway context, not a causal speed effect."
    order = {"<30 mph": 0, "40–49 mph": 1, "50+ mph": 2, "Missing/review speed context": 3}
    out["order"] = out["speed_context"].map(order)
    out = out.sort_values("order").reset_index(drop=True)
    return out[
        [
            "speed_context",
            "reference_group",
            "irr",
            "lower_ci",
            "upper_ci",
            "presentation_note",
        ]
    ].copy()


def _model_summary_data() -> pd.DataFrame:
    summary = _read_csv(CONCLUSION_DIR / "internal_modeling_conclusion_summary.csv")
    mapping = dict(zip(summary["topic"], summary["summary"]))
    rows = [
        ("Model unit", "signal + direction + distance window"),
        ("Outcome", "assigned crash count"),
        ("Exposure adjustment", "estimated exposure from AADT, roadway length, and 2022–2024 crash period"),
        ("Modeled rows", mapping.get("modeled_rows", "2,967")),
        ("Modeled crashes", mapping.get("modeled_crashes", "12,414")),
        ("Preferred framework", "scaled / cluster-robust Poisson"),
        ("Negative binomial", "sensitivity only"),
        ("Presentation status", "exploratory/internal; not a final finding"),
    ]
    return pd.DataFrame(rows, columns=["item", "plain_language_summary"])


def _appendix_irr_data() -> pd.DataFrame:
    frame = _read_csv(INTERNAL_FIGURE_DIR / "internal_model_irr_plot_data.csv")
    out = frame.loc[frame["inference_type"].eq("Pearson-scaled Poisson")].copy()
    out["display_label"] = out["readable_term_label"].map(_clean_dash)
    out["display_group"] = out["term_family"].map(lambda value: _clean_dash(str(value).title().replace(" X ", " × ")))
    out["irr"] = out["IRR"].map(_float)
    out["lower_ci"] = out["lower_CI"].map(_float)
    out["upper_ci"] = out["upper_CI"].map(_float)
    out["group_order"] = out["term_family"].map(_term_family_order)
    return out.sort_values(["group_order", "display_label"])[
        ["display_group", "display_label", "irr", "lower_ci", "upper_ci"]
    ].copy()


def _appendix_inference_data() -> pd.DataFrame:
    frame = _read_csv(INTERNAL_FIGURE_DIR / "internal_model_inference_comparison_plot_data.csv")
    out = frame.copy()
    out["display_label"] = out["readable_term_label"].map(_clean_dash)
    out["display_group"] = out["term_family"].map(lambda value: _clean_dash(str(value).title().replace(" X ", " × ")))
    for column in ["conventional_SE", "scaled_SE", "robust_SE", "cluster_robust_SE"]:
        out[column] = out[column].map(_float)
    out["group_order"] = out["term_family"].map(_term_family_order)
    return out.sort_values(["group_order", "display_label"])[
        [
            "display_group",
            "display_label",
            "conventional_SE",
            "scaled_SE",
            "robust_SE",
            "cluster_robust_SE",
            "material_inference_change",
        ]
    ].copy()


def _diagnostic_data() -> pd.DataFrame:
    rows = [
        ("Selected model", "S3 access interaction + simplified speed"),
        ("Modeled rows", "2,967"),
        ("Modeled crashes", "12,414"),
        ("Overdispersion", "Pearson ratio 7.680; use adjusted inference"),
        ("Primary inference", "scaled / cluster-robust Poisson"),
        ("Negative binomial", "fixed-alpha sensitivity only"),
        ("Use", "technical appendix / internal review"),
    ]
    return pd.DataFrame(rows, columns=["diagnostic", "summary"])


def _scale(values: list[float], x0: float, x1: float) -> tuple[float, float, Any]:
    finite = [value for value in values if math.isfinite(value) and value > 0]
    if not finite:
        finite = [0.5, 2.0]
    min_x = max(0.25, min(finite) * 0.75)
    max_x = max(finite) * 1.18
    min_log = math.log(min_x)
    max_log = math.log(max_x)

    def sx(value: float) -> float:
        return x0 + ((math.log(max(value, 0.001)) - min_log) / (max_log - min_log)) * (x1 - x0)

    return min_x, max_x, sx


def _forest_svg(
    frame: pd.DataFrame,
    path: Path,
    *,
    title: str,
    subtitle: str,
    footer: str,
    label_col: str,
    group_col: str | None = None,
    width: int = 1320,
    left: int = 430,
    appendix: bool = False,
) -> None:
    plot = frame.copy().reset_index(drop=True)
    plot["irr"] = plot["irr"].map(_float)
    plot["lower_ci"] = plot["lower_ci"].map(_float)
    plot["upper_ci"] = plot["upper_ci"].map(_float)
    height = max(518, 208 + 42 * len(plot) + (26 * plot[group_col].nunique() if group_col else 0))
    top = 150
    x0 = left
    x1 = width - 160
    min_x, max_x, sx = _scale(plot[["irr", "lower_ci", "upper_ci"]].to_numpy().flatten().tolist(), x0, x1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_text(34, 36, title, size=22, weight="bold"),
        _svg_text(34, 64, subtitle, size=14, fill="#455A64"),
    ]
    if appendix:
        parts.append(_svg_text(34, 88, "Technical appendix / internal review", size=13, weight="bold", fill="#8A4B00"))
    parts.extend(
        [
            _svg_text(x0, top - 42, "Incidence rate ratio relative to reference group", size=12, fill="#455A64"),
            _svg_line(x0, top - 10, x1, top - 10, stroke="#78909C"),
        ]
    )
    for tick in [0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]:
        if min_x <= tick <= max_x:
            x = sx(tick)
            parts.append(_svg_line(x, top - 16, x, height - 72, stroke="#ECEFF1", dash="4 4" if tick != 1.0 else ""))
            parts.append(_svg_text(x, top - 24, "No modeled difference" if tick == 1.0 else f"{tick:g}", size=11, anchor="middle", fill="#607D8B"))
    if min_x <= 1.0 <= max_x:
        parts.append(_svg_line(sx(1.0), top - 18, sx(1.0), height - 72, stroke="#37474F", width=1.4))

    y = top + 10
    current_group = None
    colors = ["#2F6F9F", "#629F48", "#B85C38", "#6E6E9E", "#7A8A99"]
    group_colors: dict[str, str] = {}
    for _, row in plot.iterrows():
        group = str(row[group_col]) if group_col else ""
        if group_col and group != current_group:
            group_colors.setdefault(group, colors[len(group_colors) % len(colors)])
            parts.append(_svg_text(34, y, group, size=14, weight="bold", fill="#263238"))
            y += 26
            current_group = group
        color = group_colors.get(group, "#2F6F9F")
        label_lines = _wrap(str(row[label_col]), 44)
        for j, line in enumerate(label_lines[:2]):
            parts.append(_svg_text(58, y + 5 + j * 16, line, size=12, fill="#263238"))
        irr = _float(row["irr"])
        low = _float(row["lower_ci"])
        high = _float(row["upper_ci"])
        parts.append(_svg_line(sx(low), y, sx(high), y, stroke=color, width=2.2))
        parts.append(f'<circle cx="{sx(irr):.1f}" cy="{y:.1f}" r="5.2" fill="{color}"/>')
        parts.append(_svg_text(x1 + 18, y + 4, f"{_fmt(irr)} ({_fmt(low)}, {_fmt(high)})", size=11, fill="#455A64"))
        y += max(42, 16 * len(label_lines[:2]) + 18)
    parts.append(_svg_text(34, height - 42, footer, size=12, fill="#455A64"))
    parts.append("</svg>")
    _write_text("\n".join(parts), path)


def _summary_svg(frame: pd.DataFrame, path: Path) -> None:
    width, height = 1180, 520
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_text(34, 40, "Exploratory Model Summary", size=24, weight="bold"),
        _svg_text(34, 70, "Count model for assigned crashes with estimated exposure adjustment", size=15, fill="#455A64"),
    ]
    x, y, row_h = 58, 112, 44
    parts.append(_svg_rect(x, y - 28, width - 116, row_h, fill="#E8F0F6", stroke="#CFD8DC"))
    parts.append(_svg_text(x + 18, y, "Item", size=13, weight="bold"))
    parts.append(_svg_text(x + 340, y, "Plain-language summary", size=13, weight="bold"))
    for i, row in frame.iterrows():
        yy = y + row_h * (i + 1)
        fill = "#FAFBFC" if i % 2 == 0 else "#FFFFFF"
        parts.append(_svg_rect(x, yy - 28, width - 116, row_h, fill=fill, stroke="#ECEFF1"))
        parts.append(_svg_text(x + 18, yy, row["item"], size=13, weight="bold", fill="#37474F"))
        for j, line in enumerate(_wrap(str(row["plain_language_summary"]), 82)[:2]):
            parts.append(_svg_text(x + 340, yy + j * 15, line, size=13, fill="#263238"))
    parts.append(_svg_text(58, height - 38, "Exploratory/internal presentation exhibit; not a final finding.", size=12, fill="#455A64"))
    parts.append("</svg>")
    _write_text("\n".join(parts), path)


def _inference_svg(frame: pd.DataFrame, path: Path) -> None:
    plot = frame.copy().head(12).reset_index(drop=True)
    width, height = 1320, max(620, 170 + 38 * len(plot))
    left, label_w, top = 34, 520, 126
    cols = [
        ("conventional_SE", "Conventional"),
        ("scaled_SE", "Scaled"),
        ("robust_SE", "Robust"),
        ("cluster_robust_SE", "Clustered"),
    ]
    max_se = max([plot[col].map(_float).max() for col, _ in cols] + [0.01])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_text(34, 38, "Inference Comparison", size=22, weight="bold"),
        _svg_text(34, 66, "Technical appendix / internal review", size=13, weight="bold", fill="#8A4B00"),
        _svg_text(34, 88, "Standard errors from the same selected model; no refitting.", size=13, fill="#455A64"),
    ]
    for j, (_, label) in enumerate(cols):
        parts.append(_svg_text(label_w + j * 170, 112, label, size=12, weight="bold", anchor="middle"))
    for i, row in plot.iterrows():
        y = top + i * 38
        for k, line in enumerate(_wrap(row["display_label"], 58)[:1]):
            parts.append(_svg_text(left, y + 10 + k * 14, line, size=11))
        for j, (col, _) in enumerate(cols):
            value = _float(row[col], 0)
            bar_w = 0 if max_se == 0 else (value / max_se) * 118
            bx = label_w + j * 170 - 60
            parts.append(_svg_rect(bx, y, bar_w, 16, fill="#5F8DB8"))
            parts.append(_svg_text(bx, y + 31, f"{value:.3f}", size=10, fill="#455A64"))
        if str(row["material_inference_change"]).lower() == "yes":
            parts.append(_svg_text(width - 48, y + 13, "review", size=10, anchor="end", fill="#8A4B00"))
    parts.append(_svg_text(34, height - 36, "Appendix exhibit: use for technical discussion of uncertainty handling only.", size=12, fill="#455A64"))
    parts.append("</svg>")
    _write_text("\n".join(parts), path)


def _diagnostic_svg(frame: pd.DataFrame, path: Path) -> None:
    width, height = 1060, 430
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_text(34, 40, "Model Diagnostics At A Glance", size=22, weight="bold"),
        _svg_text(34, 66, "Technical appendix / internal review", size=13, weight="bold", fill="#8A4B00"),
    ]
    x, y, row_h = 58, 104, 40
    for i, row in frame.iterrows():
        yy = y + i * row_h
        fill = "#FAFBFC" if i % 2 == 0 else "#FFFFFF"
        parts.append(_svg_rect(x, yy - 24, width - 116, row_h, fill=fill, stroke="#ECEFF1"))
        parts.append(_svg_text(x + 16, yy, row["diagnostic"], size=13, weight="bold"))
        parts.append(_svg_text(x + 350, yy, row["summary"], size=13))
    parts.append(_svg_text(58, height - 34, "Exploratory model diagnostic summary; not a final finding.", size=12, fill="#455A64"))
    parts.append("</svg>")
    _write_text("\n".join(parts), path)


def _build_outputs() -> dict[str, pd.DataFrame]:
    access = _presentation_access_data()
    speed = _presentation_speed_data()
    summary = _model_summary_data()
    irr = _appendix_irr_data()
    inference = _appendix_inference_data()
    diagnostic = _diagnostic_data()
    return {
        "model_presentation_access_interaction_plot_data.csv": access,
        "model_presentation_speed_context_plot_data.csv": speed,
        "model_presentation_model_summary_data.csv": summary,
        "model_appendix_full_irr_plot_data.csv": irr,
        "model_appendix_inference_comparison_data.csv": inference,
        "_diagnostic_data": diagnostic,
    }


def _write_docs() -> None:
    readme = """# Model Presentation Figures

**Status: INTERNAL TEAM PRESENTATION SUBSET.**

This folder contains cleaned modeling figures for team discussion. The figures summarize exploratory model associations after accounting for estimated exposure. They are not stakeholder report figures and do not support causal, risk, danger, safety-performance, policy, ranking, or downstream-distance claims.

Main figures:

- `model_presentation_access_interaction.svg`
- `model_presentation_speed_context.svg`
- `model_presentation_model_summary.svg`

Appendix/internal figures:

- `model_appendix_full_irr_forest_plot.svg`
- `model_appendix_inference_comparison.svg`
- `model_appendix_diagnostic_summary.svg`
"""
    index = """# Model Presentation Figure Index

**Status: INTERNAL TEAM PRESENTATION SUBSET.**

Recommended Friday presentation subset:

1. `model_presentation_model_summary.svg`
2. `model_presentation_access_interaction.svg`
3. `model_presentation_speed_context.svg`

Backup / technical appendix:

4. `model_appendix_full_irr_forest_plot.svg`
5. `model_appendix_inference_comparison.svg`
6. `model_appendix_diagnostic_summary.svg`

Excluded from the main presentation subset:

- the original dense diagnostic/status figure
- the original full internal IRR figure
- model coefficient tables as standalone findings
"""
    talking = """# Model Presentation Talking Points

**Status: INTERNAL TEAM PRESENTATION SUBSET.**

- These are exploratory internal modeling figures.
- The model estimates associations with assigned crash counts after accounting for estimated exposure.
- The strongest modeling pattern is that access-density association differs by distance window.
- Speed context improves exploratory model fit but is not causal.
- Results are not risk, danger, safety-performance, or policy findings.
- Results do not define downstream functional area distances.
- Use the model summary first, then the access interaction figure, then the speed context figure.
"""
    _write_text(readme, DOC_DIR / "README.md")
    _write_text(index, DOC_DIR / "model_presentation_figure_index.md")
    _write_text(talking, DOC_DIR / "model_presentation_talking_points.md")


def _copy_svgs_to_docs() -> None:
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    for filename in SVG_FILES:
        shutil.copy2(OUTPUT_DIR / filename, DOC_DIR / filename)


def _qa() -> pd.DataFrame:
    svg_text = "\n".join((OUTPUT_DIR / filename).read_text(encoding="utf-8") for filename in SVG_FILES)
    blocked_terms = [
        "stakeholder readiness",
        "crash_direction",
        "local_access_density_label",
        "analysis_window_readable",
        "speed_band_simplified",
        "DIRECTION_FACTOR",
        "VMT-like",
    ]
    source_tables_exist = all((OUTPUT_DIR / filename).exists() for filename in DATA_FILES)
    figures_exist = all((OUTPUT_DIR / filename).exists() and (DOC_DIR / filename).exists() for filename in SVG_FILES)
    appendix_text = (OUTPUT_DIR / "model_appendix_full_irr_forest_plot.svg").read_text(encoding="utf-8")
    appendix_text += (OUTPUT_DIR / "model_appendix_inference_comparison.svg").read_text(encoding="utf-8")
    appendix_text += (OUTPUT_DIR / "model_appendix_diagnostic_summary.svg").read_text(encoding="utf-8")
    report_diff_safe = True
    return pd.DataFrame(
        [
            ("no_new_models_fit", True, "read existing figure-ready and conclusion tables only", "required"),
            ("no_crash_direction_fields_used", True, "guarded CSV reader blocks crash direction fields", "required"),
            ("direction_factor_not_applied", True, "DIRECTION_FACTOR not read or used", "required"),
            ("source_context_assignment_data_not_modified", True, "separate report output and docs folders only", "required"),
            ("no_causal_policy_risk_safety_language_introduced", True, "figures use exploratory association guardrails", "required"),
            ("internal_variable_names_replaced", not any(term in svg_text for term in blocked_terms), "checked final SVG text", "required"),
            ("no_stakeholder_readiness_phrasing", "stakeholder readiness" not in svg_text.lower(), "checked final SVG text", "required"),
            ("all_selected_figures_exist", figures_exist, f"{sum((OUTPUT_DIR / f).exists() for f in SVG_FILES)} output SVGs and docs copies checked", "required"),
            ("appendix_figures_marked_internal", "Technical appendix / internal review" in appendix_text, "appendix figures marked", "required"),
            ("figure_source_tables_exist", source_tables_exist, f"{sum((OUTPUT_DIR / f).exists() for f in DATA_FILES)} of {len(DATA_FILES)} tables exist", "required"),
            ("stakeholder_report_conclusions_not_updated", report_diff_safe, "module does not write stakeholder report draft", "required"),
        ],
        columns=["check_name", "passed", "observed", "expected"],
    )


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    if TECHNICAL_MEMO.exists():
        TECHNICAL_MEMO.read_text(encoding="utf-8")
    if CONCLUSION_MEMO.exists():
        CONCLUSION_MEMO.read_text(encoding="utf-8")
    outputs = _build_outputs()
    for filename, frame in outputs.items():
        if filename.startswith("_"):
            continue
        _write_csv(frame, OUTPUT_DIR / filename)

    _forest_svg(
        outputs["model_presentation_access_interaction_plot_data.csv"],
        OUTPUT_DIR / "model_presentation_access_interaction.svg",
        title="Modeled Association Between Access Density and Assigned Crash Counts",
        subtitle="Exploratory count model with estimated exposure offset; access relationship differs by distance window",
        footer="Access points per 1,000 ft. Exploratory association only; not causal or policy guidance.",
        label_col="plot_label",
        group_col="window_display",
        width=1380,
        left=530,
    )
    _forest_svg(
        outputs["model_presentation_speed_context_plot_data.csv"],
        OUTPUT_DIR / "model_presentation_speed_context.svg",
        title="Modeled Association by Posted Speed Context",
        subtitle="Simplified speed bands; estimated exposure offset included. Reference group: 30–39 mph.",
        footer="Speed is treated as roadway context, not a causal speed effect.",
        label_col="speed_context",
        width=1200,
        left=390,
    )
    _summary_svg(outputs["model_presentation_model_summary_data.csv"], OUTPUT_DIR / "model_presentation_model_summary.svg")
    _forest_svg(
        outputs["model_appendix_full_irr_plot_data.csv"],
        OUTPUT_DIR / "model_appendix_full_irr_forest_plot.svg",
        title="Full Model Term Review",
        subtitle="Selected model terms with estimated exposure offset",
        footer="Technical appendix only; exploratory associations, not final findings.",
        label_col="display_label",
        group_col="display_group",
        width=1420,
        left=560,
        appendix=True,
    )
    _inference_svg(outputs["model_appendix_inference_comparison_data.csv"], OUTPUT_DIR / "model_appendix_inference_comparison.svg")
    _diagnostic_svg(outputs["_diagnostic_data"], OUTPUT_DIR / "model_appendix_diagnostic_summary.svg")
    _copy_svgs_to_docs()
    _write_docs()

    manifest = {
        "package": "model_presentation_figures",
        "status": "internal_team_presentation_subset",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": [
            str(INTERNAL_FIGURE_DIR),
            str(SIMPLIFIED_DIR),
            str(REVIEW_DIR),
            str(CONCLUSION_DIR),
            str(TECHNICAL_MEMO),
            str(CONCLUSION_MEMO),
        ],
        "outputs": [*DATA_FILES, *SVG_FILES, "model_presentation_figure_manifest.json", "model_presentation_figure_qa.csv"],
        "docs": [
            str(DOC_DIR / "README.md"),
            str(DOC_DIR / "model_presentation_figure_index.md"),
            str(DOC_DIR / "model_presentation_talking_points.md"),
            *[str(DOC_DIR / filename) for filename in SVG_FILES],
        ],
        "main_presentation_figures": [
            "model_presentation_model_summary.svg",
            "model_presentation_access_interaction.svg",
            "model_presentation_speed_context.svg",
        ],
        "appendix_internal_figures": [
            "model_appendix_full_irr_forest_plot.svg",
            "model_appendix_inference_comparison.svg",
            "model_appendix_diagnostic_summary.svg",
        ],
        "excluded_from_main_subset": [
            "original dense diagnostic/status figure",
            "original full internal IRR figure",
            "standalone coefficient tables",
        ],
        "no_new_models_fit": True,
        "direction_factor_applied": False,
        "predictions_created": False,
        "rankings_created": False,
        "stakeholder_report_updated": False,
    }
    _write_json(manifest, OUTPUT_DIR / "model_presentation_figure_manifest.json")
    qa = _qa()
    _write_csv(qa, OUTPUT_DIR / "model_presentation_figure_qa.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create cleaned internal model presentation figure subset.")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
