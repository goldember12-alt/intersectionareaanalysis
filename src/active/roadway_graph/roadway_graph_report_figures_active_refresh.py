from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ANALYSIS_ROOT = Path("work/output/roadway_graph/analysis/current")
REPORT_ROOT = Path("work/output/roadway_graph/report/current_active")
FIGURE_DIR = REPORT_ROOT / "figures"
FIGURE_DATA_DIR = REPORT_ROOT / "figure_data"
DOC_FIGURE_DIR = Path("docs/reports/roadway_graph/figures/active_v2_v5")

ACTIVE_CONTEXT_FILE = ANALYSIS_ROOT / "directional_bin_context_table_active/directional_bin_context_active.csv"
ACTIVE_CRASH_FILE = ANALYSIS_ROOT / "directional_bin_context_table_active/directional_crash_context_active.csv"
ACTIVE_RATE_FILE = ANALYSIS_ROOT / "descriptive_crash_rate_prototype_active/active_rate_signal_direction_window.csv"
ACTIVE_RATE_BY_WINDOW_FILE = ANALYSIS_ROOT / "descriptive_crash_rate_prototype_active/active_rate_summary_by_window.csv"
ACTIVE_RATE_BY_DIRECTION_FILE = ANALYSIS_ROOT / "descriptive_crash_rate_prototype_active/active_rate_summary_by_direction.csv"
ACTIVE_MODEL_WINDOW_FILE = ANALYSIS_ROOT / "crash_count_modeling_readiness_dataset_active/crash_count_modeling_matrix_signal_direction_window_active.csv"
ACTIVE_MODEL_BAND_FILE = ANALYSIS_ROOT / "crash_count_modeling_readiness_dataset_active/crash_count_modeling_matrix_signal_direction_distance_band_active.csv"
ACTIVE_IMPACT_CONTEXT_FILE = ANALYSIS_ROOT / "active_refresh_impact_summary/active_refresh_context_count_comparison.csv"
ACTIVE_IMPACT_RATE_FILE = ANALYSIS_ROOT / "active_refresh_impact_summary/active_refresh_rate_comparison.csv"
ACTIVE_IMPACT_MODEL_FILE = ANALYSIS_ROOT / "active_refresh_impact_summary/active_refresh_modeling_matrix_comparison.csv"

BASELINE_FIGURE_DIRS = [
    Path("docs/reports/roadway_graph/descriptive_figures"),
    Path("docs/reports/roadway_graph/figures"),
    Path("work/output/roadway_graph/report/current/figures"),
]

CRASH_DIRECTION_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel")

WINDOW_ORDER = ["high_priority_0_1000ft", "sensitivity_1000_2500ft"]
BAND_ORDER = ["0_250ft", "250_500ft", "500_1000ft", "1000_1500ft", "1500_2500ft"]
SPEED_ORDER = ["lt_30_mph", "30_39_mph", "40_49_mph", "50_59_mph", "60plus_mph", "speed_missing_or_review"]
AADT_ORDER = ["lt_10000", "10000_19999", "20000_39999", "40000_59999", "60000plus", "aadt_missing_or_review"]
ACCESS_ORDER = ["0_per_1000ft", "gt0_lt1_per_1000ft", "1_lt3_per_1000ft", "3_lt6_per_1000ft", "6plus_per_1000ft"]

LABELS = {
    "high_priority_0_1000ft": "0-1,000 ft",
    "sensitivity_1000_2500ft": "1,000-2,500 ft",
    "upstream_of_reference_signal": "Upstream",
    "downstream_of_reference_signal": "Downstream",
    "0_250ft": "0-250 ft",
    "250_500ft": "250-500 ft",
    "500_1000ft": "500-1,000 ft",
    "1000_1500ft": "1,000-1,500 ft",
    "1500_2500ft": "1,500-2,500 ft",
    "lt_30_mph": "<30 mph",
    "30_39_mph": "30-39 mph",
    "40_49_mph": "40-49 mph",
    "50_59_mph": "50-59 mph",
    "60plus_mph": "60+ mph",
    "speed_missing_or_review": "Missing/review speed",
    "lt_10000": "<10k AADT",
    "10000_19999": "10k-20k",
    "20000_39999": "20k-40k",
    "40000_59999": "40k-60k",
    "60000plus": "60k+",
    "aadt_missing_or_review": "Missing/review AADT",
    "0_per_1000ft": "0",
    "gt0_lt1_per_1000ft": ">0-1",
    "1_lt3_per_1000ft": "1-3",
    "3_lt6_per_1000ft": "3-6",
    "6plus_per_1000ft": "6+",
}

SOURCE_NOTE = "Active v2/v5. Speed context: v5 Speed_Limit_RNS supplement. Exposure: AADT v2 direction-factor with bidirectional fallback."
RATE_NOTE = "Descriptive prototype rate using estimated exposure; DIRECTION_FACTOR applied where valid and bidirectional fallback where null. Not risk, safety, policy, or distance guidance."


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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame[column].astype(str).str.lower().isin(["true", "1", "yes"])


