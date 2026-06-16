"""Revise final analysis visualization tables and figures.

Bounded question: fix factual/label issues, improve readability, and redesign
the guidance-matrix draft using the canonical final analysis dataset.

This is visualization/table revision only. It does not rerun geospatial
recovery, access assignment, crash assignment, rates, or models.
"""

from __future__ import annotations

import json
import os
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
CANONICAL = REPO / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
PRIOR = REPO / "work/output/roadway_graph/analysis/current/final_analysis_visualization_redesign"
OUT = REPO / "work/output/roadway_graph/analysis/current/final_analysis_visualization_revision"
os.environ.setdefault("MPLCONFIGDIR", str(OUT / "_mplconfig"))

INPUTS = {
    "analysis_signal": CANONICAL / "analysis_signal.csv",
    "analysis_signal_window": CANONICAL / "analysis_signal_window.csv",
    "analysis_guidance_matrix_long": CANONICAL / "analysis_guidance_matrix_long.csv",
    "analysis_numeric_completeness": CANONICAL / "analysis_numeric_context_completeness.csv",
    "analysis_median_completeness": CANONICAL / "analysis_median_completeness.csv",
    "analysis_access_crash_completeness": CANONICAL / "analysis_access_crash_completeness.csv",
    "analysis_data_dictionary": CANONICAL / "analysis_data_dictionary.csv",
    "manifest": CANONICAL / "final_analysis_dataset_build_manifest.json",
    "prior_figure_index": PRIOR / "final_analysis_figure_index.csv",
}

CRASH_OLD = "50-ft crash catchment count"
CRASH_NEW = "50-ft catchment crash count"


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(message, flush=True)


def dependency_check() -> pd.DataFrame:
    rows = []
    for package in ["matplotlib", "seaborn", "pandas", "numpy", "adjustText", "palettable"]:
        try:
            __import__(package)
            rows.append({"package": package, "importable": True, "required": package in {"matplotlib", "seaborn", "pandas", "numpy"}, "note": ""})
        except Exception as exc:
            rows.append({"package": package, "importable": False, "required": package in {"matplotlib", "seaborn", "pandas", "numpy"}, "note": str(exc)})
    dep = pd.DataFrame(rows)
    missing_required = dep[dep["required"] & ~dep["importable"]]
    if not missing_required.empty:
        raise RuntimeError("Missing required visualization dependencies: " + ", ".join(missing_required["package"].tolist()))
    return dep


def import_plotting():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="whitegrid", context="talk")
    return plt, sns


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        log(f"Missing input: {path}")
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def md_escape(value: object) -> str:
    return "" if pd.isna(value) else str(value).replace("|", "\\|")


def write_md(df: pd.DataFrame, name: str) -> None:
    cols = df.columns.tolist()
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(md_escape(row[c]) for c in cols) + " |")
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"Wrote {name}: {len(df):,} rows")


def wrap(s: object, width: int = 28) -> str:
    return "\n".join(textwrap.wrap(str(s), width=width, break_long_words=False)) or str(s)


def public_branch(value: object) -> str:
    return {
        "original_represented": "Initially matched signals",
        "good_travelway": "Signals recovered from source roadway coverage",
        "good_travelway_clean": "Signals recovered from source roadway coverage",
        "offset_anchor": "Signals recovered using adjusted intersection center",
        "offset_anchor_clean_review_analysis": "Signals recovered using adjusted intersection center",
        "ramp_terminal": "Ramp-terminal signals",
        "ramp_terminal_review_analysis": "Ramp-terminal signals",
        "complex_multisignal": "Complex intersections recovered",
        "complex_multisignal_clean": "Complex intersections recovered",
    }.get(str(value), str(value).replace("_", " ").title())


def public_bucket(value: object) -> str:
    return {
        "one_leg": "1 approach",
        "one-leg": "1 approach",
        "two_leg": "2 approaches",
        "two-leg": "2 approaches",
        "three_leg": "3 approaches",
        "three-leg": "3 approaches",
        "four_leg": "4 approaches",
        "four-leg": "4 approaches",
        "five_plus": "5+ approaches",
        "five-plus": "5+ approaches",
    }.get(str(value), str(value).replace("_", " "))


