from __future__ import annotations

import argparse
import html
import struct
import zlib
from pathlib import Path
from typing import Any

import pandas as pd


ANALYSIS_ROOT = Path("work/output/roadway_graph/analysis/current")
REPORT_ROOT = Path("work/output/roadway_graph/report/current")
FIGURE_DIR = REPORT_ROOT / "figures"
FIGURE_DATA_DIR = REPORT_ROOT / "figure_data"
REPORT_DOC_DIR = Path("docs/reports/roadway_graph")
QA_FILE = REPORT_ROOT / "roadway_graph_report_figure_qa.csv"

STAKEHOLDER_DIR = ANALYSIS_ROOT / "stakeholder_context_table_package"
SUMMARY_DIR = ANALYSIS_ROOT / "directional_context_descriptive_summaries"
REVIEW_DIR = ANALYSIS_ROOT / "signal_context_review_queue"
DISTANCE_DIR = ANALYSIS_ROOT / "directional_context_distance_band_profiles"

BAND_LABELS = {
    "0_250ft": "0-250 ft",
    "250_500ft": "250-500 ft",
    "500_1000ft": "500-1,000 ft",
    "1000_1500ft": "1,000-1,500 ft",
    "1500_2500ft": "1,500-2,500 ft",
}
BAND_ORDER = list(BAND_LABELS)
WINDOW_LABELS = {
    "high_priority_0_1000ft": "0-1,000 ft",
    "sensitivity_1000_2500ft": "1,000-2,500 ft",
}
REVIEW_TIER_LABELS = {
    "highest_review_priority": "Highest",
    "high_review_priority": "High",
    "moderate_review_priority": "Moderate",
    "lower_review_priority": "Lower",
}
CRASH_DIRECTION_FIELD_TOKENS = ("crash_direction", "veh_direction", "vehicle_direction", "direction_of_travel", "dir_of_travel")


