# -*- coding: utf-8 -*-
"""
PHASE 2 FIGURES: Functional Area Zoning Crash & Access Analysis
VERSION: 2026.3 (FIXED FIG2/FIG3/FIG8 + OUTLIER CONTROL + FIELD AUTO-DETECT)

Main fixes:
- Robust field detection for Rear-End and Sideswipe (new naming scheme).
- Fig 2 now plots meaningful Rear-End vs Sideswipe densities by zone.
- Fig 3 regression uses robust regression, sensible axis limits, and optional log scaling.
- Fig 8 distribution is clipped to avoid extreme outliers dominating the view.
- Scatter plots use clipping/log options to remain interpretable.

Output folder: <ProjectFolder>/secondstepfigures
Input layer: Final_Functional_Zones (output of secondstep.py)
"""

import arcpy
import pandas as pd
import seaborn as sns
import os
import numpy as np
import re
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ==============================================================================
# CONFIG
# ==============================================================================
INPUT_LAYER = "Final_Functional_Zones"

# Segment filtering for figure stability (does not change GIS data)
MIN_LEN_FT = 50.0  # should match your segmentation cleanup threshold

# Outlier handling for plots (percentile clipping)
CLIP_PCT_DEFAULT = 99.0
CLIP_PCT_SCATTER = 99.0
CLIP_PCT_HIST = 99.0
CLIP_PCT_REG = 99.0

# Regression options
USE_LOG1P_IN_REGRESSION = False  # set True if you want log1p(y) / log1p(x)
ROBUST_REGRESSION = True         # seaborn regplot robust fit if available

TOP_N = 10


# ==============================================================================
# HELPERS
# ==============================================================================
def msg(s: str):
    try:
        arcpy.AddMessage(s)
    except Exception:
        pass
    print(s)

def safe_savefig(path: str):
    plt.tight_layout()
    plt.savefig(path, dpi=200)
    plt.close()

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def clip_series(s: pd.Series, pct: float):
    """Clip series to [0, percentile] ignoring NaNs."""
    if s.dropna().empty:
        return s
    hi = np.nanpercentile(s, pct)
    return s.clip(lower=0, upper=hi)

def winsorize_df(df: pd.DataFrame, cols, pct=99.0):
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = clip_series(out[c], pct)
    return out

def find_field(fields, patterns):
    """Return first field whose upper name contains any pattern (also upper)."""
    up = {f.upper(): f for f in fields}
    for patt in patterns:
        patt_up = patt.upper()
        for fu, f_orig in up.items():
            if patt_up in fu:
                return f_orig
    return None

def sns_barplot_ci(*, x=None, y=None, hue=None, data=None, order=None, hue_order=None,
                   title=None, xlabel=None, ylabel=None, outfile=None,
                   figsize=(10, 6), estimator=np.mean):
    """Seaborn barplot wrapper compatible with older versions."""
    plt.figure(figsize=figsize)
    try:
        sns.barplot(x=x, y=y, hue=hue, data=data, order=order, hue_order=hue_order,
                    estimator=estimator, errorbar=("ci", 95))
    except TypeError:
        sns.barplot(x=x, y=y, hue=hue, data=data, order=order, hue_order=hue_order,
                    estimator=estimator, ci=95)
    if title:
        plt.title(title)
    if xlabel is not None:
        plt.xlabel(xlabel)
    if ylabel is not None:
        plt.ylabel(ylabel)
    plt.tight_layout()
    if outfile:
        plt.savefig(outfile, dpi=200)
    plt.close()

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


# ==============================================================================
# RESOLVE PROJECT FOLDER / FIGURES FOLDER
# ==============================================================================
try:
    project_gdb = arcpy.env.workspace or arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
    project_folder = os.path.dirname(project_gdb)
except Exception:
    project_folder = r"C:\Temp"

figures_folder = os.path.join(project_folder, "secondstepfigures")
ensure_dir(figures_folder)

msg("--- GENERATING FUNCTIONAL AREA ANALYSIS FIGURES (FIXED) ---")
msg(f"Workspace: {arcpy.env.workspace}")
msg(f"Reading layer: {INPUT_LAYER}")
msg(f"Saving figures to: {figures_folder}")

# ==============================================================================
# 1) EXTRACT DATA
# ==============================================================================
if not arcpy.Exists(INPUT_LAYER):
    raise FileNotFoundError(
        f"Input layer '{INPUT_LAYER}' not found in workspace '{arcpy.env.workspace}'. "
        f"Run secondstep.py first."
    )