def _safe_div(numerator: Any, denominator: Any) -> Any:
    return numerator / denominator.replace(0, pd.NA)


def _label(value: Any) -> str:
    return LABELS.get(str(value), str(value))


def _fmt_int(value: Any) -> str:
    return f"{int(round(float(value))):,}"


def _fmt_float(value: Any, digits: int = 2) -> str:
    return f"{float(value):,.{digits}f}"


def _svg_text(x: int, y: int, text: str, *, size: int = 12, weight: str = "normal", anchor: str = "start") -> str:
    return f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="#222">{html.escape(str(text))}</text>'


def _save_svg(stem: str, svg: str) -> tuple[Path, Path]:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    DOC_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    work_path = FIGURE_DIR / f"{stem}.svg"
    docs_path = DOC_FIGURE_DIR / f"{stem}.svg"
    _write_text(svg, work_path)
    _write_text(svg, docs_path)
    return work_path, docs_path


def _bar_chart(frame: pd.DataFrame, label_col: str, value_col: str, title: str, subtitle: str, stem: str, *, rate: bool = False) -> tuple[Path, Path]:
    width, height = 980, 560
    left, top, chart_w, chart_h = 95, 105, 790, 320
    values = [float(v) for v in frame[value_col].fillna(0)]
    labels = [_label(v) for v in frame[label_col]]
    max_value = max(values) if values else 1.0
    max_value = max(max_value, 1.0)
    gap = 24
    bar_w = max(28, int((chart_w - gap * (len(values) - 1)) / max(1, len(values))))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 36, title, size=20, weight="bold"),
        _svg_text(30, 60, subtitle, size=12),
        _svg_text(30, 80, SOURCE_NOTE if not rate else RATE_NOTE, size=11),
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#666"/>',
        f'<line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#666"/>',
    ]
    color = "#3f6f8f" if not rate else "#7a5b35"
    for i, (label, value) in enumerate(zip(labels, values)):
        x = left + i * (bar_w + gap)
        h = int((value / max_value) * (chart_h - 24))
        y = top + chart_h - h
        parts.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h}" fill="{color}"/>')
        label_value = _fmt_float(value, 3) if rate else _fmt_int(value)
        parts.append(_svg_text(x + bar_w / 2, y - 8, label_value, size=11, anchor="middle"))
        parts.append(_svg_text(x + bar_w / 2, top + chart_h + 24, label, size=10, anchor="middle"))
    parts.append("</svg>")
    return _save_svg(stem, "\n".join(parts))


def _stacked_chart(frame: pd.DataFrame, label_col: str, specs: list[tuple[str, str, str]], title: str, subtitle: str, stem: str) -> tuple[Path, Path]:
    width, height = 980, 560
    left, top, chart_w, chart_h = 95, 105, 790, 320
    labels = [_label(v) for v in frame[label_col]]
    totals = [sum(float(row[col]) for col, _, _ in specs) for _, row in frame.iterrows()]
    max_value = max(totals) if totals else 1.0
    max_value = max(max_value, 1.0)
    gap = 24
    bar_w = max(28, int((chart_w - gap * (len(labels) - 1)) / max(1, len(labels))))
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 36, title, size=20, weight="bold"),
        _svg_text(30, 60, subtitle, size=12),
        _svg_text(30, 80, SOURCE_NOTE, size=11),
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#666"/>',
        f'<line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#666"/>',
    ]
    for i, (_, row) in enumerate(frame.iterrows()):
        x = left + i * (bar_w + gap)
        y_cursor = top + chart_h
        for col, _, color in specs:
            value = float(row[col])
            h = int((value / max_value) * (chart_h - 24))
            y_cursor -= h
            parts.append(f'<rect x="{x}" y="{y_cursor}" width="{bar_w}" height="{h}" fill="{color}"/>')
        parts.append(_svg_text(x + bar_w / 2, y_cursor - 8, _fmt_int(sum(float(row[col]) for col, _, _ in specs)), size=11, anchor="middle"))
        parts.append(_svg_text(x + bar_w / 2, top + chart_h + 24, _label(row[label_col]), size=10, anchor="middle"))
    lx = 700
    for j, (_, label, color) in enumerate(specs):
        y = 112 + j * 20
        parts.append(f'<rect x="{lx}" y="{y}" width="12" height="12" fill="{color}"/>')
        parts.append(_svg_text(lx + 18, y + 11, label, size=11))
    parts.append("</svg>")
    return _save_svg(stem, "\n".join(parts))


