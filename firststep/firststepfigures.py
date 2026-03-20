import arcpy
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import os
import numpy as np

# ==============================================================================
# CONFIGURATION
# ==============================================================================
try:
    project_gdb = arcpy.env.workspace or arcpy.mp.ArcGISProject("CURRENT").defaultGeodatabase
    project_folder = os.path.dirname(project_gdb)
except:
    project_folder = r"C:\Temp"

print(f"--- GENERATING FINAL VDOT SAFETY FIGURES ---")

# ==============================================================================
# 1. DATA EXTRACTION
# ==============================================================================
print("[1/3] Extracting data...")
target_layer = "Final_Intersection_Data"
fields = ["ORIG_FID" if "ORIG_FID" in [f.name for f in arcpy.ListFields(target_layer)] else "TARGET_FID",
          "distance", "Crash_Count", "Access_Count", "Speed_Limit", "COORDINATION", "Valid_Bin"]

data_rows = []
with arcpy.da.SearchCursor(target_layer, fields) as cursor:
    for row in cursor:
        if row[6] == 1: # Valid Bin Only
            data_rows.append({
                "ID": row[0],
                "Distance": row[1],
                "Cum_Crash": row[2],
                "Cum_Access": row[3],
                "Speed": row[4] if row[4] else 0,
                "Coordination": row[5] if row[5] else "Isolated"
            })

df = pd.DataFrame(data_rows)

# ==============================================================================
# 2. DATA PROCESSING (FORCE-MERGE FIX)
# ==============================================================================
print("[2/3] Processing with Force-Merge Logic...")

# STEP A: Calculate TOTALS per ID/Distance (Ignores Speed/Coord splits)
df_totals = df.groupby(['ID', 'Distance'])[['Cum_Crash', 'Cum_Access']].sum().reset_index()

# STEP B: Determine DOMINANT Attributes per ID
# We take the MAX speed and the FIRST non-null Coordination for the whole intersection
df_attrs = df.groupby('ID').agg({
    'Speed': 'max',
    'Coordination': lambda x: x.mode()[0] if not x.mode().empty else "Isolated"
}).reset_index()

# STEP C: MERGE Totals with Attributes
df_final = pd.merge(df_totals, df_attrs, on='ID')

# STEP D: Sort & Diff (Now strictly safe)
df_final = df_final.sort_values(by=["ID", "Distance"])
df_final['Crash_Interval'] = df_final.groupby('ID')['Cum_Crash'].diff().fillna(df_final['Cum_Crash'])
df_final['Access_Interval'] = df_final.groupby('ID')['Cum_Access'].diff().fillna(df_final['Cum_Access'])

# STEP E: Calculated Metrics
def bin_speed(s):
    if s < 35: return "Low (<35)" # Adjusted to catch 25/30
    elif s <= 45: return "Med (35-45)"
    else: return "High (>45)"
df_final['Speed_Bin'] = df_final['Speed'].apply(bin_speed)
df_final['Access_Density_1k'] = (df_final['Access_Interval'] / 50) * 1000

# ==============================================================================
# 3. GENERATE FIGURES
# ==============================================================================
print("[3/3] Generating Figures...")
sns.set_theme(style="whitegrid")

# FIG 1: SPEED
plt.figure(figsize=(10, 6))
sns.lineplot(data=df_final, x="Distance", y="Crash_Interval", hue="Speed_Bin", marker="o", errorbar=('ci', 95))
plt.title("Downstream Crash Fade by Speed Limit (Corrected)")
plt.ylabel("Avg Crashes per 50ft Segment")
plt.axhline(0, color='black', linewidth=0.5)
plt.savefig(os.path.join(project_folder, "Fig1_Speed_Fade_Fixed.png"))
plt.close()

# FIG 2: COORDINATION
plt.figure(figsize=(10, 6))
coord_df = df_final[df_final['Coordination'].isin(['Coordinated', 'Isolated'])]
sns.lineplot(data=coord_df, x="Distance", y="Crash_Interval", hue="Coordination", palette="Set2")
plt.title("Safety Impact of Signal Coordination (Corrected)")
plt.ylabel("Avg Crashes per 50ft Segment")
plt.savefig(os.path.join(project_folder, "Fig2_Coordination_Fixed.png"))
plt.close()

# FIG 3: FRICTION (BOX PLOT)
plt.figure(figsize=(10, 6))
box_data = df_final[(df_final['Access_Density_1k'] <= 60) & (df_final['Crash_Interval'] < 15)].copy()
def get_label(d):
    if d == 0: return "0 Driveways"
    elif d == 20: return "1 Driveway"
    elif d == 40: return "2 Driveways"
    elif d == 60: return "3 Driveways"
    else: return "4+ Driveways"
box_data['Driveway_Count'] = box_data['Access_Density_1k'].apply(get_label)
order = ["0 Driveways", "1 Driveway", "2 Driveways", "3 Driveways"]
sns.boxplot(x="Driveway_Count", y="Crash_Interval", data=box_data, order=order, palette="Reds")
plt.title("Impact of Driveway Density on Local Crash Risk")
plt.xlabel("Access Points per 50ft Segment")
plt.ylabel("Crash Frequency")
plt.savefig(os.path.join(project_folder, "Fig3_Friction_Boxplot.png"))
plt.close()

# FIG 4: GLOBAL FADE
plt.figure(figsize=(12, 6))
global_avg = df_final.groupby("Distance")["Crash_Interval"].mean().reset_index()
sns.lineplot(data=global_avg, x="Distance", y="Crash_Interval", color="#2ca02c", linewidth=2.5, marker="o")
plt.title("Total Downstream Fade (Global Average)")
plt.axhline(0, color='black', linewidth=0.8)
plt.savefig(os.path.join(project_folder, "Fig4_Global_Fade_Fixed.png"))
plt.close()

print("Done. Check output folder.")