# -*- coding: utf-8 -*-
"""
PHASE 3 FIGURES: Directional Functional Segment QA / Diagnostics
VERSION: 2026.3a

Purpose
-------
Create review figures for the outputs of thirdstep.py, focusing on:
- upstream / downstream / at-signal directional labeling
- final segment crash and access densities
- direction-source confidence
- QC flags from claim resolution / neighbor trimming / missing IDs
- measure-space diagnostics (Delta_M)

Output folder: <ProjectFolder>/thirdstepfigures
Primary input: Final_Functional_Segments
Optional inputs: QC_ThirdStep, Final_Functional_Zones_Stage3, QC_CrashesFarSnap

This script is intentionally defensive:
- it auto-detects fields when possible
- it skips figures gracefully when a field is missing
- it does not modify GIS data

This patched version removes the seaborn dependency so it can run in the
ArcGIS Pro GeoPandas environment without additional package installs.
"""

import os
import re
import arcpy
import pandas as pd
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ==============================================================================
# CONFIG
# ==============================================================================
INPUT_LAYER = "Final_Functional_Segments"
OPTIONAL_QC_TABLE = "QC_ThirdStep"
OPTIONAL_ZONES_LAYER = "Final_Functional_Zones_Stage3"
OPTIONAL_FAR_CRASH_LAYER = "QC_CrashesFarSnap"

MIN_LEN_FT = 50.0
CLIP_PCT_DEFAULT = 99.0
CLIP_PCT_SCATTER = 99.0
CLIP_PCT_HIST = 99.0
TOP_N = 12

# ==============================================================================
# HELPERS
# ==============================================================================
def msg(s: str):
    try:
        arcpy.AddMessage(s)
    except Exception:
        pass
    print(s)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def safe_savefig(path: str):
    plt.tight_layout()
    plt.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()


def to_float(x, default=np.nan):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def to_int(x, default=0):
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return default
        return int(x)
    except Exception:
        return default


def clip_series(s: pd.Series, pct: float):
    s2 = pd.to_numeric(s, errors="coerce")
    if s2.dropna().empty:
        return s2
    hi = np.nanpercentile(s2, pct)
    return s2.clip(lower=0, upper=hi)


def winsorize_df(df: pd.DataFrame, cols, pct=99.0):
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = clip_series(out[c], pct)
    return out


def find_field(fields, patterns):
    up = {f.upper(): f for f in fields}
    for patt in patterns:
        patt_up = patt.upper()
        for fu, f_orig in up.items():
            if patt_up in fu:
                return f_orig
    return None