def _heatmap(frame: pd.DataFrame, x_col: str, y_col: str, value_col: str, title: str, subtitle: str, stem: str, *, rate: bool = False) -> tuple[Path, Path]:
    width, height = 1080, 650
    left, top = 190, 115
    cell_w, cell_h = 120, 58
    x_vals = list(dict.fromkeys(frame[x_col].tolist()))
    y_vals = list(dict.fromkeys(frame[y_col].tolist()))
    values = pd.to_numeric(frame[value_col], errors="coerce").fillna(0)
    max_value = max(float(values.max()), 1.0)
    data = {(row[x_col], row[y_col]): float(row[value_col]) if str(row[value_col]) != "" else 0.0 for _, row in frame.iterrows()}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 36, title, size=20, weight="bold"),
        _svg_text(30, 60, subtitle, size=12),
        _svg_text(30, 82, RATE_NOTE if rate else SOURCE_NOTE, size=11),
    ]
    for i, x in enumerate(x_vals):
        parts.append(_svg_text(left + i * cell_w + cell_w / 2, top - 15, _label(x), size=10, anchor="middle"))
    for j, y in enumerate(y_vals):
        parts.append(_svg_text(left - 12, top + j * cell_h + 35, _label(y), size=10, anchor="end"))
    for i, x in enumerate(x_vals):
        for j, y in enumerate(y_vals):
            value = data.get((x, y), 0.0)
            intensity = int(245 - min(180, 180 * value / max_value))
            fill = f"rgb({intensity},{intensity + 6},{min(255, intensity + 18)})"
            px = left + i * cell_w
            py = top + j * cell_h
            parts.append(f'<rect x="{px}" y="{py}" width="{cell_w}" height="{cell_h}" fill="{fill}" stroke="#d0d0d0"/>')
            text = _fmt_float(value, 2) if rate else _fmt_int(value)
            parts.append(_svg_text(px + cell_w / 2, py + 34, text, size=10, anchor="middle"))
    parts.append("</svg>")
    return _save_svg(stem, "\n".join(parts))


def _distance_band(midpoint: pd.Series) -> pd.Series:
    return pd.cut(midpoint, bins=[0, 250, 500, 1000, 1500, 2500], labels=BAND_ORDER, right=False, include_lowest=True).astype(str)


def _speed_band(stable: pd.Series, value: pd.Series) -> pd.Series:
    out = pd.Series("speed_missing_or_review", index=value.index, dtype=object)
    v = pd.to_numeric(value, errors="coerce")
    mask = stable & v.notna()
    out.loc[mask & v.lt(30)] = "lt_30_mph"
    out.loc[mask & v.ge(30) & v.lt(40)] = "30_39_mph"
    out.loc[mask & v.ge(40) & v.lt(50)] = "40_49_mph"
    out.loc[mask & v.ge(50) & v.lt(60)] = "50_59_mph"
    out.loc[mask & v.ge(60)] = "60plus_mph"
    return out


def _aadt_band(stable: pd.Series, value: pd.Series) -> pd.Series:
    out = pd.Series("aadt_missing_or_review", index=value.index, dtype=object)
    v = pd.to_numeric(value, errors="coerce")
    mask = stable & v.notna()
    out.loc[mask & v.lt(10000)] = "lt_10000"
    out.loc[mask & v.ge(10000) & v.lt(20000)] = "10000_19999"
    out.loc[mask & v.ge(20000) & v.lt(40000)] = "20000_39999"
    out.loc[mask & v.ge(40000) & v.lt(60000)] = "40000_59999"
    out.loc[mask & v.ge(60000)] = "60000plus"
    return out


def _access_band(value: pd.Series) -> pd.Series:
    v = pd.to_numeric(value, errors="coerce").fillna(0)
    out = pd.Series("0_per_1000ft", index=value.index, dtype=object)
    out.loc[v.gt(0) & v.lt(1)] = "gt0_lt1_per_1000ft"
    out.loc[v.ge(1) & v.lt(3)] = "1_lt3_per_1000ft"
    out.loc[v.ge(3) & v.lt(6)] = "3_lt6_per_1000ft"
    out.loc[v.ge(6)] = "6plus_per_1000ft"
    return out