all_fields = [f.name for f in arcpy.ListFields(INPUT_LAYER)]
msg(f"Field count: {len(all_fields)}")

# Required core fields
required = ["Zone_Type", "Assigned_Speed", "Cnt_TotalCrash", "Cnt_Access", "Seg_Len_Ft", "AADT"]
missing_req = [f for f in required if f not in all_fields]
if missing_req:
    raise RuntimeError(f"Missing required fields in {INPUT_LAYER}: {missing_req}")

# Detect collision count fields (Cnt_*)
cnt_fields = sorted([f for f in all_fields if f.startswith("Cnt_")])
collision_cnt_fields = [f for f in cnt_fields if f not in ("Cnt_Access", "Cnt_TotalCrash")]

# Detect rear-end and sideswipe fields in your newer naming scheme
rear_cnt_field = find_field(collision_cnt_fields, ["CNT_REAR_END", "CNT_REAREND"])
ss_same_field = find_field(collision_cnt_fields, ["CNT_SIDESWIPE_SAME_DIRECTION", "CNT_SIDESWIPE_SAME"])
ss_opp_field  = find_field(collision_cnt_fields, ["CNT_SIDESWIPE_OPPOSITE_DIRECTION", "CNT_SIDESWIPE_OPPOSITE"])
ss_generic    = find_field(collision_cnt_fields, ["CNT_SIDESWIPE"])  # fallback if only one exists

msg("Detected key crash mechanism fields:")
msg(f"  Rear-End count field: {rear_cnt_field}")
msg(f"  Sideswipe same-dir:   {ss_same_field}")
msg(f"  Sideswipe opp-dir:    {ss_opp_field}")
msg(f"  Sideswipe generic:    {ss_generic}")

# Build cursor fields
fields = [
    "Zone_Type",
    "Assigned_Speed",
    "Cnt_TotalCrash",
    "Cnt_Access",
    "Seg_Len_Ft",
    "AADT",
] + collision_cnt_fields

data_rows = []
with arcpy.da.SearchCursor(INPUT_LAYER, fields) as cur:
    for row in cur:
        zone = row[0]
        speed = row[1]
        total_crashes = row[2]
        access_count = row[3]
        length_ft = row[4]
        aadt = row[5]

        # Filter short segments for figure stability
        if length_ft is None or float(length_ft) < MIN_LEN_FT:
            continue

        rec = {
            "Zone": zone,
            "Speed": to_float(speed),
            "Crashes": to_int(total_crashes),
            "Access_Count": to_int(access_count),
            "Length_Ft": to_float(length_ft, default=np.nan),
            "AADT": to_float(aadt, default=np.nan),
        }

        # Add collision type counts
        base_idx = 6
        for i, f in enumerate(collision_cnt_fields):
            rec[f] = to_int(row[base_idx + i])

        data_rows.append(rec)

df = pd.DataFrame(data_rows)
if df.empty:
    raise RuntimeError("No rows after filtering. Check Seg_Len_Ft or MIN_LEN_FT threshold.")

# Handle AADT missing / zero for MVMT denominators
df["AADT"] = df["AADT"].replace([0, np.nan], 1000.0)

msg(f"Rows in dataframe (after length filter): {len(df)}")
msg(f"Zones present: {df['Zone'].dropna().unique()}")

# ------------------------------------------------------------------------------
# Normalize zone labels for presentation
# ------------------------------------------------------------------------------
ZONE_LABEL_MAP = {
    "Zone 1: Critical": "Zone 1",
    "Zone 2: Functional": "Zone 2",
    "Zone 1 - Critical": "Zone 1",
    "Zone 2 - Functional": "Zone 2",
    "Critical": "Zone 1",
    "Functional": "Zone 2",
}

df["Zone"] = df["Zone"].astype(str).replace(ZONE_LABEL_MAP)

# Optional: force a clean plotting order everywhere
ZONE_ORDER = ["Zone 1", "Zone 2"]

# ==============================================================================
# 2) METRICS
# ==============================================================================
df["Length_Ft"] = df["Length_Ft"].clip(lower=1.0)

df["Crash_Dens_1k"] = (df["Crashes"] / df["Length_Ft"]) * 1000.0

df["Length_Miles"] = df["Length_Ft"] / 5280.0
df["VMT_Daily"] = df["AADT"] * df["Length_Miles"]
df["VMT_Daily"] = df["VMT_Daily"].replace(0, np.nan)

