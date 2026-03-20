import arcpy
import pandas as pd
import os

# ==============================================================================
# CONFIGURATION
# ==============================================================================
input_bins = "Final_Intersection_Data"  # Your output from firststep.py
crash_layer = "CrashData_Basic"  # Your raw crash points
output_excel = r"C:\Users\Jameson.Clements\Documents\VDOT_Analysis_Matrix.xlsx"

# UPDATED DICTIONARY with correct Field Names
# Note: We keep quotes (e.g., '2') because your Light Condition query worked with them.
crash_metrics = {
    "Count_RearEnd": "COLLISION_TYPE = '1' OR COLLISION_TYPE = 'Rear End'",
    "Count_Angle": "COLLISION_TYPE = '2' OR COLLISION_TYPE = 'Angle'",
    "Count_Severe": "CRASH_SEVERITY IN ('K', 'A', 'B')",
    "Count_Night": "LIGHT_CONDITION IN ('2', '3', '4')",
    "Count_Wet": "ROADWAY_SURFACE_COND = '2'"  # Fixed Field Name
}

# ==============================================================================
# PART 1: ENRICHMENT (Get specific crash counts)
# ==============================================================================
print("--- STARTING DATA ENRICHMENT ---")
arcpy.env.overwriteOutput = True
temp_bins = "memory/Enriched_Bins"

# Check if input exists
if not arcpy.Exists(input_bins):
    raise ValueError(f"Input layer {input_bins} not found in workspace!")

arcpy.management.CopyFeatures(input_bins, temp_bins)

for col_name, sql_query in crash_metrics.items():
    print(f"   Counting: {col_name}...")

    # 1. Select specific crashes
    temp_crashes = "memory/temp_crash_selection"
    # Wrap in try/except to catch SQL errors gracefully
    try:
        arcpy.management.MakeFeatureLayer(crash_layer, temp_crashes, sql_query)
    except Exception as e:
        print(f"   !!! SQL ERROR on {col_name}: {e}")
        print(f"   !!! Query was: {sql_query}")
        continue

    # 2. Spatial Join
    temp_join = f"memory/join_{col_name}"
    arcpy.analysis.SpatialJoin(
        target_features=temp_bins,
        join_features=temp_crashes,
        out_feature_class=temp_join,
        join_operation="JOIN_ONE_TO_ONE",
        match_option="INTERSECT",
        search_radius="75 Feet"
    )

    # 3. Transfer Data
    arcpy.management.AddField(temp_bins, col_name, "LONG")

    join_data = {}
    with arcpy.da.SearchCursor(temp_join, ["TARGET_FID", "Join_Count"]) as cursor:
        for fid, count in cursor:
            join_data[fid] = count

    # Use generic 'OBJECTID' or finding the OID field dynamically is safer
    oid_field = [f.name for f in arcpy.ListFields(temp_bins) if f.type == 'OID'][0]

    with arcpy.da.UpdateCursor(temp_bins, [oid_field, col_name]) as cursor:
        for row in cursor:
            row[1] = join_data.get(row[0], 0)
            cursor.updateRow(row)

    arcpy.management.Delete(temp_join)
    arcpy.management.Delete(temp_crashes)

# ==============================================================================
# PART 2: AGGREGATION
# ==============================================================================
print("--- CONSOLIDATING TO EXCEL ---")

# Determine correct ID field (ORIG_FID vs TARGET_FID)
actual_fields = [f.name for f in arcpy.ListFields(temp_bins)]
id_field = "ORIG_FID" if "ORIG_FID" in actual_fields else "TARGET_FID"

# Build field list
keep_fields = [
                  id_field, "distance", "Valid_Bin",
                  "Access_Count", "Speed_Limit", "COORDINATION",
                  "Crash_Count"
              ] + list(crash_metrics.keys())

data_rows = []
with arcpy.da.SearchCursor(temp_bins, keep_fields) as cursor:
    for row in cursor:
        if row[2] == 1:  # Valid_Bin only
            record = {
                "Intersection_ID": row[0],
                "Distance_Bin": row[1],
                "Total_Access": row[3],
                "Speed_Limit": row[4],
                "Signal_Type": row[5],
                "Total_Crashes": row[6]
            }
            # Add dynamic columns
            for i, key in enumerate(crash_metrics.keys()):
                record[key] = row[7 + i]

            data_rows.append(record)

df = pd.DataFrame(data_rows)

# Aggregation Rules
agg_rules = {
    "Total_Access": "sum",
    "Total_Crashes": "sum",
    "Speed_Limit": "max",
    "Signal_Type": "first"
}
for key in crash_metrics.keys():
    agg_rules[key] = "sum"

# Perform Force-Merge Aggregation
df_clean = df.groupby(["Intersection_ID", "Distance_Bin"]).agg(agg_rules).reset_index()
df_clean = df_clean.sort_values(by=["Intersection_ID", "Distance_Bin"])

# Calculate Interval (Marginal) Counts
print("   Calculating interval counts...")
cols_to_diff = ["Total_Crashes", "Total_Access"] + list(crash_metrics.keys())

for col in cols_to_diff:
    new_col = col.replace("Count_", "Interval_")
    if "Total" in col: new_col = col.replace("Total_", "Interval_")

    df_clean[new_col] = df_clean.groupby("Intersection_ID")[col].diff().fillna(df_clean[col])
    df_clean[new_col] = df_clean[new_col].clip(lower=0)

# ==============================================================================
# PART 3: EXPORT
# ==============================================================================
print(f"--- SAVING TO {output_excel} ---")
df_clean.to_excel(output_excel, index=False)
print("Success! Analysis Matrix Created.")