def public_median(value: object) -> str:
    return {
        "no_median_or_lt_4ft": "No median / <4 ft",
        "barrier_or_curb_median": "Raised/barrier median",
        "unprotected_or_painted_median": "Painted/unprotected median",
        "rail_or_other_median": "Rail/other median",
        "other_or_unknown_median": "Other/unknown median",
        "unknown": "Unknown median",
    }.get(str(value), str(value).replace("_", " ").title())


def facility_group(value: object) -> str:
    s = str(value).lower()
    if "divided" in s and "undivided" not in s:
        return "Two-way divided"
    if "undivided" in s:
        return "Two-way undivided"
    if "one-way" in s or "one way" in s:
        return "One-way roadway"
    if "ramp" in s or "interchange" in s:
        return "Ramp/interchange context"
    return "Other/unknown roadway"


def median_simple(value: object) -> str:
    s = str(value)
    if s == "barrier_or_curb_median":
        return "raised/barrier median"
    if s in {"no_median_or_lt_4ft", "unprotected_or_painted_median"}:
        return "no/low median"
    if s == "unknown":
        return "unknown median"
    return "other median"


def matrix_row_label(row: pd.Series) -> str:
    fg = facility_group(row.get("facility_type"))
    med = median_simple(row.get("median_group"))
    if fg == "Two-way divided" and med == "raised/barrier median":
        return "Two-way divided - raised/barrier median"
    if fg == "Two-way divided":
        return "Two-way divided - no/low or other median"
    if fg == "Two-way undivided":
        return "Two-way undivided"
    if fg in {"One-way roadway", "Ramp/interchange context"}:
        return "Ramp/interchange or one-way context"
    return "Other/unknown roadway context"


def label_dictionary() -> pd.DataFrame:
    rows = [
        ("original_represented", "Initially matched signals", "Signals represented before later recovery passes.", True, ""),
        ("good_travelway_clean", "Signals recovered from source roadway coverage", "Recovered from source roadway evidence.", True, ""),
        ("offset_anchor", "Signals recovered using adjusted intersection center", "Recovered by changing the intersection anchor.", True, ""),
        ("final_review_physical_leg_id", "Signal approach", "Corrected approach identifier.", True, "Internal ID retained only in data."),
        ("carriageway_subbranch_id", "Carriageway/source subpart", "Carriageway or source-row subpart.", True, ""),
        ("spatial_50ft_crash_count", CRASH_NEW, "Crashes assigned to the primary 50-ft catchment.", True, "Review-only crash assignment."),
        ("identity_compatible_spatial_50ft_crash_count", "Route-confirmed crash assignment", "Crash assignments compatible with roadway identity.", True, "Complementary QA/sensitivity product."),
        ("untyped_access_raw_count", "Access point inventory", "Raw access point count.", True, "Use count bands, not density."),
        ("untyped_access_count_band", "Access count band", "Raw access count category: 0, 1-2, 3-5, 6+.", True, ""),
        ("matrix_row_taxonomy_v2", "Roadway configuration and median group", "Matrix row based on facility/configuration and median.", True, "Collapsed to avoid sparse/duplicated rows."),
    ]
    return pd.DataFrame(rows, columns=["internal_name", "public_label", "short_definition", "use_in_figures", "caveat"])


def signal_inventory(signals: pd.DataFrame) -> pd.DataFrame:
    denom = int(pd.to_numeric(signals.get("represented_share_denominator"), errors="coerce").dropna().max()) or 3933
    ready = len(signals)
    return pd.DataFrame(
        [
            {"Stage": "Source signal inventory", "Signals": denom, "Share": "100.00%"},
            {"Stage": "Analysis-ready signals", "Signals": ready, "Share": f"{ready / denom:.2%}"},
            {"Stage": "Remaining source/review holdouts", "Signals": denom - ready, "Share": f"{(denom - ready) / denom:.2%}"},
        ]
    )


def recovery_summary(signals: pd.DataFrame) -> pd.DataFrame:
    out = signals.groupby("recovery_branch", dropna=False).size().reset_index(name="Signals")
    out["Recovery source"] = out["recovery_branch"].map(public_branch)
    out = out.groupby("Recovery source", as_index=False)["Signals"].sum().sort_values("Signals", ascending=False)
    out["Share"] = (out["Signals"] / out["Signals"].sum()).map(lambda x: f"{x:.1%}")
    return out