def safe_label(s):
    s = str(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def bin_speed(s):
    try:
        if pd.isna(s):
            return "Unknown"
        s = float(s)
    except Exception:
        return "Unknown"
    if s <= 35:
        return "Low (<=35)"
    elif s <= 45:
        return "Med (40-45)"
    else:
        return "High (>=50)"


def set_basic_style():
    plt.rcParams.update({
        "figure.figsize": (10, 6),
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.axisbelow": True,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "legend.fontsize": 9,
    })


def maybe_barplot(x=None, y=None, hue=None, data=None, order=None,
                  title=None, xlabel=None, ylabel=None, outfile=None,
                  figsize=(10, 6), estimator=np.mean, rotate_xticks=0):
    if data is None or x is None or y is None:
        return
    if x not in data.columns or y not in data.columns:
        return
    plot_df = data.copy()
    if order is None:
        order = list(pd.unique(plot_df[x]))
    else:
        order = [v for v in order if v in set(plot_df[x])]
    if not order:
        return

    plt.figure(figsize=figsize)
    ax = plt.gca()

    if hue and hue in plot_df.columns:
        hue_vals = [h for h in pd.unique(plot_df[hue]) if pd.notna(h)]
        n_hue = max(len(hue_vals), 1)
        x_pos = np.arange(len(order), dtype=float)
        width = min(0.8 / n_hue, 0.35)
        offsets = (np.arange(n_hue) - (n_hue - 1) / 2.0) * width

        for i, hv in enumerate(hue_vals):
            sub = plot_df[plot_df[hue] == hv]
            agg = sub.groupby(x, as_index=False)[y].agg(estimator)
            val_map = dict(zip(agg[x], agg[y]))
            heights = [val_map.get(cat, 0) for cat in order]
            ax.bar(x_pos + offsets[i], heights, width=width, label=str(hv), alpha=0.9)

        ax.set_xticks(x_pos)
        ax.set_xticklabels(order, rotation=rotate_xticks)
        ax.legend(title=hue)
    else:
        agg = plot_df.groupby(x, as_index=False)[y].agg(estimator)
        val_map = dict(zip(agg[x], agg[y]))
        heights = [val_map.get(cat, 0) for cat in order]
        ax.bar(order, heights, alpha=0.9)
        ax.tick_params(axis="x", rotation=rotate_xticks)

    if title:
        plt.title(title)
    if xlabel is not None:
        plt.xlabel(xlabel)
    if ylabel is not None:
        plt.ylabel(ylabel)
    if outfile:
        safe_savefig(outfile)
    else:
        plt.close()


def maybe_boxplot(df, x, y, title, xlabel, ylabel, outfile, figsize=(10, 6), hue=None):
    if x not in df.columns or y not in df.columns:
        return
    sub_cols = [x, y] + ([hue] if hue and hue in df.columns else [])
    sub = df[sub_cols].dropna().copy()
    if sub.empty:
        return

    plt.figure(figsize=figsize)
    ax = plt.gca()

    if hue and hue in sub.columns:
        x_vals = list(pd.unique(sub[x]))
        hue_vals = list(pd.unique(sub[hue]))
        n_hue = max(len(hue_vals), 1)
        x_pos = np.arange(len(x_vals), dtype=float)
        width = min(0.8 / n_hue, 0.35)
        offsets = (np.arange(n_hue) - (n_hue - 1) / 2.0) * width

        for i, hv in enumerate(hue_vals):
            data_arrays = []
            for xv in x_vals:
                arr = sub[(sub[x] == xv) & (sub[hue] == hv)][y].to_numpy()
                data_arrays.append(arr if len(arr) else np.array([np.nan]))
            bp = ax.boxplot(
                data_arrays,
                positions=x_pos + offsets[i],
                widths=width * 0.9,
                patch_artist=True,
                showfliers=False,
                manage_ticks=False,
            )
            for patch in bp["boxes"]:
                patch.set_alpha(0.6)
            bp["boxes"][0].set_label(str(hv))

        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_vals, rotation=20)
        ax.legend(title=hue)
    else:
        groups = [sub[sub[x] == xv][y].to_numpy() for xv in pd.unique(sub[x])]
        labels = list(pd.unique(sub[x]))
        ax.boxplot(groups, labels=labels, showfliers=False, patch_artist=True)
        ax.tick_params(axis="x", rotation=20)

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    safe_savefig(outfile)


def maybe_hist(df, col, title, xlabel, outfile, hue=None, bins=40, figsize=(10, 6)):
    if col not in df.columns:
        return
    sub_cols = [col] + ([hue] if hue and hue in df.columns else [])
    sub = df[sub_cols].dropna().copy()
    if sub.empty:
        return

    plt.figure(figsize=figsize)
    ax = plt.gca()

    if hue and hue in sub.columns:
        for hv in pd.unique(sub[hue]):
            arr = pd.to_numeric(sub.loc[sub[hue] == hv, col], errors="coerce").dropna().to_numpy()
            if len(arr):
                ax.hist(arr, bins=bins, histtype="step", linewidth=1.5, label=str(hv))
        ax.legend(title=hue)
    else:
        arr = pd.to_numeric(sub[col], errors="coerce").dropna().to_numpy()
        if len(arr):
            ax.hist(arr, bins=bins)

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel("Count")
    safe_savefig(outfile)


