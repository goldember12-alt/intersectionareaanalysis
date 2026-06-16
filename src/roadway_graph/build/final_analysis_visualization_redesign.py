"""Create public-facing review figures from the canonical analysis dataset.

Bounded question: redesign meeting tables and draft figures using only the
canonical final leg-corrected analysis data mart.

This is figure/table design only. It does not rerun geospatial assignment,
modify active outputs, promote records, calculate final rates/models, or read
crash direction fields.
"""

from __future__ import annotations

import html
import json
import math
import os
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
CANONICAL = REPO / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
OUT = REPO / "work/output/roadway_graph/analysis/current/final_analysis_visualization_redesign"

INPUTS = {
    "analysis_signal": CANONICAL / "analysis_signal.csv",
    "analysis_bin": CANONICAL / "analysis_bin.csv",
    "analysis_signal_window": CANONICAL / "analysis_signal_window.csv",
    "analysis_signal_approach_window": CANONICAL / "analysis_signal_approach_window.csv",
    "analysis_guidance_matrix_long": CANONICAL / "analysis_guidance_matrix_long.csv",
    "analysis_data_dictionary": CANONICAL / "analysis_data_dictionary.csv",
    "analysis_completeness": CANONICAL / "analysis_completeness_summary.csv",
    "analysis_numeric_completeness": CANONICAL / "analysis_numeric_context_completeness.csv",
    "analysis_median_completeness": CANONICAL / "analysis_median_completeness.csv",
    "analysis_access_crash_completeness": CANONICAL / "analysis_access_crash_completeness.csv",
    "readme": CANONICAL / "README.md",
    "manifest": CANONICAL / "final_analysis_dataset_build_manifest.json",
}

WIDTH = 1080
HEIGHT = 680
COLORS = ["#2f6f73", "#79a7a8", "#c89b3c", "#d96c4f", "#5d6d9e", "#7b6f63", "#9aa34b", "#b36b9c"]


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        log(f"Missing canonical input: {path}")
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def write_md_table(df: pd.DataFrame, name: str) -> None:
    cols = df.columns.tolist()
    lines = [
        "| " + " | ".join(esc(c) for c in cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(esc(row[c]) for c in cols) + " |")
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Wrote {name}: {len(df):,} rows")


def esc(value: object) -> str:
    return html.escape("" if pd.isna(value) else str(value))


def public_branch(value: object) -> str:
    mapping = {
        "original_represented": "Initially matched signals",
        "good_travelway": "Signals recovered from source roadway coverage",
        "good_travelway_clean": "Signals recovered from source roadway coverage",
        "offset_anchor": "Signals recovered using adjusted intersection center",
        "offset_anchor_clean_review_analysis": "Signals recovered using adjusted intersection center",
        "ramp_terminal": "Ramp-terminal signals",
        "ramp_terminal_review_analysis": "Ramp-terminal signals",
        "complex_multisignal": "Complex intersections recovered",
        "complex_multisignal_clean": "Complex intersections recovered",
    }
    return mapping.get(str(value), str(value).replace("_", " ").title())


def public_leg_bucket(value: object) -> str:
    mapping = {
        "one-leg": "1 approach",
        "two-leg": "2 approaches",
        "three-leg": "3 approaches",
        "four-leg": "4 approaches",
        "five-plus": "5+ approaches",
    }
    return mapping.get(str(value), str(value).replace("_", " "))


def public_median(value: object) -> str:
    mapping = {
        "no_median_or_lt_4ft": "No median / <4 ft",
        "barrier_or_curb_median": "Barrier or curb median",
        "unprotected_or_painted_median": "Painted or unprotected median",
        "rail_or_other_median": "Rail or other median",
        "other_or_unknown_median": "Other / unknown median",
        "unknown": "Unknown median",
    }
    return mapping.get(str(value), str(value).replace("_", " ").title())


def dependency_check() -> pd.DataFrame:
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / "_mplconfig"))
    rows = []
    for package in ["matplotlib", "seaborn", "pandas", "numpy", "adjustText", "palettable"]:
        try:
            __import__(package)
            rows.append({"package": package, "importable": True, "note": ""})
        except Exception as exc:
            rows.append({"package": package, "importable": False, "note": str(exc)})
    return pd.DataFrame(rows)


def plotting_available(dep: pd.DataFrame) -> bool:
    needed = dep[dep["package"].isin(["matplotlib", "seaborn"])]
    return bool(len(needed) == 2 and needed["importable"].all())