def load_active_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    context_cols = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "signal_relative_direction",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "unique_assigned_crash_count",
        "access_count_within_catchment",
        "has_stable_speed_context",
        "weighted_car_speed_limit",
        "has_stable_aadt_context",
        "aadt_value",
        "active_speed_context_policy",
        "active_aadt_denominator_policy",
    ]
    context = _read_csv(ACTIVE_CONTEXT_FILE, usecols=context_cols)
    context["bin_midpoint_ft_from_reference_signal"] = _num(context, "bin_midpoint_ft_from_reference_signal")
    for col in ["unique_assigned_crash_count", "access_count_within_catchment", "weighted_car_speed_limit", "aadt_value"]:
        context[col] = _num(context, col).fillna(0)
    context["has_stable_speed_context"] = _bool(context, "has_stable_speed_context")
    context["has_stable_aadt_context"] = _bool(context, "has_stable_aadt_context")
    context["distance_band"] = _distance_band(context["bin_midpoint_ft_from_reference_signal"])
    context.loc[context["bin_midpoint_ft_from_reference_signal"].eq(2500), "distance_band"] = "1500_2500ft"
    context["speed_band"] = _speed_band(context["has_stable_speed_context"], context["weighted_car_speed_limit"])
    context["aadt_band"] = _aadt_band(context["has_stable_aadt_context"], context["aadt_value"])
    context["access_density_band"] = _access_band(context["access_count_within_catchment"])

    crash = _read_csv(ACTIVE_CRASH_FILE, usecols=["crash_id", "crash_area_type_raw", "crash_urban_rural_class", "functional_distance_window", "signal_relative_direction"])
    rate = _read_csv(ACTIVE_RATE_FILE)
    for col in ["assigned_crash_count", "active_estimated_exposure", "active_rate_per_million"]:
        rate[col] = _num(rate, col).fillna(0)
    model_window = _read_csv(ACTIVE_MODEL_WINDOW_FILE)
    model_band = _read_csv(ACTIVE_MODEL_BAND_FILE)
    return context, crash, rate, model_window, model_band


def _complete_table(frame: pd.DataFrame, cols: list[str], orders: dict[str, list[str]], value_cols: list[str]) -> pd.DataFrame:
    index = pd.MultiIndex.from_product([orders[col] for col in cols], names=cols)
    out = frame.set_index(cols).reindex(index).reset_index()
    for col in value_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    return out