def maybe_scatter(df, x, y, hue, title, xlabel, ylabel, outfile, figsize=(10, 6), alpha=0.45, s=20):
    if x not in df.columns or y not in df.columns:
        return
    sub_cols = [x, y] + ([hue] if hue and hue in df.columns else [])
    sub = df[sub_cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    if sub.empty:
        return

    plt.figure(figsize=figsize)
    ax = plt.gca()
    if hue and hue in sub.columns:
        for hv in pd.unique(sub[hue]):
            part = sub[sub[hue] == hv]
            ax.scatter(part[x], part[y], alpha=alpha, s=s, label=str(hv))
        ax.legend(title=hue)
    else:
        ax.scatter(sub[x], sub[y], alpha=alpha, s=s)

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    safe_savefig(outfile)


# ==============================================================================
# RESOLVE PROJECT FOLDER / FIGURES FOLDER
# ==============================================================================
try:
    project_gdb = arcpy.env.workspace or arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
    project_folder = os.path.dirname(project_gdb)
except Exception:
    project_folder = r"C:\Temp"

figures_folder = os.path.join(project_folder, "thirdstepfigures")
ensure_dir(figures_folder)
set_basic_style()

msg("--- GENERATING THIRDSTEP QA / DIRECTIONAL FIGURES ---")
msg(f"Workspace: {arcpy.env.workspace}")
msg(f"Reading layer: {INPUT_LAYER}")
msg(f"Saving figures to: {figures_folder}")

# ==============================================================================
# LOAD FINAL SEGMENTS
# ==============================================================================
if not arcpy.Exists(INPUT_LAYER):
    raise FileNotFoundError(
        f"Input layer '{INPUT_LAYER}' not found in workspace '{arcpy.env.workspace}'. "
        f"Run thirdstep.py first."
    )

all_fields = [f.name for f in arcpy.ListFields(INPUT_LAYER)]
msg(f"Field count in final segments: {len(all_fields)}")

required = ["SegOID", "Seg_Len_Ft"]
missing_req = [f for f in required if f not in all_fields]
if missing_req:
    raise RuntimeError(f"Missing required fields in {INPUT_LAYER}: {missing_req}")

flow_field = find_field(all_fields, ["FLOW_ROLE"])
dirsource_field = find_field(all_fields, ["DIRSOURCE"])
zone_field = find_field(all_fields, ["ZONE_TYPE"])
speed_field = find_field(all_fields, ["ASSIGNED_SPEED"])
aadt_field = find_field(all_fields, ["AADT"])
side_field = find_field(all_fields, ["SIDE_CODE"])
delta_field = find_field(all_fields, ["DELTA_M"])
length_field = "Seg_Len_Ft"
access_count_field = find_field(all_fields, ["CNT_ACCESS"])
crash_total_field = find_field(all_fields, ["CNT_CRASH_TOTAL"])
crash_up_field = find_field(all_fields, ["CNT_CRASH_UP"])
crash_down_field = find_field(all_fields, ["CNT_CRASH_DOWN"])
crash_at_field = find_field(all_fields, ["CNT_CRASH_AT"])
access_density_field = find_field(all_fields, ["ACCESS_DENSITY_1K"])
crash_density_field = find_field(all_fields, ["CRASH_DENSITY_1K"])

qc_link_field = find_field(all_fields, ["QC_LINKMISSING"])
qc_overlap_field = find_field(all_fields, ["QC_SIGNALOVERLAP"])
qc_unknown_field = find_field(all_fields, ["QC_DIRECTIONUNKNOWN"])
qc_trim_field = find_field(all_fields, ["QC_TRIMMEDBYNEIGHBOR"])
qc_far_field = find_field(all_fields, ["QC_CRASHFARSNAP"])

count_fields = [f for f in all_fields if f.startswith("Cnt_")]
dir_type_fields = [
    f for f in count_fields
    if f not in {access_count_field, crash_total_field, crash_up_field, crash_down_field, crash_at_field}
]

msg("Detected fields:")
for lbl, val in [
    ("Flow_Role", flow_field),
    ("DirSource", dirsource_field),
    ("Zone_Type", zone_field),
    ("Assigned_Speed", speed_field),
    ("AADT", aadt_field),
    ("Delta_M", delta_field),
    ("Cnt_Access", access_count_field),
    ("Cnt_Crash_Total", crash_total_field),
    ("Cnt_Crash_Up", crash_up_field),
    ("Cnt_Crash_Down", crash_down_field),
    ("Cnt_Crash_At", crash_at_field),
    ("Access_Density_1k", access_density_field),
    ("Crash_Density_1k", crash_density_field),
]:
    msg(f"  {lbl}: {val}")

cursor_fields = ["SegOID", length_field]
for f in [
    flow_field, dirsource_field, zone_field, speed_field, aadt_field, side_field, delta_field,
    access_count_field, crash_total_field, crash_up_field, crash_down_field, crash_at_field,
    access_density_field, crash_density_field,
    qc_link_field, qc_overlap_field, qc_unknown_field, qc_trim_field, qc_far_field
] + dir_type_fields:
    if f and f not in cursor_fields:
        cursor_fields.append(f)

rows = []
with arcpy.da.SearchCursor(INPUT_LAYER, cursor_fields) as cur:
    for row in cur:
        rec = dict(zip(cursor_fields, row))
        seg_len = to_float(rec.get(length_field), default=np.nan)
        if np.isnan(seg_len) or seg_len < MIN_LEN_FT:
            continue

        out = {
            "SegOID": rec.get("SegOID"),
            "Length_Ft": seg_len,
            "Flow_Role": safe_label(rec.get(flow_field, "Unknown")) if flow_field else "Unknown",
            "DirSource": safe_label(rec.get(dirsource_field, "Unknown")) if dirsource_field else "Unknown",
            "Zone": safe_label(rec.get(zone_field, "Unknown")) if zone_field else "Unknown",
            "Speed": to_float(rec.get(speed_field), default=np.nan) if speed_field else np.nan,
            "AADT": to_float(rec.get(aadt_field), default=np.nan) if aadt_field else np.nan,
            "Side_Code": safe_label(rec.get(side_field, "Unknown")) if side_field else "Unknown",
            "Delta_M": to_float(rec.get(delta_field), default=np.nan) if delta_field else np.nan,
            "Access_Count": to_int(rec.get(access_count_field), default=0) if access_count_field else 0,
            "Crash_Total": to_int(rec.get(crash_total_field), default=0) if crash_total_field else 0,
            "Crash_Up": to_int(rec.get(crash_up_field), default=0) if crash_up_field else 0,
            "Crash_Down": to_int(rec.get(crash_down_field), default=0) if crash_down_field else 0,
            "Crash_At": to_int(rec.get(crash_at_field), default=0) if crash_at_field else 0,
            "QC_LinkMissing": to_int(rec.get(qc_link_field), default=0) if qc_link_field else 0,
            "QC_SignalOverlap": to_int(rec.get(qc_overlap_field), default=0) if qc_overlap_field else 0,
            "QC_DirectionUnknown": to_int(rec.get(qc_unknown_field), default=0) if qc_unknown_field else 0,
            "QC_TrimmedByNeighbor": to_int(rec.get(qc_trim_field), default=0) if qc_trim_field else 0,
            "QC_CrashFarSnap": to_int(rec.get(qc_far_field), default=0) if qc_far_field else 0,
        }

        out["Access_Density_1k"] = (
            to_float(rec.get(access_density_field), default=np.nan)
            if access_density_field else (out["Access_Count"] / out["Length_Ft"]) * 1000.0
        )
        out["Crash_Density_1k"] = (
            to_float(rec.get(crash_density_field), default=np.nan)
            if crash_density_field else (out["Crash_Total"] / out["Length_Ft"]) * 1000.0
        )

        for f in dir_type_fields:
            out[f] = to_int(rec.get(f), default=0)

        rows.append(out)

df = pd.DataFrame(rows)
if df.empty:
    raise RuntimeError("No usable segment rows after applying the minimum length filter.")

if aadt_field:
    df["AADT_forRate"] = df["AADT"].replace([0, np.nan], 1000.0)
    df["Length_Miles"] = df["Length_Ft"] / 5280.0
    df["VMT_Daily"] = df["AADT_forRate"] * df["Length_Miles"]
    df["Crash_Rate_MVMT"] = (df["Crash_Total"] * 1_000_000.0) / (df["VMT_Daily"] * 365.0 * 3.0)
    df["Crash_Rate_MVMT"] = df["Crash_Rate_MVMT"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
else:
    df["Crash_Rate_MVMT"] = np.nan

if speed_field:
    df["Speed_Bin"] = df["Speed"].apply(bin_speed)
else:
    df["Speed_Bin"] = "Unknown"

msg(f"Rows in dataframe after filtering: {len(df)}")
msg(f"Flow roles present: {sorted(df['Flow_Role'].dropna().unique())}")

# ==============================================================================
# FIG 0: segment count by flow role
# ==============================================================================
flow_counts = df["Flow_Role"].fillna("Unknown").value_counts().reset_index()
flow_counts.columns = ["Flow_Role", "Segments"]
maybe_barplot(
    x="Flow_Role", y="Segments", data=flow_counts,
    title="Segment Count by Final Flow Role",
    xlabel="Flow Role", ylabel="Number of Segments",
    outfile=os.path.join(figures_folder, "Fig0_Segment_Count_By_FlowRole.png"),
    figsize=(11, 6), estimator=np.sum
)

# ==============================================================================
# FIG 1: flow role by zone
# ==============================================================================
if zone_field and flow_field:
    zf = df.groupby(["Zone", "Flow_Role"]).size().reset_index(name="Segments")
    maybe_barplot(
        x="Zone", y="Segments", hue="Flow_Role", data=zf,
        title="Directional Role Mix by Zone",
        xlabel="Zone", ylabel="Number of Segments",
        outfile=os.path.join(figures_folder, "Fig1_FlowRole_By_Zone.png"),
        figsize=(12, 6), estimator=np.sum
    )

# ==============================================================================
# FIG 2: crash density by flow role
# ==============================================================================
df2 = winsorize_df(df, ["Crash_Density_1k"], pct=CLIP_PCT_DEFAULT)
maybe_boxplot(
    df2, "Flow_Role", "Crash_Density_1k",
    "Crash Density by Flow Role (Clipped)",
    "Flow Role", "Crashes per 1,000 ft",
    os.path.join(figures_folder, "Fig2_CrashDensity_By_FlowRole.png"),
    figsize=(11, 6)
)

# ==============================================================================
# FIG 3: access density by flow role
# ==============================================================================
df3 = winsorize_df(df, ["Access_Density_1k"], pct=CLIP_PCT_DEFAULT)
maybe_boxplot(
    df3, "Flow_Role", "Access_Density_1k",
    "Access Density by Flow Role (Clipped)",
    "Flow Role", "Access Points per 1,000 ft",
    os.path.join(figures_folder, "Fig3_AccessDensity_By_FlowRole.png"),
    figsize=(11, 6)
)

# ==============================================================================
# FIG 4: directional crash composition by zone
# ==============================================================================
if crash_up_field or crash_down_field or crash_at_field:
    comp = df[["Zone", "Crash_Up", "Crash_Down", "Crash_At"]].copy()
    comp = comp.groupby("Zone", as_index=False).sum()
    comp_m = comp.melt(id_vars="Zone", value_vars=["Crash_Up", "Crash_Down", "Crash_At"],
                       var_name="Crash_Component", value_name="Crash_Count")
    comp_m["Crash_Component"] = comp_m["Crash_Component"].replace({
        "Crash_Up": "Upstream",
        "Crash_Down": "Downstream",
        "Crash_At": "At Signal"
    })
    maybe_barplot(
        x="Zone", y="Crash_Count", hue="Crash_Component", data=comp_m,
        title="Crash Direction Composition by Zone",
        xlabel="Zone", ylabel="Crash Count",
        outfile=os.path.join(figures_folder, "Fig4_CrashDirectionComposition_By_Zone.png"),
        figsize=(12, 6), estimator=np.sum
    )

# ==============================================================================
# FIG 5: direction source confidence distribution
# ==============================================================================
if dirsource_field:
    ds = df["DirSource"].fillna("Unknown").value_counts().reset_index()
    ds.columns = ["DirSource", "Segments"]
    maybe_barplot(
        x="DirSource", y="Segments", data=ds,
        title="Direction Source Distribution",
        xlabel="Direction Source", ylabel="Number of Segments",
        outfile=os.path.join(figures_folder, "Fig5_DirectionSource_Distribution.png"),
        figsize=(13, 6), estimator=np.sum, rotate_xticks=20
    )

# ==============================================================================
# FIG 6: Delta_M distribution by flow role
# ==============================================================================
if delta_field:
    d6 = winsorize_df(df, ["Delta_M"], pct=CLIP_PCT_HIST).copy()
    d6 = d6[np.isfinite(d6["Delta_M"])]
    if not d6.empty:
        maybe_hist(
            d6, "Delta_M",
            "Projected Measure Offset from Signal (Delta_M)",
            "Delta_M (segment midpoint measure - signal measure)",
            os.path.join(figures_folder, "Fig6_DeltaM_Distribution.png"),
            hue="Flow_Role", bins=50, figsize=(12, 6)
        )
        # Add zero line on a second pass for consistency.
        plt.figure(figsize=(12, 6))
        ax = plt.gca()
        for hv in pd.unique(d6["Flow_Role"]):
            arr = pd.to_numeric(d6.loc[d6["Flow_Role"] == hv, "Delta_M"], errors="coerce").dropna().to_numpy()
            if len(arr):
                ax.hist(arr, bins=50, histtype="step", linewidth=1.5, label=str(hv))
        ax.axvline(0, linestyle="--", linewidth=1)
        ax.legend(title="Flow_Role")
        plt.title("Projected Measure Offset from Signal (Delta_M)")
        plt.xlabel("Delta_M (segment midpoint measure - signal measure)")
        plt.ylabel("Count")
        safe_savefig(os.path.join(figures_folder, "Fig6_DeltaM_Distribution.png"))

# ==============================================================================
# FIG 7: QC flag counts from final segments
# ==============================================================================
qc_counts = pd.DataFrame([
    {"QC_Flag": "Missing LinkID", "Count": int(df["QC_LinkMissing"].sum())},
    {"QC_Flag": "Unknown Direction", "Count": int(df["QC_DirectionUnknown"].sum())},
    {"QC_Flag": "Overlap Claim", "Count": int(df["QC_SignalOverlap"].sum())},
    {"QC_Flag": "Trimmed By Neighbor", "Count": int(df["QC_TrimmedByNeighbor"].sum())},
    {"QC_Flag": "Crash Far Snap", "Count": int(df["QC_CrashFarSnap"].sum())},
])
maybe_barplot(
    x="QC_Flag", y="Count", data=qc_counts,
    title="Final QC Flag Counts",
    xlabel="QC Flag", ylabel="Flagged Segments",
    outfile=os.path.join(figures_folder, "Fig7_QCFlag_Counts.png"),
    figsize=(13, 6), estimator=np.sum, rotate_xticks=15
)

# ==============================================================================
# FIG 8: crash density by QC status
# ==============================================================================
qc_compare_rows = []
for qc_name in ["QC_LinkMissing", "QC_DirectionUnknown", "QC_SignalOverlap", "QC_TrimmedByNeighbor"]:
    if qc_name not in df.columns:
        continue
    tmp = df[[qc_name, "Crash_Density_1k"]].copy()
    tmp["QC_Group"] = qc_name.replace("QC_", "")
    tmp["Flag_Status"] = tmp[qc_name].map({1: "Flagged", 0: "Not Flagged"}).fillna("Not Flagged")
    qc_compare_rows.append(tmp[["QC_Group", "Flag_Status", "Crash_Density_1k"]])
if qc_compare_rows:
    d8 = pd.concat(qc_compare_rows, ignore_index=True)
    d8 = winsorize_df(d8, ["Crash_Density_1k"], pct=CLIP_PCT_DEFAULT)
    maybe_boxplot(
        d8, "QC_Group", "Crash_Density_1k",
        "Crash Density for Flagged vs Non-Flagged Segments",
        "QC Group", "Crashes per 1,000 ft",
        os.path.join(figures_folder, "Fig8_CrashDensity_By_QCStatus.png"),
        figsize=(14, 6), hue="Flag_Status"
    )

# ==============================================================================
# FIG 9: AADT vs crash density scatter
# ==============================================================================
if aadt_field:
    d9 = df[["AADT", "Crash_Density_1k", "Flow_Role"]].copy()
    d9 = winsorize_df(d9, ["AADT", "Crash_Density_1k"], pct=CLIP_PCT_SCATTER)
    d9 = d9.replace([np.inf, -np.inf], np.nan).dropna()
    if len(d9) > 10:
        maybe_scatter(
            d9, "AADT", "Crash_Density_1k", "Flow_Role",
            "AADT vs Crash Density by Flow Role (Clipped)",
            "AADT", "Crashes per 1,000 ft",
            os.path.join(figures_folder, "Fig9_AADT_vs_CrashDensity.png"),
            figsize=(10, 6), alpha=0.45, s=20
        )

# ==============================================================================
# FIG 10: crash rate by speed environment
# ==============================================================================
if speed_field and aadt_field:
    d10 = winsorize_df(df, ["Crash_Rate_MVMT"], pct=CLIP_PCT_DEFAULT)
    maybe_barplot(
        x="Speed_Bin", y="Crash_Rate_MVMT", hue="Flow_Role", data=d10,
        order=["Low (<=35)", "Med (40-45)", "High (>=50)", "Unknown"],
        title="Crash Rate (MVMT) by Speed Environment and Flow Role",
        xlabel="Speed Environment", ylabel="Crashes per MVMT",
        outfile=os.path.join(figures_folder, "Fig10_CrashRateMVMT_By_SpeedAndFlow.png"),
        figsize=(13, 6)
    )

# ==============================================================================
# FIG 11: most common directional crash-type counts
# ==============================================================================
if dir_type_fields:
    totals = df[dir_type_fields].sum().sort_values(ascending=False)
    top = totals.head(TOP_N)
    top_df = top.reset_index()
    top_df.columns = ["Count_Field", "Crash_Count"]
    top_df["Crash_Type_Direction"] = (
        top_df["Count_Field"]
        .str.replace("Cnt_", "", regex=False)
        .str.replace("_", " ", regex=False)
    )
    top_df.to_csv(os.path.join(figures_folder, "DirectionalCrashType_Counts_Top.csv"), index=False)

    plt.figure(figsize=(12, 7))
    ax = plt.gca()
    ax.barh(top_df["Crash_Type_Direction"], top_df["Crash_Count"])
    ax.invert_yaxis()
    plt.title(f"Top {len(top_df)} Directional Crash-Type Counts")
    plt.xlabel("Crash Count")
    plt.ylabel("Crash Type + Direction Bucket")
    safe_savefig(os.path.join(figures_folder, "Fig11_TopDirectionalCrashTypes.png"))

# ==============================================================================
# FIG 12: QC table summary if present
# ==============================================================================
if arcpy.Exists(OPTIONAL_QC_TABLE):
    q_fields = [f.name for f in arcpy.ListFields(OPTIONAL_QC_TABLE)]
    if all(x in q_fields for x in ["QC_Type", "QC_Value", "QC_Count"]):
        q_rows = []
        with arcpy.da.SearchCursor(OPTIONAL_QC_TABLE, ["QC_Type", "QC_Value", "QC_Count"]) as cur:
            for a, b, c in cur:
                q_rows.append({
                    "QC_Type": safe_label(a),
                    "QC_Value": safe_label(b),
                    "QC_Count": to_int(c, default=0)
                })
        qdf = pd.DataFrame(q_rows)
        if not qdf.empty:
            qdf.to_csv(os.path.join(figures_folder, "QC_ThirdStep_Summary.csv"), index=False)
            qplot = qdf.sort_values("QC_Count", ascending=False).head(20)
            # Build a readable combined label to avoid complicated hue grouping.
            qplot = qplot.copy()
            qplot["QC_Label"] = qplot["QC_Type"] + " | " + qplot["QC_Value"]
            plt.figure(figsize=(13, 8))
            ax = plt.gca()
            ax.barh(qplot["QC_Label"], qplot["QC_Count"])
            ax.invert_yaxis()
            plt.title("QC_ThirdStep Top Counts")
            plt.xlabel("Count")
            plt.ylabel("QC Value")
            safe_savefig(os.path.join(figures_folder, "Fig12_QCTable_TopCounts.png"))

# ==============================================================================
# OPTIONAL SUMMARY CSV FOR DEBUGGING
# ==============================================================================
summary = pd.DataFrame([
    {"Metric": "SegmentRowsUsed", "Value": int(len(df))},
    {"Metric": "UnknownDirectionSegments", "Value": int(df["QC_DirectionUnknown"].sum())},
    {"Metric": "MissingLinkIDSegments", "Value": int(df["QC_LinkMissing"].sum())},
    {"Metric": "OverlapClaimSegments", "Value": int(df["QC_SignalOverlap"].sum())},
    {"Metric": "TrimmedByNeighborSegments", "Value": int(df["QC_TrimmedByNeighbor"].sum())},
    {"Metric": "TotalCrashCount", "Value": int(df["Crash_Total"].sum())},
    {"Metric": "TotalAccessCount", "Value": int(df["Access_Count"].sum())},
])
summary.to_csv(os.path.join(figures_folder, "thirdstepfigures_summary.csv"), index=False)

df.head(5000).to_csv(os.path.join(figures_folder, "thirdstepfigures_debug_sample.csv"), index=False)

msg("--- THIRDSTEP FIGURES COMPLETE ---")
msg(f"Figures written to: {figures_folder}")