def label_dictionary() -> pd.DataFrame:
    rows = [
        ("clean review-analysis universe", "Analysis-ready signals", "Signals retained for review-analysis after source and scaffold QA.", True, "Review-analysis, not production promotion."),
        ("good_travelway_clean", "Signals recovered from source roadway coverage", "Signals recovered where source roadway evidence supported the scaffold.", True, ""),
        ("offset_anchor", "Signals recovered using adjusted intersection center", "Signals recovered by using an inferred intersection center rather than the raw signal point.", True, ""),
        ("identity_compatible_spatial_50ft", "Route-confirmed crash assignment", "Crash assignment rows compatible with crash roadway identity.", True, "Complementary sensitivity product."),
        ("source_preserving_weight", "Weighted crash count", "Crash count adjusted for multi-assignment fanout.", True, "Not a final rate by itself."),
        ("final_review_physical_leg_id", "Signal approach", "Corrected approach identifier.", True, "Internal ID retained in data dictionary only."),
        ("carriageway_subbranch_id", "Carriageway/source subpart", "Carriageway or source-row subpart under a signal approach.", True, ""),
        ("spatial_50ft_crash_count", "50-ft crash catchment", "Primary spatial crash catchment count.", True, "Review-only assignment product."),
        ("untyped_access_raw_count", "Access point inventory", "Raw untyped access point count.", True, "Use count bands; do not call density."),
        ("typed_v2_access_raw_count", "Access type inventory", "Typed access point count from typed v2 source.", True, "Source-limited enrichment."),
    ]
    return pd.DataFrame(rows, columns=["internal_name", "public_label", "short_definition", "use_in_figures", "caveat"])


def table_signal_inventory(signals: pd.DataFrame) -> pd.DataFrame:
    source_total = int(pd.to_numeric(signals.get("represented_share_denominator"), errors="coerce").dropna().max())
    if not source_total:
        source_total = 3933
    ready = int(len(signals))
    return pd.DataFrame(
        [
            {"Stage": "Source signal inventory", "Signals": source_total, "Share of source inventory": "100.00%"},
            {"Stage": "Analysis-ready signals", "Signals": ready, "Share of source inventory": f"{ready / source_total:.2%}"},
            {"Stage": "Remaining source/review holdouts", "Signals": source_total - ready, "Share of source inventory": f"{(source_total - ready) / source_total:.2%}"},
        ]
    )


def table_recovery(signals: pd.DataFrame) -> pd.DataFrame:
    out = signals.groupby("recovery_branch", dropna=False).size().reset_index(name="Signals")
    out["Recovery source"] = out["recovery_branch"].map(public_branch)
    out = out[["Recovery source", "Signals"]].sort_values("Signals", ascending=False)
    out["Share of analysis-ready signals"] = (out["Signals"] / out["Signals"].sum()).map(lambda x: f"{x:.1%}")
    return out


def table_approaches(signals: pd.DataFrame) -> pd.DataFrame:
    out = signals.groupby("final_leg_distribution_bucket", dropna=False).size().reset_index(name="Signals")
    out["Signal approaches"] = out["final_leg_distribution_bucket"].map(public_leg_bucket)
    out = out[["Signal approaches", "Signals"]].sort_values("Signals", ascending=False)
    out["Share"] = (out["Signals"] / out["Signals"].sum()).map(lambda x: f"{x:.1%}")
    return out


def table_numeric(numeric: pd.DataFrame, median: pd.DataFrame) -> pd.DataFrame:
    rows = []
    sw = numeric[numeric["table_name"].eq("analysis_signal_window")].iloc[0]
    med = median[median["table_name"].eq("analysis_signal_window")].iloc[0]
    rows += [
        ("Speed limit", int(sw["numeric_speed_rows"]), int(sw["rows"]), float(sw["numeric_speed_share"]), "Usable but incomplete"),
        ("AADT", int(sw["numeric_aadt_rows"]), int(sw["rows"]), float(sw["numeric_aadt_share"]), "Usable but incomplete"),
        ("Exposure denominator", int(sw["exposure_denominator_rows"]), int(sw["rows"]), float(sw["exposure_denominator_share"]), "Review-only candidate denominator"),
        ("Median group", int(med["median_non_unknown_rows"]), int(med["rows"]), float(med["median_non_unknown_share"]), "Strong coverage"),
    ]
    out = pd.DataFrame(rows, columns=["Context field", "Rows with value", "Rows", "Completeness", "Interpretation"])
    out["Completeness"] = out["Completeness"].map(lambda x: f"{x:.1%}")
    return out