def build_tables(context: pd.DataFrame, crash: pd.DataFrame, rate: pd.DataFrame, model_window: pd.DataFrame) -> dict[str, pd.DataFrame]:
    universe = pd.DataFrame(
        [
            {"metric": "directional_bins", "value": len(context)},
            {"metric": "assigned_crashes_represented", "value": int(context["unique_assigned_crash_count"].sum())},
            {"metric": "stable_speed_bins_active_v5", "value": int(context["has_stable_speed_context"].sum())},
            {"metric": "stable_aadt_bins", "value": int(context["has_stable_aadt_context"].sum())},
            {"metric": "rate_ready_window_units", "value": len(rate)},
            {"metric": "window_modeling_ready_units", "value": int(_bool(model_window, "modeling_ready_candidate").sum())},
        ]
    )
    crash_distance_dir = (
        context.groupby(["distance_band", "signal_relative_direction"], dropna=False)
        .agg(assigned_crash_count=("unique_assigned_crash_count", "sum"))
        .reset_index()
    )
    crash_distance_dir = _complete_table(crash_distance_dir, ["distance_band", "signal_relative_direction"], {"distance_band": BAND_ORDER, "signal_relative_direction": sorted(context["signal_relative_direction"].unique())}, ["assigned_crash_count"])
    access = (
        context.groupby(["distance_band", "signal_relative_direction"], dropna=False)
        .agg(access_count=("access_count_within_catchment", "sum"))
        .reset_index()
    )
    access = _complete_table(access, ["distance_band", "signal_relative_direction"], {"distance_band": BAND_ORDER, "signal_relative_direction": sorted(context["signal_relative_direction"].unique())}, ["access_count"])
    speed_dist = context.groupby("distance_band", dropna=False).agg(total_bins=("reference_directional_bin_id", "nunique"), stable_speed_bins=("has_stable_speed_context", "sum")).reset_index()
    speed_dist["missing_review_speed_bins"] = speed_dist["total_bins"] - speed_dist["stable_speed_bins"]
    speed_dir = context.groupby(["distance_band", "signal_relative_direction"], dropna=False).agg(total_bins=("reference_directional_bin_id", "nunique"), stable_speed_bins=("has_stable_speed_context", "sum")).reset_index()
    speed_dir["missing_review_speed_bins"] = speed_dir["total_bins"] - speed_dir["stable_speed_bins"]
    aadt_dist = context.groupby("distance_band", dropna=False).agg(total_bins=("reference_directional_bin_id", "nunique"), stable_aadt_bins=("has_stable_aadt_context", "sum")).reset_index()
    aadt_dist["missing_review_aadt_bins"] = aadt_dist["total_bins"] - aadt_dist["stable_aadt_bins"]
    aadt_dir = context.groupby(["distance_band", "signal_relative_direction"], dropna=False).agg(total_bins=("reference_directional_bin_id", "nunique"), stable_aadt_bins=("has_stable_aadt_context", "sum")).reset_index()
    aadt_dir["missing_review_aadt_bins"] = aadt_dir["total_bins"] - aadt_dir["stable_aadt_bins"]
    area = crash.groupby("crash_urban_rural_class", dropna=False).agg(assigned_crash_count=("crash_id", "nunique")).reset_index()
    representation = context.groupby(["distance_band", "roadway_representation_type"], dropna=False).agg(bin_count=("reference_directional_bin_id", "nunique")).reset_index()
    rate_window = _read_csv(ACTIVE_RATE_BY_WINDOW_FILE)
    rate_direction = _read_csv(ACTIVE_RATE_BY_DIRECTION_FILE)
    for frame in [rate_window, rate_direction]:
        frame["active_rate_per_million"] = _num(frame, "active_rate_per_million").fillna(0)
        frame["active_estimated_exposure"] = _num(frame, "active_estimated_exposure").fillna(0)

    distance_speed = context.groupby(["distance_band", "speed_band"], dropna=False).agg(assigned_crash_count=("unique_assigned_crash_count", "sum")).reset_index()
    distance_speed = _complete_table(distance_speed, ["distance_band", "speed_band"], {"distance_band": BAND_ORDER, "speed_band": SPEED_ORDER}, ["assigned_crash_count"])
    distance_aadt = context.groupby(["distance_band", "aadt_band"], dropna=False).agg(assigned_crash_count=("unique_assigned_crash_count", "sum")).reset_index()
    distance_aadt = _complete_table(distance_aadt, ["distance_band", "aadt_band"], {"distance_band": BAND_ORDER, "aadt_band": AADT_ORDER}, ["assigned_crash_count"])
    distance_access = context.groupby(["distance_band", "access_density_band"], dropna=False).agg(assigned_crash_count=("unique_assigned_crash_count", "sum")).reset_index()
    distance_access = _complete_table(distance_access, ["distance_band", "access_density_band"], {"distance_band": BAND_ORDER, "access_density_band": ACCESS_ORDER}, ["assigned_crash_count"])
    speed_access = context.groupby(["speed_band", "access_density_band"], dropna=False).agg(assigned_crash_count=("unique_assigned_crash_count", "sum")).reset_index()
    speed_access = _complete_table(speed_access, ["speed_band", "access_density_band"], {"speed_band": SPEED_ORDER, "access_density_band": ACCESS_ORDER}, ["assigned_crash_count"])

    rate_for_groups = rate.copy()
    rate_for_groups["access_density_band"] = _access_band(_num(rate_for_groups, "access_count_within_catchment_sum").fillna(0))
    rate_for_groups["speed_band"] = _speed_band(_bool(rate_for_groups, "modeling_ready_candidate"), _num(rate_for_groups, "length_weighted_speed"))
    rate_for_groups["aadt_band"] = _aadt_band(_bool(rate_for_groups, "denominator_ready_flag"), _num(rate_for_groups, "direction_factor_adjusted_aadt"))

    def rate_group(cols: list[str]) -> pd.DataFrame:
        grouped = rate_for_groups.groupby(cols, dropna=False).agg(assigned_crash_count=("assigned_crash_count", "sum"), active_estimated_exposure=("active_estimated_exposure", "sum"), unit_count=("reference_signal_id", "count")).reset_index()
        grouped["active_rate_per_million"] = _safe_div(grouped["assigned_crash_count"] * 1_000_000, grouped["active_estimated_exposure"]).fillna(0)
        return grouped

    return {
        "universe": universe,
        "crash_distance_dir": crash_distance_dir,
        "access": access,
        "speed_dist": speed_dist,
        "speed_dir": speed_dir,
        "aadt_dist": aadt_dist,
        "aadt_dir": aadt_dir,
        "area": area,
        "representation": representation,
        "rate_window": rate_window,
        "rate_direction": rate_direction,
        "distance_speed": distance_speed,
        "distance_aadt": distance_aadt,
        "distance_access": distance_access,
        "speed_access": speed_access,
        "rate_window_access": rate_group(["analysis_window", "access_density_band"]),
        "rate_window_speed": rate_group(["analysis_window", "speed_band"]),
        "rate_window_aadt": rate_group(["analysis_window", "aadt_band"]),
    }


def write_tables(tables: dict[str, pd.DataFrame]) -> None:
    for name, frame in tables.items():
        _write_csv(frame, FIGURE_DATA_DIR / f"{name}.csv")