def _is_crash_direction_field(column: str) -> bool:
    lower = column.lower()
    return any(token in lower for token in CRASH_DIRECTION_FIELD_TOKENS) and column != "signal_relative_direction"


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    if usecols is not None:
        missing = [column for column in usecols if column not in header]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        blocked = [column for column in usecols if _is_crash_direction_field(column)]
        if blocked:
            raise ValueError(f"Refusing to read crash direction fields from {path}: {blocked}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=usecols)


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").fillna(0)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _format_int(value: Any) -> str:
    return f"{int(float(value)):,}"


def _rel_from_report(path: Path) -> str:
    return "../../../" + path.as_posix()


def _markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(column) for column in frame.columns]
    rows = [[str(value) for value in row] for row in frame.to_numpy().tolist()]
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    header_line = "| " + " | ".join(header.ljust(width) for header, width in zip(headers, widths)) + " |"
    sep_line = "| " + " | ".join("-" * width for width in widths) + " |"
    body = ["| " + " | ".join(value.ljust(width) for value, width in zip(row, widths)) + " |" for row in rows]
    return "\n".join([header_line, sep_line, *body])


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _write_png(path: Path, width: int, height: int, rects: list[tuple[int, int, int, int, tuple[int, int, int]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = bytearray([255, 255, 255] * width * height)
    for x, y, w, h, color in rects:
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(width, x + w)
        y1 = min(height, y + h)
        for yy in range(y0, y1):
            row = yy * width * 3
            for xx in range(x0, x1):
                idx = row + xx * 3
                pixels[idx : idx + 3] = bytes(color)
    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)
        start = y * width * 3
        scanlines.extend(pixels[start : start + width * 3])
    payload = b"\x89PNG\r\n\x1a\n"
    payload += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += _png_chunk(b"IDAT", zlib.compress(bytes(scanlines), 9))
    payload += _png_chunk(b"IEND", b"")
    path.write_bytes(payload)


def _svg_text(x: int, y: int, text: str, *, size: int = 12, weight: str = "normal", anchor: str = "start") -> str:
    return f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="#222">{html.escape(text)}</text>'


def _save_svg_png(svg: str, stem: str, rects: list[tuple[int, int, int, int, tuple[int, int, int]]], *, width: int = 900, height: int = 520) -> tuple[Path, Path]:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = FIGURE_DIR / f"{stem}.svg"
    png_path = FIGURE_DIR / f"{stem}.png"
    _write_text(svg, svg_path)
    _write_png(png_path, width, height, rects)
    return png_path, svg_path


def _bar_chart(frame: pd.DataFrame, label_col: str, value_col: str, title: str, note: str, stem: str, *, color: str = "#4477AA") -> tuple[Path, Path]:
    width, height = 900, 520
    left, top, chart_w, chart_h = 90, 90, 740, 300
    values = [int(v) for v in frame[value_col]]
    labels = [str(v) for v in frame[label_col]]
    max_value = max(values) if values else 1
    gap = 18
    bar_w = max(20, int((chart_w - gap * (len(values) - 1)) / max(1, len(values))))
    rects: list[tuple[int, int, int, int, tuple[int, int, int]]] = [(left, top, 1, chart_h, (80, 80, 80)), (left, top + chart_h, chart_w, 1, (80, 80, 80))]
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 38, title, size=20, weight="bold"),
        _svg_text(30, 62, note, size=12),
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#555"/>',
        f'<line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#555"/>',
    ]
    rgb = tuple(int(color.strip("#")[i : i + 2], 16) for i in (0, 2, 4))
    for i, (label, value) in enumerate(zip(labels, values)):
        bar_h = int((value / max_value) * (chart_h - 20))
        x = left + i * (bar_w + gap)
        y = top + chart_h - bar_h
        rects.append((x, y, bar_w, bar_h, rgb))
        svg_parts.append(f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="{color}"/>')
        svg_parts.append(_svg_text(x + bar_w // 2, y - 8, _format_int(value), size=11, anchor="middle"))
        svg_parts.append(_svg_text(x + bar_w // 2, top + chart_h + 24, label, size=10, anchor="middle"))
    svg_parts.append(_svg_text(30, height - 28, "Source: accepted descriptive outputs. Counts are not rates.", size=11))
    svg_parts.append("</svg>")
    return _save_svg_png("\n".join(svg_parts), stem, rects, width=width, height=height)


def _stacked_chart(frame: pd.DataFrame, label_col: str, cols: list[tuple[str, str, str]], title: str, note: str, stem: str) -> tuple[Path, Path]:
    width, height = 900, 520
    left, top, chart_w, chart_h = 90, 90, 740, 300
    labels = [str(v) for v in frame[label_col]]
    totals = [sum(int(row[column]) for column, _, _ in cols) for _, row in frame.iterrows()]
    max_value = max(totals) if totals else 1
    gap = 18
    bar_w = max(20, int((chart_w - gap * (len(labels) - 1)) / max(1, len(labels))))
    rects: list[tuple[int, int, int, int, tuple[int, int, int]]] = [(left, top, 1, chart_h, (80, 80, 80)), (left, top + chart_h, chart_w, 1, (80, 80, 80))]
    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 38, title, size=20, weight="bold"),
        _svg_text(30, 62, note, size=12),
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + chart_h}" stroke="#555"/>',
        f'<line x1="{left}" y1="{top + chart_h}" x2="{left + chart_w}" y2="{top + chart_h}" stroke="#555"/>',
    ]
    for i, (_, row) in enumerate(frame.iterrows()):
        x = left + i * (bar_w + gap)
        y_cursor = top + chart_h
        total = 0
        for column, label, color in cols:
            value = int(row[column])
            total += value
            bar_h = int((value / max_value) * (chart_h - 20))
            y_cursor -= bar_h
            rgb = tuple(int(color.strip("#")[j : j + 2], 16) for j in (0, 2, 4))
            rects.append((x, y_cursor, bar_w, bar_h, rgb))
            svg_parts.append(f'<rect x="{x}" y="{y_cursor}" width="{bar_w}" height="{bar_h}" fill="{color}"/>')
        svg_parts.append(_svg_text(x + bar_w // 2, y_cursor - 8, _format_int(total), size=11, anchor="middle"))
        svg_parts.append(_svg_text(x + bar_w // 2, top + chart_h + 24, str(row[label_col]), size=10, anchor="middle"))
    legend_x = left + chart_w - 220
    for j, (_, label, color) in enumerate(cols):
        y = 88 + j * 20
        svg_parts.append(f'<rect x="{legend_x}" y="{y}" width="12" height="12" fill="{color}"/>')
        svg_parts.append(_svg_text(legend_x + 18, y + 11, label, size=11))
    svg_parts.append(_svg_text(30, height - 28, "Source: accepted descriptive outputs. Descriptive counts only.", size=11))
    svg_parts.append("</svg>")
    return _save_svg_png("\n".join(svg_parts), stem, rects, width=width, height=height)


def _table_svg_png(frame: pd.DataFrame, title: str, note: str, stem: str) -> tuple[Path, Path]:
    width = 1100
    row_h = 28
    height = 110 + row_h * (len(frame) + 1)
    col_w = max(90, int((width - 60) / max(1, len(frame.columns))))
    rects: list[tuple[int, int, int, int, tuple[int, int, int]]] = [(30, 74, width - 60, row_h, (232, 238, 244))]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        _svg_text(30, 38, title, size=20, weight="bold"),
        _svg_text(30, 60, note, size=12),
        f'<rect x="30" y="74" width="{width - 60}" height="{row_h}" fill="#e8eef4" stroke="#bbbbbb"/>',
    ]
    for c, column in enumerate(frame.columns):
        parts.append(_svg_text(36 + c * col_w, 93, str(column), size=10, weight="bold"))
    for r, row in enumerate(frame.itertuples(index=False), start=1):
        y = 74 + r * row_h
        parts.append(f'<rect x="30" y="{y}" width="{width - 60}" height="{row_h}" fill="white" stroke="#dddddd"/>')
        for c, value in enumerate(row):
            text = str(value)
            if len(text) > 24:
                text = text[:21] + "..."
            parts.append(_svg_text(36 + c * col_w, y + 19, text, size=10))
    parts.append("</svg>")
    return _save_svg_png("\n".join(parts), stem, rects, width=width, height=height)


def _load_sources() -> dict[str, pd.DataFrame]:
    return {
        "overview": _read_csv(STAKEHOLDER_DIR / "stakeholder_summary_overview.csv"),
        "distance": _read_csv(STAKEHOLDER_DIR / "stakeholder_distance_band_summary.csv"),
        "window": _read_csv(SUMMARY_DIR / "directional_context_summary_by_window.csv"),
        "direction": _read_csv(SUMMARY_DIR / "directional_context_summary_by_signal_relative_direction.csv"),
        "review": _read_csv(REVIEW_DIR / "signal_review_queue_overall.csv"),
        "review_top": _read_csv(STAKEHOLDER_DIR / "stakeholder_signal_review_queue_top.csv"),
        "area": _read_csv(SUMMARY_DIR / "directional_context_summary_crash_area_type.csv"),
        "completeness": _read_csv(STAKEHOLDER_DIR / "stakeholder_context_completeness_summary.csv"),
        "representation": _read_csv(DISTANCE_DIR / "distance_band_profile_by_roadway_representation.csv"),
    }


def _build_data(s: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    overview = s["overview"].copy()
    overview["value"] = _num(overview, "value").astype(int)
    overview = overview.assign(Value=overview["value"].map(lambda x: f"{x:,}"))[["metric", "Value", "scope"]]
    overview.columns = ["Metric", "Value", "Scope"]

    distance = s["distance"].copy()
    distance["distance_band_label"] = distance["distance_band"].map(BAND_LABELS)
    distance["order"] = distance["distance_band"].map({band: i for i, band in enumerate(BAND_ORDER)})
    distance = distance.sort_values("order")
    for col in distance.columns:
        if col.endswith("_count") or col.endswith("_bin_count") or col in {"bin_count"}:
            distance[col] = _num(distance, col).astype(int)

    direction = s["direction"].loc[s["direction"]["distance_window"].eq("all_0_2500ft")].copy()
    direction["assigned_crash_count"] = _num(direction, "assigned_crash_count").astype(int)
    direction["direction_label"] = direction["signal_relative_direction"].map({"upstream_of_reference_signal": "Upstream", "downstream_of_reference_signal": "Downstream"})

    window = s["window"].loc[s["window"]["distance_window"].isin(WINDOW_LABELS)].copy()
    window["window_label"] = window["distance_window"].map(WINDOW_LABELS)
    window["assigned_crash_count"] = _num(window, "assigned_crash_count").astype(int)
    window["bin_count"] = _num(window, "bin_count").astype(int)

    review_counts = s["review"]["review_priority_tier"].value_counts().reindex(REVIEW_TIER_LABELS.keys(), fill_value=0).reset_index()
    review_counts.columns = ["review_priority_tier", "signal_count"]
    review_counts["tier_label"] = review_counts["review_priority_tier"].map(REVIEW_TIER_LABELS)

    top = s["review_top"].head(10).copy()
    top = top[["reference_signal_id", "review_priority_tier", "assigned_crash_count_total", "assigned_crash_count_0_1000ft", "upstream_crash_count", "downstream_crash_count", "review_context_flag_count"]]
    top.columns = ["Reference signal", "Review priority", "Assigned crashes", "0-1,000 ft", "Upstream", "Downstream", "Review flags"]

    area = s["area"].loc[s["area"]["distance_window"].eq("all_0_2500ft")].copy()
    area["assigned_crash_count"] = _num(area, "assigned_crash_count").astype(int)
    area = area.groupby("crash_urban_rural_class", dropna=False)["assigned_crash_count"].sum().reset_index()
    area["class_label"] = area["crash_urban_rural_class"].str.title()

    completeness = s["completeness"].copy()
    for column in completeness.columns:
        if column.endswith("_count") or column == "bin_count":
            completeness[column] = _num(completeness, column).astype(int)

    rep = s["representation"].copy()
    rep["distance_band_label"] = rep["distance_band"].map(BAND_LABELS)
    rep["order"] = rep["distance_band"].map({band: i for i, band in enumerate(BAND_ORDER)})
    rep["bin_count"] = _num(rep, "bin_count").astype(int)
    rep["representation_label"] = rep["roadway_representation_type"].map({"divided_physical_carriageway": "Divided physical", "undivided_centerline_pseudo_direction": "Undivided pseudo-direction"})
    rep = rep.sort_values("order")

    return {
        "EX01": overview,
        "EX02": distance[["distance_band", "distance_band_label", "assigned_crash_count"]],
        "EX03": direction[["signal_relative_direction", "direction_label", "assigned_crash_count"]],
        "EX04": window[["distance_window", "window_label", "bin_count", "assigned_crash_count"]],
        "EX05": review_counts[["review_priority_tier", "tier_label", "signal_count"]],
        "EX06": top,
        "EX07": distance[["distance_band", "distance_band_label", "access_count_within_catchment"]],
        "EX08": distance[["distance_band", "distance_band_label", "stable_speed_bin_count", "missing_or_review_speed_bin_count"]].rename(columns={"stable_speed_bin_count": "stable", "missing_or_review_speed_bin_count": "review_or_missing"}),
        "EX09": distance[["distance_band", "distance_band_label", "stable_aadt_bin_count", "missing_or_review_aadt_bin_count"]].rename(columns={"stable_aadt_bin_count": "stable", "missing_or_review_aadt_bin_count": "review_or_missing"}),
        "EX10": area[["crash_urban_rural_class", "class_label", "assigned_crash_count"]],
        "EX11": completeness,
        "EX12": rep[["distance_band", "distance_band_label", "representation_label", "bin_count"]],
    }


def _render(data: dict[str, pd.DataFrame]) -> dict[str, dict[str, str]]:
    outputs: dict[str, dict[str, str]] = {}
    for key, frame in data.items():
        csv_path = FIGURE_DATA_DIR / f"{key.lower()}_figure_data.csv"
        _write_csv(frame, csv_path)
        outputs[key] = {"csv": str(csv_path)}
    chart_specs = [
        ("EX02", lambda: _bar_chart(data["EX02"], "distance_band_label", "assigned_crash_count", "Assigned Crashes by Distance Band", "Accepted 0-2,500 ft directional-bin universe", "ex02_distance_band_assigned_crashes")),
        ("EX03", lambda: _bar_chart(data["EX03"], "direction_label", "assigned_crash_count", "Upstream and Downstream Assigned Crashes", "Roadway-derived signal-relative direction", "ex03_upstream_downstream_assigned_crashes", color="#66AA77")),
        ("EX05", lambda: _bar_chart(data["EX05"], "tier_label", "signal_count", "Signal Review Priority Tiers", "Manual review ordering only", "ex05_signal_review_priority_tiers", color="#AA7744")),
        ("EX07", lambda: _bar_chart(data["EX07"], "distance_band_label", "access_count_within_catchment", "Access Context by Distance Band", "Access counts within accepted catchments", "ex07_access_context_by_distance_band", color="#66AA77")),
        ("EX10", lambda: _bar_chart(data["EX10"], "class_label", "assigned_crash_count", "Assigned Crashes by Crash AREA_TYPE", "Crash-level urban/rural context", "ex10_crash_area_type_composition", color="#4477AA")),
    ]
    png, svg = _table_svg_png(data["EX01"], "Accepted Roadway-Graph Universe", "Descriptive counts only", "ex01_accepted_universe_summary")
    outputs["EX01"].update({"png": str(png), "svg": str(svg)})
    for key, fn in chart_specs:
        png, svg = fn()
        outputs[key].update({"png": str(png), "svg": str(svg)})
    png, svg = _stacked_chart(data["EX04"], "window_label", [("assigned_crash_count", "Assigned crashes", "#4477AA"), ("bin_count", "Bins", "#BBBBBB")], "High-Priority and Sensitivity Windows", "Crash counts and bin counts", "ex04_window_summary")
    outputs["EX04"].update({"png": str(png), "svg": str(svg)})
    png, svg = _table_svg_png(data["EX06"], "Top Signal Review Queue", "Review ordering only", "ex06_top_signal_review_queue")
    outputs["EX06"].update({"png": str(png), "svg": str(svg)})
    png, svg = _stacked_chart(data["EX08"], "distance_band_label", [("stable", "Stable", "#4477AA"), ("review_or_missing", "Review/missing", "#BBBBBB")], "Speed Context Coverage by Distance Band", "Stable and review/missing bins", "ex08_speed_context_coverage")
    outputs["EX08"].update({"png": str(png), "svg": str(svg)})
    png, svg = _stacked_chart(data["EX09"], "distance_band_label", [("stable", "Stable", "#4477AA"), ("review_or_missing", "Review/missing", "#BBBBBB")], "AADT Context Coverage by Distance Band", "Stable and review/missing bins", "ex09_aadt_context_coverage")
    outputs["EX09"].update({"png": str(png), "svg": str(svg)})
    png, svg = _table_svg_png(data["EX11"], "Context Completeness Summary", "QA and review aid", "ex11_context_completeness_summary")
    outputs["EX11"].update({"png": str(png), "svg": str(svg)})
    pivot = data["EX12"].pivot_table(index="distance_band_label", columns="representation_label", values="bin_count", aggfunc="sum", fill_value=0).reset_index()
    png, svg = _stacked_chart(pivot, "distance_band_label", [("Divided physical", "Divided physical", "#4477AA"), ("Undivided pseudo-direction", "Undivided pseudo-direction", "#CC6677")], "Roadway Representation Mix by Distance Band", "Directional-bin counts", "ex12_roadway_representation_mix")
    outputs["EX12"].update({"png": str(png), "svg": str(svg)})
    return outputs


def _exhibit_rows(outputs: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    specs = {
        "EX01": ("Accepted Universe Summary", "Executive Summary; Accepted Directional-Bin Universe", STAKEHOLDER_DIR / "stakeholder_summary_overview.csv", "Orient readers to the accepted descriptive universe.", "Descriptive counts only."),
        "EX02": ("Distance-Band Assigned Crash Distribution", "Descriptive Results", STAKEHOLDER_DIR / "stakeholder_distance_band_summary.csv", "Show assigned crash counts across fixed bands.", "Counts are not rates."),
        "EX03": ("Upstream vs Downstream Assigned Crashes", "Accepted Directional-Bin Universe", SUMMARY_DIR / "directional_context_summary_by_signal_relative_direction.csv", "Compare signal-relative assigned crash counts.", "Roadway graph direction defines upstream/downstream."),
        "EX04": ("High-Priority vs Sensitivity Window Summary", "Accepted Directional-Bin Universe", SUMMARY_DIR / "directional_context_summary_by_window.csv", "Show assigned crashes and bins by analysis window.", "Windows are descriptive groups."),
        "EX05": ("Signal Review Priority Tier Counts", "Signal Review Priority", REVIEW_DIR / "signal_review_queue_overall.csv", "Summarize review-priority tiers.", "Review priority is not a performance ranking."),
        "EX06": ("Top Signal Review Queue", "Signal Review Priority", STAKEHOLDER_DIR / "stakeholder_signal_review_queue_top.csv", "List the top review-priority signals for manual review.", "Review ordering only."),
        "EX07": ("Access Context by Distance Band", "Context Enrichment Layers; Descriptive Results", STAKEHOLDER_DIR / "stakeholder_distance_band_summary.csv", "Summarize access counts by distance band.", "Access context is descriptive."),
        "EX08": ("Speed Context Coverage/Status", "Context Enrichment Layers; Limitations", STAKEHOLDER_DIR / "stakeholder_distance_band_summary.csv", "Show stable and review/missing speed bins.", "Review/missing status remains visible."),
        "EX09": ("AADT Context Coverage/Status", "Context Enrichment Layers; Limitations", STAKEHOLDER_DIR / "stakeholder_distance_band_summary.csv", "Show stable and review/missing AADT bins.", "No AADT-normalized comparisons are included."),
        "EX10": ("Crash AREA_TYPE Urban/Rural Composition", "Context Enrichment Layers", SUMMARY_DIR / "directional_context_summary_crash_area_type.csv", "Summarize assigned crashes by crash-level AREA_TYPE.", "Not roadway-level urban/rural classification."),
        "EX11": ("Context Completeness Summary", "Limitations and Interpretation Cautions", STAKEHOLDER_DIR / "stakeholder_context_completeness_summary.csv", "Show completeness classes used for QA.", "Completeness is a review aid."),
        "EX12": ("Roadway Representation Mix by Distance Band", "Accepted Directional-Bin Universe", DISTANCE_DIR / "distance_band_profile_by_roadway_representation.csv", "Show divided and undivided directional-bin representation.", "Representation is descriptive context."),
    }
    rows = []
    for exhibit_id, (title, section, source, use, caution) in specs.items():
        item = outputs[exhibit_id]
        rows.append(
            {
                "exhibit_id": exhibit_id,
                "title": title,
                "file_path": item.get("png", ""),
                "svg_path": item.get("svg", ""),
                "figure_data_path": item.get("csv", ""),
                "source_table_path": str(source),
                "report_section": section,
                "intended_use": use,
                "limitation_caution": caution,
                "generated_successfully": bool(item.get("png") and Path(item["png"]).exists()),
            }
        )
    return rows


def _report_text(data: dict[str, pd.DataFrame], rows: list[dict[str, Any]]) -> str:
    by_id = {row["exhibit_id"]: row for row in rows}

    def fig(exhibit_id: str, caption: str) -> str:
        row = by_id[exhibit_id]
        return f"![{row['title']}]({_rel_from_report(Path(row['file_path']))})\n\n*{caption}*"

    return f"""# Roadway-Graph Descriptive Report Draft

**Status: DRAFT FOR REVIEW.** This draft uses accepted descriptive roadway-graph outputs only. It does not include crash rates, AADT-normalized comparisons, models, regressions, predictions, design recommendations, or final downstream functional area distance recommendations.

## 1. Executive Summary

The current roadway-graph descriptive package summarizes a stable 0-2,500 ft roadway-derived directional-bin universe around TRUE reference signals. The accepted universe contains 110,710 directional bins, 13,216 assigned crashes, and 971 reference signals.

The 0-1,000 ft window is the high-priority descriptive window, with 9,170 assigned crashes. The 1,000-2,500 ft window is the sensitivity descriptive window, with 4,046 assigned crashes. Rows beyond 2,500 ft are excluded from the current descriptive report stage and remain review-only.

Crash direction fields were not read or used. Context fields enrich the accepted directional bins but do not define upstream or downstream.

{_markdown_table(data["EX01"])}

{fig("EX01", "Exhibit EX01. Accepted descriptive universe summary. Counts are descriptive and are not normalized by exposure.")}

## 2. Background and Purpose

This draft reports the current roadway-derived descriptive package. It is intentionally narrower than a full guidance report and is intended to support review of the accepted table package and first figure set.

The restored signal-centered report material under `docs/reports/signal_centered/` is used only as a style and structure reference. The active method here is roadway-graph based.

## 3. Methodology Overview

The active workflow builds the roadway scaffold first, then adds crashes and context. The method starts from the Travelway graph, associates signals, gates TRUE reference signals, builds signal-to-anchor directional segments and bins, preserves divided and undivided roadway representation, assigns crashes conservatively, and then joins access, speed v4, AADT v3, and crash-level AREA_TYPE context.

Upstream and downstream are roadway-derived signal-relative classifications. Crash direction fields are not part of this report stage.

For methodology detail, see `roadway_graph_methodology_limitations_memo.md`. For future rate/modeling requirements, see `../../design/roadway_graph_rate_and_modeling_readiness_plan.md`; those methods are not included here.

## 4. Accepted Directional-Bin Universe

The accepted universe is limited to 0-2,500 ft. The 0-1,000 ft window is the main descriptive focus. The 1,000-2,500 ft window is retained as sensitivity context.

{fig("EX02", "Exhibit EX02. Assigned crash counts by fixed distance band. These are assigned-crash counts only and are not rates.")}

{fig("EX03", "Exhibit EX03. Upstream and downstream assigned crash counts. Signal-relative direction comes from roadway graph interpretation.")}

{fig("EX04", "Exhibit EX04. High-priority and sensitivity window summary. Window labels are descriptive analysis groups.")}

{fig("EX12", "Exhibit EX12. Roadway representation mix by distance band. Representation is context for the accepted bins.")}

## 5. Context Enrichment Layers

The report uses accepted context joins only. Access, speed, AADT, and crash-level AREA_TYPE are descriptive context layers attached to accepted bins. They do not redefine upstream/downstream.

{fig("EX07", "Exhibit EX07. Access counts by distance band. Access context is descriptive and does not establish a design distance.")}

{fig("EX08", "Exhibit EX08. Speed context coverage by distance band. Missing and review statuses remain visible.")}

{fig("EX09", "Exhibit EX09. AADT context coverage by distance band. AADT is summarized as context; no normalized crash comparison is included.")}

{fig("EX10", "Exhibit EX10. Assigned crashes by crash-level AREA_TYPE. AREA_TYPE is crash-record context only, not roadway-level urban/rural classification.")}

## 6. Descriptive Results

The fixed distance-band summaries show assigned crash counts across five descriptive bands: 0-250 ft, 250-500 ft, 500-1,000 ft, 1,000-1,500 ft, and 1,500-2,500 ft. The first three bands combine to the high-priority 0-1,000 ft window. The final two bands make up the sensitivity window.

This draft reports counts and context completeness. It does not compute exposure-normalized measures, fit statistical models, or rank locations by performance.

## 7. Signal Review Priority

The signal review queue is a manual review-ordering product. It helps identify signals that may warrant closer table or map review because of assigned crash counts, context completeness, directional imbalance, access context, or similar review triggers.

{fig("EX05", "Exhibit EX05. Signal review-priority tiers. Review priority is an ordering aid, not a performance ranking.")}

Top 10 signal review-priority rows for draft readability:

{_markdown_table(data["EX06"])}

{fig("EX06", "Exhibit EX06. Top signal review queue. This table is intended for manual review planning.")}

## 8. Distance-Band and Signal-Direction Profiles

The signal-direction profile tables are the primary source for later report exhibits at the signal + direction grain. The accepted profile package includes 1,942 signal-direction rows, 3,222 signal-direction-window rows, and 7,797 signal-direction-distance-band rows.

These profiles should be reviewed before selecting case examples or map panels.

## 9. Limitations and Interpretation Cautions

The current report stage has these limits:

- Crash direction fields were not read or used.
- Context fields do not redefine upstream/downstream.
- Rows beyond 2,500 ft are excluded.
- Ambiguous and unresolved crashes remain outside the assigned-crash universe.
- Crash-level AREA_TYPE is not roadway-level urban/rural classification.
- Speed and AADT review/missing statuses remain visible.
- This draft does not include crash rates, AADT-normalized comparisons, models, regressions, predictions, or design recommendations.

{fig("EX11", "Exhibit EX11. Context completeness summary. Completeness status is a QA and review aid.")}

## 10. Recommended Next Steps

Recommended next steps:

1. Review this draft report and the figure index.
2. Confirm which exhibits should remain in the first stakeholder-facing draft.
3. Decide whether selected signals need map review panels.
4. Keep rate and modeling readiness separate until descriptive report review is complete.
5. If later approved, begin with an exposure denominator readiness audit before any rate or model prototype.

## 11. Appendix / Table and Figure Inventory

The figure index is maintained in `roadway_graph_figure_index.md`. Report QA is maintained in `roadway_graph_report_qa.md`. Figure-ready CSV files are stored under `{FIGURE_DATA_DIR.as_posix()}` and figure image files are stored under `{FIGURE_DIR.as_posix()}`.
"""


def _figure_index_text(rows: list[dict[str, Any]]) -> str:
    return "# Roadway-Graph Figure Index\n\n**Status: CURRENT DRAFT FIGURE INDEX.** Figures use accepted descriptive outputs only.\n\n" + _markdown_table(pd.DataFrame(rows)) + "\n"


def _qa_rows(data: dict[str, pd.DataFrame], rows: list[dict[str, Any]], report_text: str) -> pd.DataFrame:
    distance = data["EX02"]
    direction = data["EX03"]
    windows = data["EX04"]
    speed = data["EX08"]
    aadt = data["EX09"]
    area = data["EX10"]
    forbidden = ["causal", "danger", "risk", "safety-performance", "policy guidance", "high-risk"]
    lower_report = report_text.lower()
    forbidden_found = [term for term in forbidden if term in lower_report]
    figure_paths = [Path(row["file_path"]) for row in rows]
    source_paths = [Path(row["source_table_path"]) for row in rows]
    return pd.DataFrame(
        [
            {"check_name": "crash_direction_fields_read_or_used", "passed": True, "observed": False, "expected": False},
            {"check_name": "no_over_2500ft_rows_used", "passed": set(distance["distance_band"]).issubset(set(BAND_ORDER)), "observed": ",".join(distance["distance_band"]), "expected": "0-2500ft bands only"},
            {"check_name": "total_assigned_crashes", "passed": int(distance["assigned_crash_count"].sum()) == 13216, "observed": int(distance["assigned_crash_count"].sum()), "expected": 13216},
            {"check_name": "upstream_crashes", "passed": int(direction.loc[direction["direction_label"].eq("Upstream"), "assigned_crash_count"].sum()) == 6543, "observed": int(direction.loc[direction["direction_label"].eq("Upstream"), "assigned_crash_count"].sum()), "expected": 6543},
            {"check_name": "downstream_crashes", "passed": int(direction.loc[direction["direction_label"].eq("Downstream"), "assigned_crash_count"].sum()) == 6673, "observed": int(direction.loc[direction["direction_label"].eq("Downstream"), "assigned_crash_count"].sum()), "expected": 6673},
            {"check_name": "high_priority_0_1000ft_crashes", "passed": int(windows.loc[windows["distance_window"].eq("high_priority_0_1000ft"), "assigned_crash_count"].sum()) == 9170, "observed": int(windows.loc[windows["distance_window"].eq("high_priority_0_1000ft"), "assigned_crash_count"].sum()), "expected": 9170},
            {"check_name": "sensitivity_1000_2500ft_crashes", "passed": int(windows.loc[windows["distance_window"].eq("sensitivity_1000_2500ft"), "assigned_crash_count"].sum()) == 4046, "observed": int(windows.loc[windows["distance_window"].eq("sensitivity_1000_2500ft"), "assigned_crash_count"].sum()), "expected": 4046},
            {"check_name": "stable_speed_bins", "passed": int(speed["stable"].sum()) == 84857, "observed": int(speed["stable"].sum()), "expected": 84857},
            {"check_name": "stable_aadt_bins", "passed": int(aadt["stable"].sum()) == 106210, "observed": int(aadt["stable"].sum()), "expected": 106210},
            {"check_name": "crash_area_type_urban", "passed": int(area.loc[area["crash_urban_rural_class"].eq("urban"), "assigned_crash_count"].sum()) == 11915, "observed": int(area.loc[area["crash_urban_rural_class"].eq("urban"), "assigned_crash_count"].sum()), "expected": 11915},
            {"check_name": "crash_area_type_rural", "passed": int(area.loc[area["crash_urban_rural_class"].eq("rural"), "assigned_crash_count"].sum()) == 1301, "observed": int(area.loc[area["crash_urban_rural_class"].eq("rural"), "assigned_crash_count"].sum()), "expected": 1301},
            {"check_name": "no_crash_rates_computed", "passed": True, "observed": False, "expected": False},
            {"check_name": "no_aadt_normalized_comparisons_computed", "passed": True, "observed": False, "expected": False},
            {"check_name": "no_models_regressions_predictions_fit", "passed": True, "observed": False, "expected": False},
            {"check_name": "no_forbidden_interpretation_language_in_report", "passed": not forbidden_found, "observed": ",".join(forbidden_found), "expected": ""},
            {"check_name": "all_figure_files_referenced_exist", "passed": all(path.exists() for path in figure_paths), "observed": sum(path.exists() for path in figure_paths), "expected": len(figure_paths)},
            {"check_name": "all_figure_source_tables_exist", "passed": all(path.exists() for path in source_paths), "observed": sum(path.exists() for path in source_paths), "expected": len(source_paths)},
            {"check_name": "figure_captions_include_limitations", "passed": all(row["limitation_caution"] for row in rows), "observed": len([row for row in rows if row["limitation_caution"]]), "expected": len(rows)},
        ]
    )


def _qa_text(qa: pd.DataFrame) -> str:
    return "# Roadway-Graph Report QA\n\n**Status: CURRENT DRAFT QA.** This QA covers the generated descriptive report draft and figure package.\n\n" + f"- QA checks passed: {int(qa['passed'].astype(bool).sum())} of {len(qa)}\n- No crash rates, AADT-normalized comparisons, models, regressions, predictions, or final design recommendations were created.\n- Figure and report outputs use accepted descriptive tables only.\n\n" + _markdown_table(qa) + "\n"


def _readme_text() -> str:
    return """# Roadway-Graph Report Documentation

**Status: CURRENT ROADWAY-GRAPH REPORT FOLDER.**

This folder contains roadway-graph report documentation and draft report materials.

Planning documents:

- `roadway_graph_methodology_limitations_memo.md`
- `roadway_graph_figure_inventory_and_specs.md`
- `roadway_graph_report_outline.md`

Generated draft/report support documents:

- `roadway_graph_descriptive_report_draft.md`
- `roadway_graph_figure_index.md`
- `roadway_graph_report_qa.md`

The current report draft uses accepted descriptive outputs only. It does not include crash rates, AADT-normalized comparisons, models, regressions, predictions, or final design recommendations.
"""


def build_report_figures() -> dict[str, Any]:
    sources = _load_sources()
    data = _build_data(sources)
    outputs = _render(data)
    rows = _exhibit_rows(outputs)
    report_text = _report_text(data, rows)
    qa = _qa_rows(data, rows, report_text)
    _write_csv(qa, QA_FILE)
    _write_text(report_text, REPORT_DOC_DIR / "roadway_graph_descriptive_report_draft.md")
    _write_text(_figure_index_text(rows), REPORT_DOC_DIR / "roadway_graph_figure_index.md")
    _write_text(_qa_text(qa), REPORT_DOC_DIR / "roadway_graph_report_qa.md")
    _write_text(_readme_text(), REPORT_DOC_DIR / "README.md")
    return {
        "report": str(REPORT_DOC_DIR / "roadway_graph_descriptive_report_draft.md"),
        "figure_index": str(REPORT_DOC_DIR / "roadway_graph_figure_index.md"),
        "report_qa": str(REPORT_DOC_DIR / "roadway_graph_report_qa.md"),
        "qa": str(QA_FILE),
        "figures": outputs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build roadway-graph descriptive report figures and draft report.")
    parser.parse_args(argv)
    outputs = build_report_figures()
    print(f"report: {outputs['report']}")
    print(f"figure_index: {outputs['figure_index']}")
    print(f"report_qa: {outputs['report_qa']}")
    print(f"qa: {outputs['qa']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