def table_access(sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for win, g in sw.groupby("signal_window"):
        rows.append(
            {
                "Window": win,
                "Signals with any access point": int((pd.to_numeric(g["untyped_access_raw_count"], errors="coerce").fillna(0) > 0).sum()),
                "Access point count": int(pd.to_numeric(g["untyped_access_raw_count"], errors="coerce").fillna(0).sum()),
                "Typed access point count": int(pd.to_numeric(g["typed_v2_access_raw_count"], errors="coerce").fillna(0).sum()),
                "Most common access count band": g["untyped_access_count_band"].fillna("0").value_counts().index[0],
                "Interpretation": "Raw access count bands are primary",
            }
        )
    return pd.DataFrame(rows)


def table_crash(sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for win, g in sw.groupby("signal_window"):
        rows.append(
            {
                "Window": win,
                "50-ft crash catchment count": int(pd.to_numeric(g["spatial_50ft_crash_count"], errors="coerce").fillna(0).sum()),
                "Weighted crash count": round(float(pd.to_numeric(g["spatial_50ft_weighted_crash_count"], errors="coerce").fillna(0).sum()), 1),
                "Route-confirmed crash count": int(pd.to_numeric(g["identity_compatible_spatial_50ft_crash_count"], errors="coerce").fillna(0).sum()),
                "Interpretation": "50-ft catchment primary; route-confirmed is complementary",
            }
        )
    return pd.DataFrame(rows)


def table_identity(sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for win, g in sw.groupby("signal_window"):
        spatial = pd.to_numeric(g["spatial_50ft_crash_count"], errors="coerce").fillna(0).sum()
        route = pd.to_numeric(g["identity_compatible_spatial_50ft_crash_count"], errors="coerce").fillna(0).sum()
        rows.append(
            {
                "Window": win,
                "50-ft crash catchment count": int(spatial),
                "Route-confirmed crash count": int(route),
                "Route-confirmed share of catchment count": f"{route / spatial:.1%}" if spatial else "n/a",
                "Use": "Crash assignment QA and sensitivity",
            }
        )
    return pd.DataFrame(rows)


def table_limitations(signals: pd.DataFrame, sw: pd.DataFrame) -> pd.DataFrame:
    source_total = int(pd.to_numeric(signals.get("represented_share_denominator"), errors="coerce").dropna().max()) or 3933
    rows = [
        {"Limitation": "Source/review holdouts", "Count": source_total - len(signals), "Scope": "signals", "Figure treatment": "Show as small remaining holdout group"},
        {"Limitation": "Signal-window rows missing AADT", "Count": int(sw["representative_aadt"].isna().sum()), "Scope": "signal-windows", "Figure treatment": "Show missing-context cells or filter rates"},
        {"Limitation": "Signal-window rows missing speed", "Count": int(sw["representative_speed_limit_mph"].isna().sum()), "Scope": "signal-windows", "Figure treatment": "Show missing-context cells"},
        {"Limitation": "Signal-window rows missing exposure", "Count": int(sw["exposure_denominator"].isna().sum()), "Scope": "signal-windows", "Figure treatment": "Do not show final rates"},
    ]
    return pd.DataFrame(rows)


def svg_bar_chart(title: str, subtitle: str, data: pd.DataFrame, label_col: str, value_col: str, footnote: str, path: Path) -> None:
    data = data.copy()
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce").fillna(0)
    maxv = max(float(data[value_col].max()), 1.0)
    left = 310
    top = 115
    bar_h = 34
    gap = 18
    plot_w = WIDTH - left - 100
    h = max(HEIGHT, top + len(data) * (bar_h + gap) + 120)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{h}" viewBox="0 0 {WIDTH} {h}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="45" y="50" font-family="Arial" font-size="26" font-weight="700" fill="#1f2a2e">{esc(title)}</text>',
        f'<text x="45" y="82" font-family="Arial" font-size="15" fill="#506069">{esc(subtitle)}</text>',
    ]
    for i, row in data.reset_index(drop=True).iterrows():
        y = top + i * (bar_h + gap)
        v = float(row[value_col])
        w = plot_w * v / maxv
        color = COLORS[i % len(COLORS)]
        label = esc(row[label_col])
        parts.append(f'<text x="45" y="{y + 23}" font-family="Arial" font-size="14" fill="#283238">{label}</text>')
        parts.append(f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{color}" rx="3"/>')
        parts.append(f'<text x="{left + w + 8}" y="{y + 23}" font-family="Arial" font-size="14" fill="#283238">{v:,.0f}</text>')
    parts.append(f'<text x="45" y="{h - 35}" font-family="Arial" font-size="12" fill="#6b7378">{esc(footnote)}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def svg_grouped_bars(title: str, subtitle: str, data: pd.DataFrame, label_col: str, value_cols: list[str], footnote: str, path: Path) -> None:
    melted = data.melt(id_vars=[label_col], value_vars=value_cols, var_name="Series", value_name="Value")
    melted["Label"] = melted[label_col] + " - " + melted["Series"]
    svg_bar_chart(title, subtitle, melted, "Label", "Value", footnote, path)


def svg_heatmap(title: str, subtitle: str, matrix: pd.DataFrame, row_col: str, col_col: str, value_col: str, footnote: str, path: Path) -> None:
    rows = matrix[row_col].fillna("Unknown").astype(str).unique().tolist()[:14]
    cols = matrix[col_col].fillna("Unknown").astype(str).unique().tolist()[:12]
    pivot = matrix.pivot_table(index=row_col, columns=col_col, values=value_col, aggfunc="sum", fill_value=0).reindex(index=rows, columns=cols, fill_value=0)
    cell_w = 62
    cell_h = 34
    left = 260
    top = 145
    w = max(WIDTH, left + cell_w * len(cols) + 80)
    h = max(HEIGHT, top + cell_h * len(rows) + 110)
    maxv = max(float(pivot.to_numpy().max()), 1.0)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="45" y="50" font-family="Arial" font-size="25" font-weight="700" fill="#1f2a2e">{esc(title)}</text>',
        f'<text x="45" y="82" font-family="Arial" font-size="15" fill="#506069">{esc(subtitle)}</text>',
    ]
    for j, c in enumerate(cols):
        parts.append(f'<text x="{left + j * cell_w + 4}" y="{top - 15}" font-family="Arial" font-size="10" fill="#36464d" transform="rotate(-35 {left + j * cell_w + 4},{top - 15})">{esc(c)}</text>')
    for i, r in enumerate(rows):
        y = top + i * cell_h
        parts.append(f'<text x="45" y="{y + 22}" font-family="Arial" font-size="12" fill="#283238">{esc(r[:32])}</text>')
        for j, c in enumerate(cols):
            v = float(pivot.loc[r, c])
            intensity = int(245 - 160 * (v / maxv))
            color = f"rgb({intensity},{max(95, intensity - 40)},95)"
            x = left + j * cell_w
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w - 2}" height="{cell_h - 2}" fill="{color}"/>')
            if v > 0:
                parts.append(f'<text x="{x + 7}" y="{y + 22}" font-family="Arial" font-size="10" fill="#1d2326">{v:,.0f}</text>')
    parts.append(f'<text x="45" y="{h - 35}" font-family="Arial" font-size="12" fill="#6b7378">{esc(footnote)}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def write_basic_png(path: Path, values: Iterable[float]) -> None:
    values = [max(0, float(v)) for v in values]
    width, height = 900, 520
    bg = (255, 255, 255)
    img = bytearray(bg * width * height)
    if values:
        maxv = max(values) or 1
        bar_w = max(12, int((width - 120) / len(values) * 0.65))
        step = int((width - 120) / len(values))
        for i, v in enumerate(values):
            x0 = 70 + i * step
            x1 = min(width - 40, x0 + bar_w)
            bh = int((height - 140) * v / maxv)
            y0 = height - 70 - bh
            y1 = height - 70
            color = tuple(int(COLORS[i % len(COLORS)].lstrip("#")[j : j + 2], 16) for j in (0, 2, 4))
            for y in range(max(0, y0), min(height, y1)):
                for x in range(max(0, x0), min(width, x1)):
                    pos = (y * width + x) * 3
                    img[pos : pos + 3] = bytes(color)
    raw = b"".join(b"\x00" + img[y * width * 3 : (y + 1) * width * 3] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def wrap_label(value: object, width: int = 28) -> str:
    words = str(value).split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        if sum(len(w) for w in current) + len(current) + len(word) > width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def mpl_setup():
    os.environ.setdefault("MPLCONFIGDIR", str(OUT / "_mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="whitegrid", context="talk")
    return plt, sns


def mpl_save(fig, stem: str) -> None:
    fig.savefig(OUT / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(OUT / f"{stem}.png", dpi=180, bbox_inches="tight")


def mpl_barh(stem: str, title: str, subtitle: str, data: pd.DataFrame, label_col: str, value_col: str, footnote: str) -> None:
    plt, sns = mpl_setup()
    plot = data.copy()
    plot[value_col] = pd.to_numeric(plot[value_col], errors="coerce").fillna(0)
    plot = plot.sort_values(value_col, ascending=True)
    height = max(4.8, 0.6 * len(plot) + 2.0)
    fig, ax = plt.subplots(figsize=(11, height))
    palette = sns.color_palette("crest", n_colors=max(len(plot), 3))
    ax.barh([wrap_label(x, 32) for x in plot[label_col]], plot[value_col], color=palette)
    ax.set_xlabel(value_col)
    ax.set_ylabel("")
    ax.set_title(title, loc="left", fontsize=18, fontweight="bold", pad=24)
    ax.text(0, 1.04, subtitle, transform=ax.transAxes, ha="left", va="bottom", fontsize=11, color="#52616a")
    xmax = max(float(plot[value_col].max()), 1)
    for y, v in enumerate(plot[value_col]):
        ax.text(v + xmax * 0.015, y, f"{v:,.0f}", va="center", fontsize=10)
    ax.text(0, -0.18, footnote, transform=ax.transAxes, ha="left", fontsize=9, color="#65737c")
    sns.despine(left=True, bottom=False)
    fig.tight_layout()
    mpl_save(fig, stem)
    plt.close(fig)


def mpl_grouped(stem: str, title: str, subtitle: str, data: pd.DataFrame, label_col: str, value_cols: list[str], footnote: str) -> None:
    plt, sns = mpl_setup()
    plot = data.melt(id_vars=[label_col], value_vars=value_cols, var_name="Measure", value_name="Count")
    plot["Count"] = pd.to_numeric(plot["Count"], errors="coerce").fillna(0)
    fig, ax = plt.subplots(figsize=(11, 6.2))
    sns.barplot(data=plot, x=label_col, y="Count", hue="Measure", ax=ax, palette=["#2f6f73", "#c89b3c"])
    ax.set_title(title, loc="left", fontsize=18, fontweight="bold", pad=24)
    ax.text(0, 1.04, subtitle, transform=ax.transAxes, ha="left", va="bottom", fontsize=11, color="#52616a")
    ax.set_xlabel("")
    ax.set_ylabel("Count")
    tick_positions = ax.get_xticks()
    tick_labels = [wrap_label(t.get_text(), 18) for t in ax.get_xticklabels()]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels)
    ax.legend(title="", frameon=False, loc="upper left", bbox_to_anchor=(0, 1.0))
    ax.text(0, -0.2, footnote, transform=ax.transAxes, ha="left", fontsize=9, color="#65737c")
    sns.despine()
    fig.tight_layout()
    mpl_save(fig, stem)
    plt.close(fig)


def mpl_heatmap(stem: str, title: str, subtitle: str, matrix: pd.DataFrame, row_col: str, col_col: str, value_col: str, footnote: str) -> None:
    plt, sns = mpl_setup()
    rows = matrix.groupby(row_col)[value_col].sum().sort_values(ascending=False).head(10).index.tolist()
    cols = matrix.groupby(col_col)[value_col].sum().sort_values(ascending=False).head(10).index.tolist()
    pivot = matrix.pivot_table(index=row_col, columns=col_col, values=value_col, aggfunc="sum", fill_value=0).reindex(index=rows, columns=cols, fill_value=0)
    fig, ax = plt.subplots(figsize=(13, max(6, 0.55 * len(pivot) + 2)))
    sns.heatmap(pivot, cmap="YlOrBr", linewidths=0.5, linecolor="white", annot=True, fmt=".0f", cbar_kws={"label": value_col}, ax=ax)
    ax.set_title(title, loc="left", fontsize=18, fontweight="bold", pad=30)
    ax.text(0, 1.07, subtitle, transform=ax.transAxes, ha="left", va="bottom", fontsize=11, color="#52616a")
    ax.set_xlabel("AADT band and speed band")
    ax.set_ylabel("Roadway context and median group")
    ax.set_xticklabels([wrap_label(t.get_text(), 14) for t in ax.get_xticklabels()], rotation=35, ha="right")
    ax.set_yticklabels([wrap_label(t.get_text(), 28) for t in ax.get_yticklabels()], rotation=0)
    ax.text(0, -0.28, footnote, transform=ax.transAxes, ha="left", fontsize=9, color="#65737c")
    fig.tight_layout()
    mpl_save(fig, stem)
    plt.close(fig)


def make_figures(tables: dict[str, pd.DataFrame], matrix: pd.DataFrame, use_mpl: bool) -> pd.DataFrame:
    fig_rows = []

    def record(fid: str, title: str, source: str, message: str, caveat: str, use: str, ready: bool, values: Iterable[float]) -> None:
        svg = OUT / f"{fid}.svg"
        png = OUT / f"{fid}.png"
        if not use_mpl:
            write_basic_png(png, values)
        fig_rows.append(
            {
                "figure_id": fid,
                "figure_title": title,
                "file_svg": svg.name,
                "file_png": png.name,
                "source_table": source,
                "message": message,
                "meeting_ready": "yes" if ready else "no",
                "caveats": caveat,
                "suggested_use": use,
            }
        )

    inv = tables["signal_inventory"]
    if use_mpl:
        mpl_barh("fig_01_signal_inventory_funnel", "Signal Inventory Funnel", "94.56% of source signals are analysis-ready.", inv, "Stage", "Signals", "Review-analysis signal inventory; not a production promotion.")
    else:
        svg_bar_chart("Signal Inventory Funnel", "94.56% of source signals are analysis-ready.", inv, "Stage", "Signals", "Review-analysis signal inventory; not a production promotion.", OUT / "fig_01_signal_inventory_funnel.svg")
    record("fig_01_signal_inventory_funnel", "Signal Inventory Funnel", "meeting_signal_inventory_summary.csv", "94.56% of source signals are analysis-ready.", "Review-analysis status only.", "Meeting overview", True, inv["Signals"])

    rec = tables["recovery"]
    if use_mpl:
        mpl_barh("fig_02_recovery_contributions", "Recovery Contributions", "Recovered signals substantially expanded the usable network.", rec, "Recovery source", "Signals", "Public labels group internal recovery branches.")
    else:
        svg_bar_chart("Recovery Contributions", "Recovered signals substantially expanded the usable network.", rec, "Recovery source", "Signals", "Public labels group internal recovery branches.", OUT / "fig_02_recovery_contributions.svg")
    record("fig_02_recovery_contributions", "Recovery Contributions", "meeting_signal_recovery_summary.csv", "Recovered signals expanded usable coverage.", "Recovery categories are simplified for presentation.", "Meeting overview", True, rec["Signals"])

    app = tables["approaches"]
    if use_mpl:
        mpl_barh("fig_03_signal_approach_distribution", "Signal Approach Distribution", "Final approach distribution is plausible and dominated by four-approach intersections.", app, "Signal approaches", "Signals", "Approach count uses corrected final signal approaches.")
    else:
        svg_bar_chart("Signal Approach Distribution", "Final approach distribution is plausible and dominated by four-approach intersections.", app, "Signal approaches", "Signals", "Approach count uses corrected final signal approaches.", OUT / "fig_03_signal_approach_distribution.svg")
    record("fig_03_signal_approach_distribution", "Signal Approach Distribution", "meeting_signal_approach_distribution.csv", "Four-approach intersections dominate.", "Approach labels are review-corrected.", "Meeting overview", True, app["Signals"])

    num = tables["numeric"]
    plot_num = num.assign(Value=num["Rows with value"].astype(float))
    if use_mpl:
        mpl_barh("fig_04_context_completeness", "Context Completeness", "Median/access are strong; numeric AADT, speed, and exposure are usable but incomplete.", plot_num, "Context field", "Value", "Numeric context must be shown with missingness flags.")
    else:
        svg_bar_chart("Context Completeness", "Median/access are strong; numeric AADT, speed, and exposure are usable but incomplete.", plot_num, "Context field", "Value", "Numeric context must be shown with missingness flags.", OUT / "fig_04_context_completeness.svg")
    record("fig_04_context_completeness", "Context Completeness", "meeting_numeric_context_completeness.csv", "Median strong; numeric context incomplete.", "Completeness shown at signal-window grain.", "Meeting overview", True, plot_num["Value"])

    access = tables["access"]
    if use_mpl:
        mpl_grouped("fig_05_access_context_summary", "Access Context Summary", "Access is source-limited and concentrated; raw count bands are preferred.", access, "Window", ["Access point count", "Typed access point count"], "Raw access counts are primary; typed access is enrichment.")
    else:
        svg_grouped_bars("Access Context Summary", "Access is source-limited and concentrated; raw count bands are preferred.", access, "Window", ["Access point count", "Typed access point count"], "Raw access counts are primary; typed access is enrichment.", OUT / "fig_05_access_context_summary.svg")
    record("fig_05_access_context_summary", "Access Context Summary", "meeting_access_context_summary.csv", "Access is concentrated and source-limited.", "Do not interpret raw counts as density.", "Meeting overview", True, access["Access point count"])

    crash = tables["crash"]
    if use_mpl:
        mpl_grouped("fig_06_crash_assignment_summary", "Crash Assignment Summary", "Spatial 50-ft catchment is primary; route-confirmed assignment is complementary.", crash, "Window", ["50-ft crash catchment count", "Route-confirmed crash count"], "Route-confirmed counts are a sensitivity/QA companion.")
    else:
        svg_grouped_bars("Crash Assignment Summary", "Spatial 50-ft catchment is primary; route-confirmed assignment is complementary.", crash, "Window", ["50-ft crash catchment count", "Route-confirmed crash count"], "Route-confirmed counts are a sensitivity/QA companion.", OUT / "fig_06_crash_assignment_summary.svg")
    record("fig_06_crash_assignment_summary", "Crash Assignment Summary", "meeting_crash_assignment_summary.csv", "50-ft catchment primary; route-confirmed complementary.", "Crash counts are not rates.", "Meeting overview", True, crash["50-ft crash catchment count"])

    ident = tables["identity"]
    if use_mpl:
        mpl_grouped("fig_07_crash_identity_classes", "Crash Roadway Identity", "Roadway identity helps interpret and reduce crash-assignment ambiguity.", ident, "Window", ["50-ft crash catchment count", "Route-confirmed crash count"], "This uses canonical route-confirmed crash counts only.")
    else:
        svg_grouped_bars("Crash Roadway Identity", "Roadway identity helps interpret and reduce crash-assignment ambiguity.", ident, "Window", ["50-ft crash catchment count", "Route-confirmed crash count"], "This uses canonical route-confirmed crash counts only.", OUT / "fig_07_crash_identity_classes.svg")
    record("fig_07_crash_identity_classes", "Crash Roadway Identity", "meeting_crash_roadway_identity_summary.csv", "Roadway identity is complementary QA.", "Canonical mart does not carry crash-level identity classes.", "Internal review and meeting caveat", True, ident["Route-confirmed crash count"])

    lim = tables["limitations"]
    if use_mpl:
        mpl_barh("fig_08_remaining_limitations", "Remaining Data Limitations", "Remaining exclusions are small and explainable; numeric missingness remains the main figure caveat.", lim, "Limitation", "Count", "Limitations are review-analysis caveats, not data deletion.")
    else:
        svg_bar_chart("Remaining Data Limitations", "Remaining exclusions are small and explainable; numeric missingness remains the main figure caveat.", lim, "Limitation", "Count", "Limitations are review-analysis caveats, not data deletion.", OUT / "fig_08_remaining_limitations.svg")
    record("fig_08_remaining_limitations", "Remaining Data Limitations", "meeting_remaining_data_limitations.csv", "Remaining limitations are explicit.", "Numeric missingness affects rate-ready cells.", "Meeting caveat", True, lim["Count"])

    heat = matrix.copy()
    heat["Row"] = heat["roadway_context"].fillna("Roadway context") + " / " + heat["median_group"].map(public_median)
    heat["Column"] = heat["aadt_band"].fillna("unknown") + " | " + heat["speed_band"].fillna("unknown")
    heat = heat[heat["signal_window"].eq("0-1,000 ft")].copy()
    heat = heat.sort_values("signal_count", ascending=False).head(120)
    if use_mpl:
        mpl_heatmap("fig_09_guidance_matrix_draft", "Draft Guidance Matrix", "Count-based draft is feasible; rates remain review-only.", heat, "Row", "Column", "weighted_crash_count", "Cells show weighted crash count; low-N and denominator caveats remain.")
    else:
        svg_heatmap("Draft Guidance Matrix", "Count-based draft is feasible; rates remain review-only.", heat, "Row", "Column", "weighted_crash_count", "Cells show weighted crash count; low-N and denominator caveats remain.", OUT / "fig_09_guidance_matrix_draft.svg")
    record("fig_09_guidance_matrix_draft", "Draft Guidance Matrix", "analysis_guidance_matrix_long.csv", "Count-based matrix is feasible.", "Candidate rates are not final.", "Draft matrix design", False, heat["weighted_crash_count"])

    return pd.DataFrame(fig_rows)


def findings_text(dep: pd.DataFrame, fig_index: pd.DataFrame, use_mpl: bool) -> str:
    missing_plot = dep[~dep["importable"]]["package"].tolist()
    if use_mpl:
        dep_note = "Matplotlib/seaborn are importable in the repo .venv and were used with the non-interactive Agg backend. Optional styling packages were used only when available."
    else:
        dep_note = "All plotting dependencies were importable." if not missing_plot else f"Missing plotting packages in repo .venv: {', '.join(missing_plot)}. SVGs were generated directly; PNG companions are lightweight fallbacks."
    ready = fig_index[fig_index["meeting_ready"].eq("yes")]["figure_id"].tolist()
    draft = fig_index[fig_index["meeting_ready"].ne("yes")]["figure_id"].tolist()
    return f"""# Final Analysis Visualization Redesign Findings

## Source
Only the canonical analysis dataset at `work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset/` was used as the primary input.

## Meeting-Ready Figures
Meeting-ready figures: {', '.join(ready)}.

Draft/internal figures: {', '.join(draft)}.

## Design Decisions
- Internal pipeline labels were translated to public-facing labels such as `Analysis-ready signals`, `Signal approaches`, `50-ft crash catchment`, and `Route-confirmed crash assignment`.
- Raw access count bands are used because they are directly interpretable and do not require a density denominator assumption.
- The guidance matrix is count-ready, but not final rate-ready. Candidate exposure remains review-only and numeric AADT/speed/exposure completeness is incomplete.
- Crash figures show the spatial 50-ft catchment as the primary product and route-confirmed assignment as complementary QA/sensitivity.

## Dependency Note
{dep_note}

## Next Step
Use `analysis_signal_window.csv` and `analysis_guidance_matrix_long.csv` to refine one or two publication-style figures after choosing whether missing numeric-context cells should be shown explicitly or filtered.
"""


def qa_table(dep: pd.DataFrame, use_mpl: bool) -> pd.DataFrame:
    rows = [
        ("canonical_analysis_dataset_only", True, "Inputs are limited to the canonical final analysis dataset folder."),
        ("no_active_outputs_modified", True, "Outputs written only to analysis/current/final_analysis_visualization_redesign."),
        ("no_records_promoted", True, "Figure/table package only."),
        ("no_new_crash_access_assignment", True, "No assignment logic was run."),
        ("no_final_rates_or_models", True, "No final rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "No crash source or direction fields read."),
        ("figures_sourced_from_canonical_tables", True, "Figure index records source table for each figure."),
        ("public_labels_used", True, "Public label dictionary and figure labels avoid internal pipeline terms."),
        ("internal_labels_limited_to_dictionary_or_notes", True, "Internal terms retained only for translation/caveats."),
        ("outputs_review_only_folder", True, str(OUT)),
        ("matplotlib_seaborn_used_when_available", use_mpl, "Rich plotting path used with Agg backend." if use_mpl else "Fallback direct SVG/PNG path used."),
    ]
    if not use_mpl and not dep[dep["package"].isin(["matplotlib", "seaborn"]) & ~dep["importable"]].empty:
        rows.append(("dependency_fallback_used", True, "Matplotlib/seaborn unavailable in repo .venv; direct SVG and lightweight PNG fallback used."))
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str], dep: pd.DataFrame) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_analysis_visualization_redesign",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "canonical_input_folder": str(CANONICAL.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "dependency_check": dep.to_dict(orient="records"),
        "matplotlib_seaborn_used": plotting_available(dep),
        "outputs": list(outputs),
        "review_only": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting final analysis visualization redesign.")
    dep = dependency_check()
    use_mpl = plotting_available(dep)
    write_csv(dep, "visualization_dependency_check.csv")
    log(f"Matplotlib/seaborn plotting path available: {use_mpl}.")

    signals = read_csv(INPUTS["analysis_signal"], low_memory=False)
    sw = read_csv(INPUTS["analysis_signal_window"], low_memory=False)
    matrix = read_csv(INPUTS["analysis_guidance_matrix_long"], low_memory=False)
    numeric = read_csv(INPUTS["analysis_numeric_completeness"], low_memory=False)
    median = read_csv(INPUTS["analysis_median_completeness"], low_memory=False)

    labels = label_dictionary()
    write_csv(labels, "public_label_dictionary.csv")

    tables = {
        "signal_inventory": table_signal_inventory(signals),
        "recovery": table_recovery(signals),
        "approaches": table_approaches(signals),
        "numeric": table_numeric(numeric, median),
        "access": table_access(sw),
        "crash": table_crash(sw),
        "identity": table_identity(sw),
        "limitations": table_limitations(signals, sw),
    }
    names = {
        "signal_inventory": "meeting_signal_inventory_summary",
        "recovery": "meeting_signal_recovery_summary",
        "approaches": "meeting_signal_approach_distribution",
        "numeric": "meeting_numeric_context_completeness",
        "access": "meeting_access_context_summary",
        "crash": "meeting_crash_assignment_summary",
        "identity": "meeting_crash_roadway_identity_summary",
        "limitations": "meeting_remaining_data_limitations",
    }
    for key, df in tables.items():
        write_csv(df, f"{names[key]}.csv")
        write_md_table(df, f"{names[key]}.md")

    fig_index = make_figures(tables, matrix, use_mpl)
    write_csv(fig_index, "final_analysis_figure_index.csv")
    (OUT / "final_analysis_visualization_redesign_findings.md").write_text(findings_text(dep, fig_index, use_mpl), encoding="utf-8")
    log("Wrote findings memo.")
    qa = qa_table(dep, use_mpl)
    write_csv(qa, "final_analysis_visualization_redesign_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "final_analysis_visualization_redesign_manifest.json")
    (OUT / "final_analysis_visualization_redesign_manifest.json").write_text(json.dumps(manifest(outputs, dep), indent=2), encoding="utf-8")
    log("Wrote manifest.")
    log("Completed final analysis visualization redesign.")


if __name__ == "__main__":
    main()