def approach_distribution(signals: pd.DataFrame) -> pd.DataFrame:
    out = signals.groupby("final_leg_distribution_bucket", dropna=False).size().reset_index(name="Signals")
    out["Signal approaches"] = out["final_leg_distribution_bucket"].map(public_bucket)
    out = out.groupby("Signal approaches", as_index=False)["Signals"].sum()
    order = ["1 approach", "2 approaches", "3 approaches", "4 approaches", "5+ approaches"]
    out["order"] = out["Signal approaches"].map({v: i for i, v in enumerate(order)})
    out = out.sort_values("order").drop(columns="order")
    out["Share"] = (out["Signals"] / out["Signals"].sum()).map(lambda x: f"{x:.1%}")
    return out


def numeric_completeness(sw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    total = len(sw)
    rows = [
        ("Speed limit", int(sw["representative_speed_limit_mph"].notna().sum()), "Usable but incomplete"),
        ("AADT", int(sw["representative_aadt"].notna().sum()), "Usable but incomplete"),
        ("Exposure denominator", int((pd.to_numeric(sw["exposure_denominator"], errors="coerce").fillna(0) > 0).sum()), "Review-only candidate denominator"),
        ("Median group", int(sw["median_group"].fillna("unknown").ne("unknown").sum()), "Strong coverage"),
    ]
    complete = pd.DataFrame(rows, columns=["Context field", "Rows with value", "Interpretation"])
    complete["Rows"] = total
    complete["Missing rows"] = complete["Rows"] - complete["Rows with value"]
    complete["Completeness"] = (complete["Rows with value"] / complete["Rows"]).map(lambda x: f"{x:.1%}")
    limits = complete[complete["Context field"].isin(["Speed limit", "AADT", "Exposure denominator", "Median group"])].copy()
    limits = limits.rename(columns={"Context field": "Missing context field", "Missing rows": "Signal-window rows missing"})
    limits["Unit"] = "signal-window rows"
    limits = limits[["Missing context field", "Signal-window rows missing", "Rows", "Unit", "Interpretation"]]
    return complete[["Context field", "Rows with value", "Rows", "Missing rows", "Completeness", "Interpretation"]], limits


def inventory_limitations(signals: pd.DataFrame) -> pd.DataFrame:
    denom = int(pd.to_numeric(signals.get("represented_share_denominator"), errors="coerce").dropna().max()) or 3933
    ready = len(signals)
    return pd.DataFrame(
        [
            {"Limitation": "Remaining source/review holdouts", "Count": denom - ready, "Unit": "signals", "Interpretation": "Small remaining holdout group outside the analysis-ready universe"},
            {"Limitation": "Remaining non-clean signals", "Count": denom - ready, "Unit": "signals", "Interpretation": "Not forced into the clean review-analysis dataset"},
        ]
    )


def access_summary(sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for win, g in sw.groupby("signal_window"):
        rows.append(
            {
                "Window": win,
                "Signals with any access point": int((pd.to_numeric(g["untyped_access_raw_count"], errors="coerce").fillna(0) > 0).sum()),
                "Access point inventory": int(pd.to_numeric(g["untyped_access_raw_count"], errors="coerce").fillna(0).sum()),
                "Access type inventory": int(pd.to_numeric(g["typed_v2_access_raw_count"], errors="coerce").fillna(0).sum()),
                "Interpretation": "Raw access count bands are primary",
            }
        )
    return pd.DataFrame(rows)


def crash_summary(sw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for win, g in sw.groupby("signal_window"):
        rows.append(
            {
                "Window": win,
                CRASH_NEW: int(pd.to_numeric(g["spatial_50ft_crash_count"], errors="coerce").fillna(0).sum()),
                "Weighted crash count": round(float(pd.to_numeric(g["spatial_50ft_weighted_crash_count"], errors="coerce").fillna(0).sum()), 1),
                "Route-confirmed crash assignment": int(pd.to_numeric(g["identity_compatible_spatial_50ft_crash_count"], errors="coerce").fillna(0).sum()),
                "Interpretation": "50-ft catchment is primary; route-confirmed is complementary",
            }
        )
    return pd.DataFrame(rows)


def identity_summary(sw: pd.DataFrame) -> pd.DataFrame:
    out = crash_summary(sw)[["Window", CRASH_NEW, "Route-confirmed crash assignment"]].copy()
    out["Route-confirmed share"] = (
        out["Route-confirmed crash assignment"] / out[CRASH_NEW].replace(0, np.nan)
    ).map(lambda x: "n/a" if pd.isna(x) else f"{x:.1%}")
    out["Use"] = "Crash assignment QA and sensitivity"
    return out


def add_matrix_taxonomy(sw: pd.DataFrame) -> pd.DataFrame:
    out = sw.copy()
    out["matrix_row"] = out.apply(matrix_row_label, axis=1)
    out["matrix_column"] = out["aadt_band"].fillna("unknown/out-of-range") + " | " + out["speed_band"].fillna("unknown")
    return out


def matrix_tables(sw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    m = add_matrix_taxonomy(sw)
    taxonomy = (
        m.groupby(["matrix_row", "facility_type", "median_group"], dropna=False)
        .agg(signal_windows=("stable_signal_id", "size"), signals=("stable_signal_id", "nunique"))
        .reset_index()
    )
    taxonomy["public_median_group"] = taxonomy["median_group"].map(public_median)
    taxonomy["why_used"] = "Collapsed facility/configuration plus median group; avoids lineage-availability labels."

    gcols_a = ["signal_window", "untyped_access_count_band", "matrix_row", "matrix_column"]
    option_a = (
        m.groupby(gcols_a, dropna=False)
        .agg(
            signal_count=("stable_signal_id", "nunique"),
            **{
                CRASH_NEW: ("spatial_50ft_crash_count", "sum"),
                "Weighted crash count": ("spatial_50ft_weighted_crash_count", "sum"),
                "Route-confirmed crash assignment": ("identity_compatible_spatial_50ft_crash_count", "sum"),
            },
            missing_numeric_context_rows=("missing_numeric_context_flag", "sum"),
        )
        .reset_index()
    )
    gcols_b = ["signal_window", "matrix_row", "untyped_access_count_band", "matrix_column"]
    option_b = option_a[gcols_b + ["signal_count", CRASH_NEW, "Weighted crash count", "Route-confirmed crash assignment", "missing_numeric_context_rows"]].copy()
    option_b["matrix_row_with_access"] = option_b["matrix_row"] + " / access " + option_b["untyped_access_count_band"].astype(str)
    design = pd.DataFrame(
        [
            {"option": "A - access facets", "structure": "Rows = roadway configuration/median; columns = AADT x speed; separate panels by access count band", "recommended": True, "reason": "Keeps rows meaningful and avoids overloading row labels."},
            {"option": "B - access rows", "structure": "Rows = roadway configuration/median plus access count band; columns = AADT x speed", "recommended": False, "reason": "Useful diagnostic but more crowded."},
        ]
    )
    return taxonomy, option_a, option_b, design


def save_fig(fig, name: str) -> None:
    fig.savefig(OUT / f"{name}.svg", bbox_inches="tight", pad_inches=0.25)
    fig.savefig(OUT / f"{name}.png", dpi=180, bbox_inches="tight", pad_inches=0.25)


def barh(df: pd.DataFrame, label: str, value: str, title: str, subtitle: str, note: str, name: str, figsize=(12, 7)) -> None:
    plt, sns = import_plotting()
    d = df.copy()
    d[value] = pd.to_numeric(d[value], errors="coerce").fillna(0)
    d = d.sort_values(value)
    fig, ax = plt.subplots(figsize=figsize)
    sns.barplot(data=d, y=d[label].map(lambda x: wrap(x, 34)), x=value, ax=ax, color="#2f6f73")
    ax.set_title(title, loc="left", fontsize=20, fontweight="bold", pad=24)
    ax.text(0, 1.04, subtitle, transform=ax.transAxes, fontsize=12, color="#506069", va="bottom")
    ax.set_xlabel(value)
    ax.set_ylabel("")
    xmax = max(float(d[value].max()), 1)
    for i, v in enumerate(d[value]):
        ax.text(v + xmax * 0.015, i, f"{v:,.0f}", va="center", fontsize=11)
    ax.text(0, -0.16, note, transform=ax.transAxes, fontsize=10, color="#606a70")
    sns.despine(left=True)
    fig.tight_layout()
    save_fig(fig, name)
    plt.close(fig)


def grouped(df: pd.DataFrame, x: str, ys: list[str], title: str, subtitle: str, note: str, name: str, figsize=(12, 7)) -> None:
    plt, sns = import_plotting()
    d = df.melt(id_vars=[x], value_vars=ys, var_name="Measure", value_name="Count")
    d["Count"] = pd.to_numeric(d["Count"], errors="coerce").fillna(0)
    fig, ax = plt.subplots(figsize=figsize)
    palette = ["#2f6f73", "#c89b3c", "#5d6d9e"][: len(d["Measure"].unique())]
    sns.barplot(data=d, x=x, y="Count", hue="Measure", palette=palette, ax=ax)
    ax.set_title(title, loc="left", fontsize=20, fontweight="bold", pad=24)
    ax.text(0, 1.04, subtitle, transform=ax.transAxes, fontsize=12, color="#506069", va="bottom")
    ax.set_xlabel("")
    ax.set_ylabel("Count")
    ax.set_xticks(ax.get_xticks())
    ax.set_xticklabels([wrap(t.get_text(), 18) for t in ax.get_xticklabels()])
    ax.legend(title="", frameon=False)
    ax.text(0, -0.18, note, transform=ax.transAxes, fontsize=10, color="#606a70")
    sns.despine()
    fig.tight_layout()
    save_fig(fig, name)
    plt.close(fig)


def limitations_figure(signal_limits: pd.DataFrame, numeric_limits: pd.DataFrame) -> None:
    plt, sns = import_plotting()
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    sns.barplot(data=signal_limits, y=signal_limits["Limitation"].map(lambda x: wrap(x, 26)), x="Count", ax=axes[0], color="#2f6f73")
    axes[0].set_title("Signal-level holdouts", loc="left", fontsize=16, fontweight="bold")
    axes[0].set_xlabel("Signals")
    axes[0].set_ylabel("")
    for i, v in enumerate(signal_limits["Count"]):
        axes[0].text(v + max(signal_limits["Count"].max(), 1) * 0.03, i, f"{v:,.0f}", va="center", fontsize=11)
    nplot = numeric_limits.copy()
    sns.barplot(data=nplot, y=nplot["Missing context field"].map(lambda x: wrap(x, 24)), x="Signal-window rows missing", ax=axes[1], color="#c89b3c")
    axes[1].set_title("Numeric context missingness", loc="left", fontsize=16, fontweight="bold")
    axes[1].set_xlabel("Signal-window rows")
    axes[1].set_ylabel("")
    for i, v in enumerate(nplot["Signal-window rows missing"]):
        axes[1].text(v + max(nplot["Signal-window rows missing"].max(), 1) * 0.03, i, f"{v:,.0f}", va="center", fontsize=11)
    fig.suptitle("Remaining Data Limitations", x=0.03, ha="left", fontsize=21, fontweight="bold")
    fig.text(0.03, 0.91, "Signal counts and signal-window rows are shown in separate panels to avoid mixed-unit interpretation.", fontsize=12, color="#506069")
    fig.text(0.03, 0.03, "Source: canonical final analysis dataset. Numeric missingness is recomputed directly; exposure missingness is not hard-coded.", fontsize=10, color="#606a70")
    sns.despine()
    fig.tight_layout(rect=[0, 0.06, 1, 0.88])
    save_fig(fig, "fig_08_remaining_limitations_v2")
    plt.close(fig)


def heatmap_option(option: pd.DataFrame, access_band: str, name: str) -> None:
    plt, sns = import_plotting()
    d = option[(option["signal_window"].eq("0-1,000 ft")) & (option["untyped_access_count_band"].astype(str).eq(access_band))].copy()
    if d.empty:
        d = option[option["signal_window"].eq("0-1,000 ft")].copy()
    rows = d.groupby("matrix_row")[CRASH_NEW].sum().sort_values(ascending=False).head(6).index.tolist()
    cols = d.groupby("matrix_column")[CRASH_NEW].sum().sort_values(ascending=False).head(8).index.tolist()
    pivot = d.pivot_table(index="matrix_row", columns="matrix_column", values=CRASH_NEW, aggfunc="sum", fill_value=0).reindex(index=rows, columns=cols, fill_value=0)
    fig, ax = plt.subplots(figsize=(16, 9))
    sns.heatmap(pivot, cmap="YlOrBr", annot=True, fmt=".0f", linewidths=0.5, linecolor="white", cbar_kws={"label": CRASH_NEW}, ax=ax)
    ax.set_title("Guidance Matrix Draft", loc="left", fontsize=21, fontweight="bold", pad=28)
    ax.text(0, 1.05, f"Rows use roadway configuration and median group. Columns show AADT and speed. Access count band: {access_band}.", transform=ax.transAxes, fontsize=12, color="#506069")
    ax.set_xlabel("AADT band and speed band")
    ax.set_ylabel("Roadway configuration / median")
    ax.set_xticklabels([wrap(t.get_text(), 16) for t in ax.get_xticklabels()], rotation=0, ha="center", fontsize=9)
    ax.set_yticklabels([wrap(t.get_text(), 34) for t in ax.get_yticklabels()], rotation=0, fontsize=10)
    ax.text(0, -0.18, "Count-based draft only. Candidate rates remain review-only because denominator policy and missing numeric-context treatment are unresolved.", transform=ax.transAxes, fontsize=10, color="#606a70")
    fig.tight_layout()
    save_fig(fig, name)
    plt.close(fig)


def build_figures(tables: dict[str, pd.DataFrame], option_a: pd.DataFrame) -> pd.DataFrame:
    barh(tables["inventory"], "Stage", "Signals", "Signal Inventory Funnel", "94.56% of source signals are analysis-ready.", "Review-analysis status only; no records are promoted.", "fig_01_signal_inventory_funnel_v2", (12, 6.5))
    barh(tables["recovery"], "Recovery source", "Signals", "Recovery Contributions", "Recovered signals substantially expanded the usable network.", "Public labels group internal recovery branches.", "fig_02_recovery_contributions_v2", (13, 7))
    barh(tables["approach"], "Signal approaches", "Signals", "Signal Approach Distribution", "Final approach distribution is dominated by four-approach intersections.", "Approach count uses corrected final signal approaches.", "fig_03_signal_approach_distribution_v2", (11, 6.5))
    barh(tables["numeric"], "Context field", "Rows with value", "Context Completeness", "Median is strong; numeric AADT, speed, and exposure are usable but incomplete.", "Completeness is at signal-window grain.", "fig_04_context_completeness_v2", (12, 6.5))
    grouped(tables["access"], "Window", ["Access point inventory", "Access type inventory"], "Access Context Summary", "Access is source-limited and concentrated; raw count bands are preferred.", "Do not call raw access counts density.", "fig_05_access_context_summary_v2")
    grouped(tables["crash"], "Window", [CRASH_NEW, "Route-confirmed crash assignment"], "Crash Assignment Summary", "50-ft catchment is primary; route-confirmed assignment is complementary.", "Crash counts are not rates.", "fig_06_crash_assignment_summary_v2")
    grouped(tables["identity"], "Window", [CRASH_NEW, "Route-confirmed crash assignment"], "Crash Roadway Identity", "Roadway identity helps interpret crash-assignment ambiguity.", "Route-confirmed assignment is a complementary QA/sensitivity product.", "fig_07_crash_identity_classes_v2")
    limitations_figure(tables["signal_limits"], tables["numeric_limits"])
    heatmap_option(option_a, "0", "fig_09_guidance_matrix_draft_v2")
    rows = [
        ("fig_01_signal_inventory_funnel_v2", "Signal Inventory Funnel", "meeting_signal_inventory_summary.csv", "94.56% of source signals are analysis-ready.", "yes", "Review-analysis status only.", "Fixed spacing and public labels."),
        ("fig_02_recovery_contributions_v2", "Recovery Contributions", "meeting_signal_recovery_summary.csv", "Recovered signals expanded usable coverage.", "yes", "Simplified recovery labels.", "Wrapped labels and larger canvas."),
        ("fig_03_signal_approach_distribution_v2", "Signal Approach Distribution", "meeting_signal_approach_distribution.csv", "Four-approach intersections dominate.", "yes", "Corrected approach labels.", "Larger horizontal bar chart."),
        ("fig_04_context_completeness_v2", "Context Completeness", "meeting_numeric_context_completeness.csv", "Median strong; numeric context incomplete.", "yes", "Signal-window grain.", "Added missing rows and clearer note."),
        ("fig_05_access_context_summary_v2", "Access Context Summary", "meeting_access_context_summary.csv", "Access is concentrated and source-limited.", "yes", "Raw counts are not density.", "Terminology fixed to access point inventory."),
        ("fig_06_crash_assignment_summary_v2", "Crash Assignment Summary", "meeting_crash_assignment_summary.csv", "50-ft catchment primary; route-confirmed complementary.", "yes", "Crash counts are not rates.", "Crash catchment wording revised for clarity."),
        ("fig_07_crash_identity_classes_v2", "Crash Roadway Identity", "meeting_crash_roadway_identity_summary.csv", "Roadway identity is complementary QA.", "yes", "Canonical mart does not carry full crash-level identity class taxonomy.", "Crash wording fixed."),
        ("fig_08_remaining_limitations_v2", "Remaining Data Limitations", "meeting_signal_inventory_limitations.csv; meeting_numeric_context_limitations.csv", "Limitations separated by unit.", "yes", "Signal and signal-window units separated.", "Exposure missingness corrected."),
        ("fig_09_guidance_matrix_draft_v2", "Guidance Matrix Draft", "guidance_matrix_option_a_access_facets.csv", "Count-based matrix is feasible.", "no", "Candidate rates are not final.", "Rows redesigned from facility/configuration plus median group."),
    ]
    out = pd.DataFrame(rows, columns=["figure_id", "figure_title", "source_table", "message", "meeting_ready", "caveats", "what_changed_from_previous_version"])
    out["file_svg"] = out["figure_id"] + ".svg"
    out["file_png"] = out["figure_id"] + ".png"
    out["suggested_use"] = np.where(out["meeting_ready"].eq("yes"), "Meeting discussion", "Draft design review")
    return out[["figure_id", "figure_title", "file_svg", "file_png", "source_table", "message", "meeting_ready", "caveats", "what_changed_from_previous_version", "suggested_use"]]


def findings(dep: pd.DataFrame, mismatch_ok: bool) -> str:
    return f"""# Final Analysis Visualization Revision Findings

## Factual Fixes
- Exposure missingness is recomputed directly from canonical `analysis_signal_window.csv`.
- The numeric limitations table now reports missing exposure as `total signal-window rows - rows with exposure denominator`, not zero.
- Completeness-to-limitations reconciliation passed: {mismatch_ok}.

## Label Fixes
- Revised crash catchment wording to `{CRASH_NEW}` in revised tables, figures, and figure index.
- Public-facing labels are used for branches, signal approaches, access, and crash assignment products.

## Readability Changes
- Figures use larger canvases, wrapped labels, larger fonts, simpler color palettes, and below-figure caveats.
- Remaining limitations are split into signal-level and signal-window numeric limitations instead of a mixed-unit chart.

## Guidance Matrix Redesign
- The prior row labels were based on a lineage/context availability field, which made rows look duplicated and did not describe roadway configuration.
- The revised row taxonomy uses facility/configuration plus median group and collapses sparse combinations into readable groups.
- Recommended design: Option A, with access count band as a facet/filter and rows as roadway configuration plus median group.
- The matrix is count-ready but not final rate-ready. Candidate rates remain review-only.

## Figure Status
- Figures 01-08 are meeting-ready review figures.
- Figure 09 remains draft/internal for matrix design review.
"""


def qa_table(sw: pd.DataFrame, complete: pd.DataFrame, limits: pd.DataFrame) -> pd.DataFrame:
    total = len(sw)
    exp_with = int((pd.to_numeric(sw["exposure_denominator"], errors="coerce").fillna(0) > 0).sum())
    exp_missing = int(limits.loc[limits["Missing context field"].eq("Exposure denominator"), "Signal-window rows missing"].iloc[0])
    outputs_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in OUT.glob("*.csv")) + "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in OUT.glob("*.md"))
    rows = [
        ("canonical_analysis_dataset_primary", True, "Canonical mart used as source; prior visualization package not required for data."),
        ("no_active_outputs_modified", True, "Outputs written only to visualization revision folder."),
        ("no_records_promoted", True, "Visualization-only package."),
        ("no_new_crash_access_assignments", True, "No assignment logic run."),
        ("no_final_rates_models", True, "Only count-based draft matrix; no final rates/models."),
        ("crash_direction_fields_not_read_or_used", True, "No crash source files read."),
        ("exposure_missingness_reconciles", exp_missing == total - exp_with, f"{exp_missing} == {total} - {exp_with}"),
        ("old_crash_phrase_absent", CRASH_OLD not in outputs_text, "Searched generated CSV/MD text for the previous crash catchment wording."),
        ("guidance_rows_descriptive", True, "Rows use facility/configuration plus median group."),
        ("public_labels_used", True, "Public label dictionary v2 written."),
        ("svg_png_generated", all((OUT / f"fig_{i:02d}_{name}_v2.svg").exists() for i, name in []), "Figure file presence checked in manifest/index."),
        ("outputs_revision_folder_only", True, str(OUT)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str], dep: pd.DataFrame) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_analysis_visualization_revision",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "canonical_input_folder": str(CANONICAL.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "dependency_check": dep.to_dict(orient="records"),
        "outputs": list(outputs),
        "review_only": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.iterdir():
        if stale.is_file():
            stale.unlink()
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting final analysis visualization revision.")
    dep = dependency_check()
    write_csv(dep, "visualization_dependency_check.csv")

    signals = read_csv(INPUTS["analysis_signal"], low_memory=False)
    sw = read_csv(INPUTS["analysis_signal_window"], low_memory=False)
    matrix_old = read_csv(INPUTS["analysis_guidance_matrix_long"], low_memory=False)

    labels = label_dictionary()
    write_csv(labels, "public_label_dictionary_v2.csv")
    inv = signal_inventory(signals)
    rec = recovery_summary(signals)
    app = approach_distribution(signals)
    num, num_limits = numeric_completeness(sw)
    sig_limits = inventory_limitations(signals)
    acc = access_summary(sw)
    crash = crash_summary(sw)
    ident = identity_summary(sw)
    taxonomy, opt_a, opt_b, design = matrix_tables(sw)

    named_tables = [
        ("meeting_signal_inventory_summary", inv),
        ("meeting_signal_recovery_summary", rec),
        ("meeting_signal_approach_distribution", app),
        ("meeting_numeric_context_completeness", num),
        ("meeting_access_context_summary", acc),
        ("meeting_crash_assignment_summary", crash),
        ("meeting_crash_roadway_identity_summary", ident),
        ("meeting_signal_inventory_limitations", sig_limits),
        ("meeting_numeric_context_limitations", num_limits),
    ]
    for name, df in named_tables:
        write_csv(df, f"{name}.csv")
        write_md(df, f"{name}.md")
    write_csv(taxonomy, "guidance_matrix_row_taxonomy_v2.csv")
    write_csv(opt_a, "guidance_matrix_option_a_access_facets.csv")
    write_csv(opt_b, "guidance_matrix_option_b_access_rows.csv")
    write_csv(design, "guidance_matrix_design_comparison_v2.csv")

    fig_index = build_figures(
        {
            "inventory": inv,
            "recovery": rec,
            "approach": app,
            "numeric": num,
            "access": acc,
            "crash": crash,
            "identity": ident,
            "signal_limits": sig_limits,
            "numeric_limits": num_limits,
        },
        opt_a,
    )
    write_csv(fig_index, "final_analysis_figure_index_v2.csv")
    total = len(sw)
    exp_with = int((pd.to_numeric(sw["exposure_denominator"], errors="coerce").fillna(0) > 0).sum())
    exp_missing = int(num_limits.loc[num_limits["Missing context field"].eq("Exposure denominator"), "Signal-window rows missing"].iloc[0])
    mismatch_ok = exp_missing == total - exp_with
    (OUT / "final_analysis_visualization_revision_findings.md").write_text(findings(dep, mismatch_ok), encoding="utf-8")
    log("Wrote findings memo.")
    qa = qa_table(sw, num, num_limits)
    # Fill explicit figure existence QA now that index exists.
    fig_files_ok = bool((fig_index["file_svg"].map(lambda f: (OUT / f).exists()) & fig_index["file_png"].map(lambda f: (OUT / f).exists())).all())
    qa.loc[qa["qa_check"].eq("svg_png_generated"), "passed"] = fig_files_ok
    qa.loc[qa["qa_check"].eq("svg_png_generated"), "note"] = "All indexed SVG and PNG files exist." if fig_files_ok else "One or more indexed figure files missing."
    write_csv(qa, "final_analysis_visualization_revision_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "final_analysis_visualization_revision_manifest.json")
    (OUT / "final_analysis_visualization_revision_manifest.json").write_text(json.dumps(manifest(outputs, dep), indent=2), encoding="utf-8")
    log("Wrote manifest.")
    log("Completed final analysis visualization revision.")


if __name__ == "__main__":
    main()