# Assume 3-year study period (consistent with your earlier script)
df["Crash_Rate_MVMT"] = (df["Crashes"] * 1_000_000.0) / (df["VMT_Daily"] * 365.0 * 3.0)
df["Crash_Rate_MVMT"] = df["Crash_Rate_MVMT"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

df["Speed_Bin"] = df["Speed"].apply(bin_speed)

# Access density per 1k ft
df["Access_Dens_1k"] = (df["Access_Count"] / df["Length_Ft"]) * 1000.0

# Per-collision-type densities
dens_cols = []
for c in collision_cnt_fields:
    dens = c.replace("Cnt_", "Dens_1k_")
    df[dens] = (df[c].astype(float) / df["Length_Ft"]) * 1000.0
    dens_cols.append(dens)

# Build mechanism densities (Rear-End & Sideswipe combined)
def dens_for_count_field(cnt_field):
    if cnt_field is None:
        return None
    dens_field = cnt_field.replace("Cnt_", "Dens_1k_")
    if dens_field in df.columns:
        return dens_field
    # If count exists but dens not made for some reason, compute it
    if cnt_field in df.columns:
        df[dens_field] = (df[cnt_field].astype(float) / df["Length_Ft"]) * 1000.0
        return dens_field
    return None

rear_dens_field = dens_for_count_field(rear_cnt_field)

# Sideswipe density: prefer sum of same + opposite if both exist; else generic
ss_dens_fields = []
for f in (ss_same_field, ss_opp_field, ss_generic):
    d = dens_for_count_field(f)
    if d:
        ss_dens_fields.append(d)

# If both same and opposite exist, use only those two (avoid double counting if generic exists)
if ss_same_field and ss_opp_field:
    ss_dens_fields = [dens_for_count_field(ss_same_field), dens_for_count_field(ss_opp_field)]
    ss_dens_fields = [x for x in ss_dens_fields if x]

if ss_dens_fields:
    df["Sideswipe_Dens_1k"] = df[ss_dens_fields].sum(axis=1)
else:
    df["Sideswipe_Dens_1k"] = np.nan

if rear_dens_field:
    df["RearEnd_Dens_1k"] = df[rear_dens_field]
else:
    df["RearEnd_Dens_1k"] = np.nan

# ==============================================================================
# 3) PLOT STYLE
# ==============================================================================
try:
    sns.set_theme(style="whitegrid", context="talk")
except Exception:
    sns.set(style="whitegrid")
    try:
        sns.set_context("talk")
    except Exception:
        pass

# ==============================================================================
# FIG 0: Segment count by zone
# ==============================================================================
zone_counts = df["Zone"].value_counts().reset_index()
zone_counts.columns = ["Zone", "Segments"]

sns_barplot_ci(
    x="Zone", y="Segments", data=zone_counts,
    title="Segment Count by Zone",
    xlabel="Zone", ylabel="Number of Segments",
    outfile=os.path.join(figures_folder, "Fig0_Segment_Count_By_Zone.png"),
    figsize=(10, 5),
    estimator=np.sum  # already aggregated but harmless
)

# ==============================================================================
# FIG 1: Crash density by zone (box)
# ==============================================================================
df_fig1 = winsorize_df(df, ["Crash_Dens_1k"], pct=CLIP_PCT_DEFAULT)
plt.figure(figsize=(10, 6))
sns.boxplot(x="Zone", y="Crash_Dens_1k", order=ZONE_ORDER, data=df_fig1, showfliers=False)
plt.title("Crash Density: Zone 1 vs Zone 2 (Clipped)")
plt.ylabel("Crashes per 1,000 ft")
plt.xlabel("Functional Area Zone")
safe_savefig(os.path.join(figures_folder, "Fig1_Zone_Risk_Comparison.png"))

# ==============================================================================
# FIG 1B: Crash rate MVMT by zone (box)
# ==============================================================================
df_fig1b = winsorize_df(df, ["Crash_Rate_MVMT"], pct=CLIP_PCT_DEFAULT)
plt.figure(figsize=(10, 6))
sns.boxplot(x="Zone", y="Crash_Rate_MVMT", order=ZONE_ORDER, data=df_fig1b, showfliers=False)
plt.title("Crash Rate (per MVMT): Zone 1 vs Zone 2 (Clipped)")
plt.ylabel("Crashes per MVMT")
plt.xlabel("Functional Area Zone")
safe_savefig(os.path.join(figures_folder, "Fig1B_Zone_CrashRate_MVMT.png"))

# ==============================================================================
# FIG 2: Rear-End vs Sideswipe density by zone (FIXED)
# ==============================================================================
if df["RearEnd_Dens_1k"].notna().any() and df["Sideswipe_Dens_1k"].notna().any():
    df2 = df[["Zone", "RearEnd_Dens_1k", "Sideswipe_Dens_1k"]].copy()
    df2 = winsorize_df(df2, ["RearEnd_Dens_1k", "Sideswipe_Dens_1k"], pct=CLIP_PCT_DEFAULT)

    df2_melt = df2.melt(
        id_vars=["Zone"],
        value_vars=["RearEnd_Dens_1k", "Sideswipe_Dens_1k"],
        var_name="Crash_Type",
        value_name="Density"
    )
    df2_melt["Crash_Type"] = df2_melt["Crash_Type"].replace({
        "RearEnd_Dens_1k": "Rear End",
        "Sideswipe_Dens_1k": "Sideswipe"
    })

    plt.figure(figsize=(10, 6))
    try:
        sns.barplot(x="Zone", y="Density", hue="Crash_Type", order=ZONE_ORDER, data=df2_melt, errorbar=("ci", 95))
    except TypeError:
        sns.barplot(x="Zone", y="Density", hue="Crash_Type", order=ZONE_ORDER, data=df2_melt, ci=95)

    plt.title("Rear-End vs Sideswipe Density by Zone (Clipped)")
    plt.ylabel("Avg Crashes per 1,000 ft")
    plt.xlabel("Zone")
    plt.legend(title="Crash Mechanism")
    safe_savefig(os.path.join(figures_folder, "Fig2_Crash_Mechanisms.png"))
else:
    msg("NOTE: Skipping Fig2 (Rear-End vs Sideswipe) because fields could not be detected.")

# ==============================================================================
# FIG 3: Access friction regression (Zone 2 only) (FIXED)
# ==============================================================================
zone2_df = df[df["Zone"] == "Zone 2"].copy()
if len(zone2_df) > 30:
    # choose y = sideswipe if we have it; else total crash density
    y_col = "Sideswipe_Dens_1k" if zone2_df["Sideswipe_Dens_1k"].notna().any() else "Crash_Dens_1k"

    # clip outliers that flatten the line
    reg_df = zone2_df[["Access_Dens_1k", y_col]].dropna().copy()
    reg_df = winsorize_df(reg_df, ["Access_Dens_1k", y_col], pct=CLIP_PCT_REG)

    # optional log transform
    if USE_LOG1P_IN_REGRESSION:
        reg_df["X"] = np.log1p(reg_df["Access_Dens_1k"])
        reg_df["Y"] = np.log1p(reg_df[y_col])
        x_plot, y_plot = "X", "Y"
        xlab = "log(1 + Access Points per 1,000 ft)"
        ylab = f"log(1 + {y_col})"
        title = f"Access Density vs {y_col} (Zone 2 Only, log1p, clipped)"
    else:
        x_plot, y_plot = "Access_Dens_1k", y_col
        xlab = "Access Points per 1,000 ft"
        ylab = y_col
        title = f"Access Density vs {y_col} (Zone 2 Only, clipped)"

    plt.figure(figsize=(10, 6))
    try:
        sns.regplot(
            x=x_plot, y=y_plot,
            data=reg_df,
            scatter_kws={"alpha": 0.25, "s": 18},
            line_kws={"color": "red"},
            robust=ROBUST_REGRESSION
        )
    except TypeError:
        # older seaborn doesn't support robust kw in regplot
        sns.regplot(
            x=x_plot, y=y_plot,
            data=reg_df,
            scatter_kws={"alpha": 0.25, "s": 18},
            line_kws={"color": "red"}
        )

    plt.title(title)
    plt.xlabel(xlab)
    plt.ylabel(ylab)
    safe_savefig(os.path.join(figures_folder, "Fig3_Access_Friction_Regression_Zone2.png"))
else:
    msg("NOTE: Skipping Fig3 regression (not enough Zone 2 rows after filtering).")

# ==============================================================================
# FIG 4: Crash density by speed environment
# ==============================================================================
df4 = winsorize_df(df, ["Crash_Dens_1k"], pct=CLIP_PCT_DEFAULT)
sns_barplot_ci(
    x="Speed_Bin", y="Crash_Dens_1k", hue="Zone", data=df4,
    order=["Low (<=35)", "Med (40-45)", "High (>=50)"], hue_order=ZONE_ORDER,
    title="Crash Density by Speed Environment (Clipped)",
    xlabel="Posted Speed Limit", ylabel="Crashes per 1,000 ft",
    outfile=os.path.join(figures_folder, "Fig4_Speed_Tier_Analysis.png"),
    figsize=(12, 6)
)

# ==============================================================================
# FIG 4B: Crash rate MVMT by speed environment
# ==============================================================================
df4b = winsorize_df(df, ["Crash_Rate_MVMT"], pct=CLIP_PCT_DEFAULT)
sns_barplot_ci(
    x="Speed_Bin", y="Crash_Rate_MVMT", hue="Zone", data=df4b,
    order=["Low (<=35)", "Med (40-45)", "High (>=50)"], hue_order=ZONE_ORDER,
    title="Crash Rate (MVMT) by Speed Environment (Clipped)",
    xlabel="Posted Speed Limit", ylabel="Crashes per MVMT",
    outfile=os.path.join(figures_folder, "Fig4B_Speed_Tier_CrashRate_MVMT.png"),
    figsize=(12, 6)
)

# ==============================================================================
# FIG 5: Top N collision types overall by avg density
# ==============================================================================
dens_cols_all = [c for c in df.columns if c.startswith("Dens_1k_")]

# Remove helper/derived mechanism densities from ranking if you want only native types
# (Keep native densities only)
native_dens_cols = [c for c in dens_cols_all if c.replace("Dens_1k_", "Cnt_") in collision_cnt_fields]

if native_dens_cols:
    df_rank = winsorize_df(df, native_dens_cols, pct=CLIP_PCT_DEFAULT)
    avg = df_rank[native_dens_cols].mean().sort_values(ascending=False)

    avg_csv = avg.reset_index()
    avg_csv.columns = ["Density_Field", "Avg_Dens_1k"]
    avg_csv["Collision_Type"] = (
        avg_csv["Density_Field"]
        .str.replace("Dens_1k_", "", regex=False)
        .str.replace("_", " ")
    )
    avg_csv.to_csv(os.path.join(figures_folder, "CollisionType_AvgDensity_All.csv"), index=False)

    top = avg.head(TOP_N)
    plot_df = top.reset_index()
    plot_df.columns = ["Density_Field", "Avg_Dens_1k"]
    plot_df["Collision_Type"] = (
        plot_df["Density_Field"]
        .str.replace("Dens_1k_", "", regex=False)
        .str.replace("_", " ")
    )

    plt.figure(figsize=(12, 6))
    try:
        sns.barplot(x="Avg_Dens_1k", y="Collision_Type", data=plot_df, errorbar=None)
    except TypeError:
        sns.barplot(x="Avg_Dens_1k", y="Collision_Type", data=plot_df, ci=None)
    plt.title(f"Top {TOP_N} Collision Types by Avg Density (Overall, clipped)")
    plt.xlabel("Avg Crashes per 1,000 ft")
    plt.ylabel("Collision Type")
    safe_savefig(os.path.join(figures_folder, "Fig5_CollisionType_Top10_Overall.png"))

# ==============================================================================
# FIG 6: Top N collision types by zone
# ==============================================================================
if native_dens_cols:
    df_zone = winsorize_df(df, native_dens_cols, pct=CLIP_PCT_DEFAULT)
    zone_avg = df_zone.groupby("Zone")[native_dens_cols].mean()

    zone_melt = zone_avg.reset_index().melt(
        id_vars=["Zone"],
        var_name="Density_Field",
        value_name="Avg_Dens_1k"
    )
    zone_melt["Collision_Type"] = (
        zone_melt["Density_Field"]
        .str.replace("Dens_1k_", "", regex=False)
        .str.replace("_", " ")
    )

    overall_rank = df_zone[native_dens_cols].mean().sort_values(ascending=False)
    top_fields = list(overall_rank.head(TOP_N).index)

    zone_top = zone_melt[zone_melt["Density_Field"].isin(top_fields)].copy()

    plt.figure(figsize=(12, 7))
    try:
        sns.barplot(data=zone_top, x="Avg_Dens_1k", y="Collision_Type", hue="Zone", errorbar=("ci", 95))
    except TypeError:
        sns.barplot(data=zone_top, x="Avg_Dens_1k", y="Collision_Type", hue="Zone", ci=95)

    plt.title(f"Top {TOP_N} Collision Types by Avg Density (By Zone, clipped)")
    plt.xlabel("Avg Crashes per 1,000 ft")
    plt.ylabel("Collision Type")
    safe_savefig(os.path.join(figures_folder, "Fig6_CollisionType_Top10_ByZone.png"))

# ==============================================================================
# FIG 7: Heatmap - density by zone (top N)
# ==============================================================================
if native_dens_cols:
    df_zone2 = winsorize_df(df, native_dens_cols, pct=CLIP_PCT_DEFAULT)
    overall_rank = df_zone2[native_dens_cols].mean().sort_values(ascending=False)
    top_fields = list(overall_rank.head(TOP_N).index)

    zone_avg2 = df_zone2.groupby("Zone")[top_fields].mean()
    zone_avg2.columns = [c.replace("Dens_1k_", "").replace("_", " ") for c in zone_avg2.columns]

    plt.figure(figsize=(14, 4 + 0.4 * len(zone_avg2)))
    sns.heatmap(zone_avg2, annot=False)
    plt.title(f"Heatmap: Avg Density by Collision Type (Top {TOP_N}) and Zone (clipped)")
    plt.xlabel("Collision Type")
    plt.ylabel("Zone")
    safe_savefig(os.path.join(figures_folder, "Fig7_CollisionType_Heatmap_Top10.png"))

# ==============================================================================
# FIG 8: Distribution of crash density by zone (FIXED)
# ==============================================================================
df8 = df.copy()
df8["Crash_Dens_1k_Clipped"] = clip_series(df8["Crash_Dens_1k"], CLIP_PCT_HIST)

plt.figure(figsize=(12, 6))
try:
    sns.histplot(
        data=df8, x="Crash_Dens_1k_Clipped", hue="Zone",
        element="step", stat="density", common_norm=False, bins=60
    )
except Exception:
    # fallback: KDE by zone
    for z in df8["Zone"].dropna().unique():
        sns.kdeplot(df8.loc[df8["Zone"] == z, "Crash_Dens_1k_Clipped"], label=str(z))
    plt.legend()

plt.title(f"Distribution of Crash Density by Zone (Clipped at {CLIP_PCT_HIST}th pct)")
plt.xlabel("Crashes per 1,000 ft (clipped)")
plt.ylabel("Density")
safe_savefig(os.path.join(figures_folder, "Fig8_CrashDensity_Distribution_ByZone.png"))

# ==============================================================================
# FIG 9: Crash density vs assigned speed (scatter) (FIXED readability)
# ==============================================================================
df9 = df.copy()
df9["Crash_Dens_1k_Clipped"] = clip_series(df9["Crash_Dens_1k"], CLIP_PCT_SCATTER)

plt.figure(figsize=(12, 6))
sns.scatterplot(data=df9, x="Speed", y="Crash_Dens_1k_Clipped", hue="Zone", alpha=0.20, s=18)
plt.title(f"Crash Density vs Assigned Speed (Clipped at {CLIP_PCT_SCATTER}th pct)")
plt.xlabel("Assigned Speed (mph)")
plt.ylabel("Crashes per 1,000 ft (clipped)")
safe_savefig(os.path.join(figures_folder, "Fig9_CrashDensity_vs_Speed_Scatter.png"))

# ==============================================================================
# FIG 10: Crash density vs access density (scatter) (FIXED readability)
# ==============================================================================
df10 = df.copy()
df10["Crash_Dens_1k_Clipped"] = clip_series(df10["Crash_Dens_1k"], CLIP_PCT_SCATTER)
df10["Access_Dens_1k_Clipped"] = clip_series(df10["Access_Dens_1k"], CLIP_PCT_SCATTER)

plt.figure(figsize=(12, 6))
sns.scatterplot(
    data=df10,
    x="Access_Dens_1k_Clipped",
    y="Crash_Dens_1k_Clipped",
    hue="Zone",
    alpha=0.20,
    s=18
)
plt.title(f"Crash Density vs Access Density (Clipped at {CLIP_PCT_SCATTER}th pct)")
plt.xlabel("Access Points per 1,000 ft (clipped)")
plt.ylabel("Crashes per 1,000 ft (clipped)")
safe_savefig(os.path.join(figures_folder, "Fig10_CrashDensity_vs_AccessDensity_Scatter.png"))

plt.close("all")
msg(f"Done. Figures saved to: {figures_folder}")