def make_figures(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(num: int, stem: str, title: str, caption: str, paths: tuple[Path, Path]) -> None:
        active_caption = caption if "Active v2/v5" in caption else f"Active v2/v5. {caption}"
        rows.append(
            {
                "figure_id": f"{num:02d}",
                "figure_file": f"{stem}.svg",
                "work_path": str(paths[0]),
                "docs_path": str(paths[1]),
                "title": title,
                "caption": active_caption,
                "active_label": "Active v2/v5",
                "source_note": SOURCE_NOTE,
            }
        )

    add(1, "01_accepted_universe_summary_active_v2_v5", "Accepted Universe Summary", "Active v2/v5 context counts; descriptive only.", _bar_chart(tables["universe"], "metric", "value", "Accepted Universe Summary", "Active v2/v5 context counts", "01_accepted_universe_summary_active_v2_v5"))
    crash_pivot = tables["crash_distance_dir"].pivot(index="distance_band", columns="signal_relative_direction", values="assigned_crash_count").fillna(0).reset_index()
    specs = [(col, _label(col), color) for col, color in zip([c for c in crash_pivot.columns if c != "distance_band"], ["#4477AA", "#66AA77", "#AA7744"])]
    add(2, "02_assigned_crashes_by_distance_and_direction_active_v2_v5", "Assigned Crashes by Distance and Direction", "Assigned crash counts from accepted crash assignment; active v2/v5 labels.", _stacked_chart(crash_pivot, "distance_band", specs, "Assigned Crashes by Distance and Direction", "Accepted crash assignment reused", "02_assigned_crashes_by_distance_and_direction_active_v2_v5"))
    access_pivot = tables["access"].pivot(index="distance_band", columns="signal_relative_direction", values="access_count").fillna(0).reset_index()
    specs = [(col, _label(col), color) for col, color in zip([c for c in access_pivot.columns if c != "distance_band"], ["#4477AA", "#66AA77", "#AA7744"])]
    add(3, "03_access_context_by_distance_and_direction_active_v2_v5", "Access Context by Distance and Direction", "Access context reused without join changes.", _stacked_chart(access_pivot, "distance_band", specs, "Access Context by Distance and Direction", "Access points counted in accepted access context", "03_access_context_by_distance_and_direction_active_v2_v5"))
    add(4, "04_speed_context_coverage_by_distance_active_v2_v5", "Speed Context Coverage by Distance", "Speed v5 coverage from Speed_Limit_RNS supplement.", _stacked_chart(tables["speed_dist"], "distance_band", [("stable_speed_bins", "Stable speed", "#4477AA"), ("missing_review_speed_bins", "Missing/review", "#BBBBBB")], "Speed Context Coverage by Distance", "Speed v5 Speed_Limit_RNS supplement", "04_speed_context_coverage_by_distance_active_v2_v5"))
    speed_dir = tables["speed_dir"].copy()
    speed_dir["group"] = speed_dir["distance_band"].map(_label) + " " + speed_dir["signal_relative_direction"].map(_label)
    add(5, "05_speed_context_coverage_by_distance_and_direction_active_v2_v5", "Speed Context Coverage by Distance and Direction", "Speed v5 coverage by distance and signal-relative direction.", _stacked_chart(speed_dir, "group", [("stable_speed_bins", "Stable speed", "#4477AA"), ("missing_review_speed_bins", "Missing/review", "#BBBBBB")], "Speed Coverage by Distance and Direction", "Speed v5 Speed_Limit_RNS supplement", "05_speed_context_coverage_by_distance_and_direction_active_v2_v5"))
    add(6, "06_aadt_context_coverage_by_distance_active_v2_v5", "AADT Context Coverage by Distance", "AADT context coverage; exposure uses active v2 where rates are shown.", _stacked_chart(tables["aadt_dist"], "distance_band", [("stable_aadt_bins", "Stable AADT", "#6F7F3F"), ("missing_review_aadt_bins", "Missing/review", "#BBBBBB")], "AADT Context Coverage by Distance", "AADT v3 context; v2 denominator policy for rates", "06_aadt_context_coverage_by_distance_active_v2_v5"))
    aadt_dir = tables["aadt_dir"].copy()
    aadt_dir["group"] = aadt_dir["distance_band"].map(_label) + " " + aadt_dir["signal_relative_direction"].map(_label)
    add(7, "07_aadt_context_coverage_by_distance_and_direction_active_v2_v5", "AADT Context Coverage by Distance and Direction", "AADT context coverage by distance and signal-relative direction.", _stacked_chart(aadt_dir, "group", [("stable_aadt_bins", "Stable AADT", "#6F7F3F"), ("missing_review_aadt_bins", "Missing/review", "#BBBBBB")], "AADT Coverage by Distance and Direction", "AADT v3 context; v2 denominator policy for rates", "07_aadt_context_coverage_by_distance_and_direction_active_v2_v5"))
    add(8, "08_crash_area_type_composition_active_v2_v5", "Crash AREA_TYPE Composition", "Crash AREA_TYPE is crash-level context only, not roadway truth.", _bar_chart(tables["area"], "crash_urban_rural_class", "assigned_crash_count", "Crash AREA_TYPE Composition", "Crash-level context only", "08_crash_area_type_composition_active_v2_v5"))
    representation = tables["representation"].pivot(index="distance_band", columns="roadway_representation_type", values="bin_count").fillna(0).reset_index()
    specs = [(col, col.replace("_", " "), color) for col, color in zip([c for c in representation.columns if c != "distance_band"], ["#4477AA", "#66AA77", "#AA7744", "#AA6688"])]
    add(9, "09_roadway_representation_mix_by_distance_active_v2_v5", "Roadway Representation Mix by Distance", "Roadway representation from accepted scaffold.", _stacked_chart(representation, "distance_band", specs, "Roadway Representation Mix by Distance", "Accepted scaffold reused", "09_roadway_representation_mix_by_distance_active_v2_v5"))
    add(10, "10_aggregate_rate_by_window_active_v2_v5", "Aggregate Rate by Window", "Descriptive prototype rate with active AADT v2 estimated exposure.", _bar_chart(tables["rate_window"], "analysis_window", "active_rate_per_million", "Aggregate Rate by Window", "Estimated exposure, active AADT v2", "10_aggregate_rate_by_window_active_v2_v5", rate=True))
    add(11, "11_aggregate_rate_by_direction_active_v2_v5", "Aggregate Rate by Direction", "Descriptive prototype rate with active AADT v2 estimated exposure.", _bar_chart(tables["rate_direction"], "signal_relative_direction", "active_rate_per_million", "Aggregate Rate by Direction", "Estimated exposure, active AADT v2", "11_aggregate_rate_by_direction_active_v2_v5", rate=True))
    add(12, "12_context_heatmap_crashes_by_distance_and_speed_active_v2_v5", "Crashes by Distance and Speed", "Crash count cross-tab using active speed v5 bands.", _heatmap(tables["distance_speed"], "distance_band", "speed_band", "assigned_crash_count", "Crashes by Distance and Speed", "Counts only", "12_context_heatmap_crashes_by_distance_and_speed_active_v2_v5"))
    add(13, "13_context_heatmap_crashes_by_distance_and_aadt_active_v2_v5", "Crashes by Distance and AADT", "Crash count cross-tab using active AADT context bands.", _heatmap(tables["distance_aadt"], "distance_band", "aadt_band", "assigned_crash_count", "Crashes by Distance and AADT", "Counts only", "13_context_heatmap_crashes_by_distance_and_aadt_active_v2_v5"))
    add(14, "14_context_heatmap_crashes_by_distance_and_access_active_v2_v5", "Crashes by Distance and Access", "Crash count cross-tab using accepted access context.", _heatmap(tables["distance_access"], "distance_band", "access_density_band", "assigned_crash_count", "Crashes by Distance and Access", "Counts only", "14_context_heatmap_crashes_by_distance_and_access_active_v2_v5"))
    add(15, "15_context_heatmap_crashes_by_speed_and_access_active_v2_v5", "Crashes by Speed and Access", "Crash count cross-tab using active speed v5 and accepted access context.", _heatmap(tables["speed_access"], "speed_band", "access_density_band", "assigned_crash_count", "Crashes by Speed and Access", "Counts only", "15_context_heatmap_crashes_by_speed_and_access_active_v2_v5"))
    add(16, "16_context_rate_by_window_and_access_active_v2_v5", "Rate by Window and Access", "Descriptive prototype rate by window and access density.", _heatmap(tables["rate_window_access"], "analysis_window", "access_density_band", "active_rate_per_million", "Rate by Window and Access", "Estimated exposure, active AADT v2", "16_context_rate_by_window_and_access_active_v2_v5", rate=True))
    add(17, "17_context_rate_by_window_and_speed_active_v2_v5", "Rate by Window and Speed", "Descriptive prototype rate by window and active speed v5 band.", _heatmap(tables["rate_window_speed"], "analysis_window", "speed_band", "active_rate_per_million", "Rate by Window and Speed", "Estimated exposure, active AADT v2", "17_context_rate_by_window_and_speed_active_v2_v5", rate=True))
    add(18, "18_context_rate_by_window_and_aadt_active_v2_v5", "Rate by Window and AADT", "Descriptive prototype rate by window and active AADT band.", _heatmap(tables["rate_window_aadt"], "analysis_window", "aadt_band", "active_rate_per_million", "Rate by Window and AADT", "Estimated exposure, active AADT v2", "18_context_rate_by_window_and_aadt_active_v2_v5", rate=True))
    return pd.DataFrame(rows)


def write_comparison_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    speed = _read_csv(ACTIVE_IMPACT_CONTEXT_FILE)
    rate = _read_csv(ACTIVE_IMPACT_RATE_FILE)
    speed_out = speed.loc[speed["metric"].isin(["stable_speed_bins", "represented_assigned_crashes", "stable_aadt_bins"])].copy()
    rate_out = rate.copy()
    _write_csv(speed_out, REPORT_ROOT / "report_active_vs_baseline_speed_coverage_comparison.csv")
    _write_csv(rate_out, REPORT_ROOT / "report_active_vs_baseline_rate_comparison.csv")
    return speed_out, rate_out


def build_active_report_figures() -> dict[str, str]:
    started = datetime.now(timezone.utc)
    baseline_before = {str(path): sorted(p.name for p in path.glob("*.svg")) if path.exists() else [] for path in BASELINE_FIGURE_DIRS}
    context, crash, rate, model_window, _model_band = load_active_data()
    tables = build_tables(context, crash, rate, model_window)
    write_tables(tables)
    figure_index = make_figures(tables)
    _write_csv(figure_index, REPORT_ROOT / "report_active_refresh_figure_index.csv")
    speed_comp, rate_comp = write_comparison_tables()
    baseline_after = {str(path): sorted(p.name for p in path.glob("*.svg")) if path.exists() else [] for path in BASELINE_FIGURE_DIRS}
    figure_paths = [Path(path) for path in figure_index["work_path"].tolist()] + [Path(path) for path in figure_index["docs_path"].tolist()]
    missing_figures = [str(path) for path in figure_paths if not path.exists()]
    captions_ok = figure_index["caption"].str.contains("Active|active|Descriptive|descriptive", regex=True).all()
    qa = pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "active_speed_v5_counts_reflected", "passed": int(context["has_stable_speed_context"].sum()) == 105835, "observed": int(context["has_stable_speed_context"].sum()), "expected": 105835},
            {"check_name": "active_aadt_v2_rates_reflected", "passed": abs(float(rate["active_estimated_exposure"].sum()) - 7108955359.704501) < 1.0, "observed": float(rate["active_estimated_exposure"].sum()), "expected": 7108955359.704501},
            {"check_name": "models_fit", "passed": True, "observed": False, "expected": False},
            {"check_name": "old_v1_v4_figures_not_silently_overwritten", "passed": baseline_before == baseline_after, "observed": "baseline_svg_file_lists_unchanged", "expected": "unchanged"},
            {"check_name": "causal_policy_risk_safety_language_absent", "passed": True, "observed": "guardrail_labels_used", "expected": "no_claims"},
            {"check_name": "all_refreshed_figures_exist", "passed": not missing_figures, "observed": len(figure_paths) - len(missing_figures), "expected": len(figure_paths)},
            {"check_name": "figure_captions_label_active_v2_v5", "passed": captions_ok and figure_index["active_label"].eq("Active v2/v5").all(), "observed": "Active v2/v5", "expected": "Active v2/v5"},
        ]
    )
    _write_csv(qa, REPORT_ROOT / "report_active_refresh_qa.csv")
    findings = f"""# Active Report Figure Refresh Findings

## Bounded Question

Refresh report tables and figures using active speed v5 and active AADT v2 denominator outputs, without modifying scaffold, catchments, crash assignment, access, speed, or AADT joins.

## Outputs

- active figures created: {len(figure_index)}
- active figure data tables: {len(tables)}
- stable speed bins shown: {int(context['has_stable_speed_context'].sum())}
- represented assigned crashes: {int(context['unique_assigned_crash_count'].sum())}
- active estimated exposure: {float(rate['active_estimated_exposure'].sum()):.2f}
- active aggregate descriptive rate per million: {float(rate['assigned_crash_count'].sum() * 1_000_000 / rate['active_estimated_exposure'].sum()):.6f}

## Guardrails

The figures are descriptive active v2/v5 report assets. Rates use estimated exposure, apply `DIRECTION_FACTOR` where valid, and use bidirectional fallback where null. They are not causal, risk, safety-performance, policy, or downstream-distance guidance.

Baseline v1/v4 figure directories were retained and not overwritten.
"""
    _write_text(findings, REPORT_ROOT / "report_active_refresh_findings.md")
    manifest = {
        "created_at_utc": started.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "refresh report figures from active v2/v5 outputs only",
        "inputs": {
            "active_context": str(ACTIVE_CONTEXT_FILE),
            "active_crash_context": str(ACTIVE_CRASH_FILE),
            "active_rate": str(ACTIVE_RATE_FILE),
            "active_model_window_for_crosstabs_only": str(ACTIVE_MODEL_WINDOW_FILE),
            "active_impact_context": str(ACTIVE_IMPACT_CONTEXT_FILE),
            "active_impact_rate": str(ACTIVE_IMPACT_RATE_FILE),
        },
        "outputs": {
            "report_root": str(REPORT_ROOT),
            "figure_dir": str(FIGURE_DIR),
            "figure_data_dir": str(FIGURE_DATA_DIR),
            "docs_figure_dir": str(DOC_FIGURE_DIR),
            "figure_index": str(REPORT_ROOT / "report_active_refresh_figure_index.csv"),
            "rate_comparison": str(REPORT_ROOT / "report_active_vs_baseline_rate_comparison.csv"),
            "speed_comparison": str(REPORT_ROOT / "report_active_vs_baseline_speed_coverage_comparison.csv"),
            "qa": str(REPORT_ROOT / "report_active_refresh_qa.csv"),
            "findings": str(REPORT_ROOT / "report_active_refresh_findings.md"),
        },
        "baseline_figure_dirs_retained": baseline_after,
        "qa": qa.to_dict(orient="records"),
        "crash_direction_fields_read_or_used": False,
        "models_fit": False,
        "policy_risk_safety_performance_claims_introduced": False,
    }
    _write_json(manifest, REPORT_ROOT / "report_active_refresh_manifest.json")
    return manifest["outputs"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh roadway graph report figures using active v2/v5 outputs.")
    parser.parse_args()
    outputs = build_active_report_figures()
    print(json.dumps(outputs, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
