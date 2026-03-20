"""
PROJECT: VDOT INTERSECTION SAFETY & ACCESS MANAGEMENT ANALYSIS
MODULE:  PHASE 1 - SPATIAL VARIABLE EXTRACTION
VERSION: 2026.3 (FINAL PRODUCTION)
DESCRIPTION:
    Automated workflow to extract safety and operational variables (Crashes,
    Access Points, AADT, Speed) across segmented distance bins (0-2000ft).

    INCLUDES:
    - "Stop at Next Signal": Flags bins that overlap downstream intersections.
    - "Internal Signal Timing": Uses embedded COORDINATION/PREEMPTION fields.
"""

import arcpy
import os

# ==============================================================================
# 0. GLOBAL CONFIGURATION & ENVIRONMENT
# ==============================================================================
p = arcpy.mp.ArcGISProject("CURRENT")
default_gdb = p.defaultGeodatabase
arcpy.env.workspace = default_gdb
arcpy.env.overwriteOutput = True

# Target Spatial Reference: NAD 1983 Virginia Lambert (EPSG: 3968)
TARGET_SR = arcpy.SpatialReference(3968)

# Input Mapping (Expected Schema in Default GDB)
RAW_INPUTS = {
    "roads": "Travelway",
    "signals": "HMMS_TrafficSignals_Flat",
    "crashes": "CrashData_Basic",
    "access": "layer_lrspoint",
    "aadt": "New_AADT",
    "speed": "SDE_VDOT_SPEED_LIMIT_MSTR_RTE"
}

# Output Catalog
LAYER_DIVIDED_ROADS = "Divided_Roads"
LAYER_STUDY_SIGNALS = "Study_Intersections"
FINAL_OUTPUT = "Final_Intersection_Data"

# Analysis Parameters
CRASH_SEARCH_RADIUS = "75 Feet"
BIN_INTERVAL = 50  # Distance in feet per ring segment
MAX_DISTANCE = 2000  # Total study radius

print(f"--- INITIALIZING ANALYSIS ENVIRONMENT: {default_gdb} ---")

# ==============================================================================
# 1. SPATIAL STANDARDIZATION
# ==============================================================================
print("[1/7] PROJECTING INPUTS TO NAD83 VA LAMBERT...")
work_layers = {}

for key, raw_name in RAW_INPUTS.items():
    if not arcpy.Exists(raw_name):
        raise FileNotFoundError(f"Missing Required Input: {raw_name}")

    out_name = f"{raw_name}_Proj"
    arcpy.management.Project(raw_name, out_name, TARGET_SR)
    work_layers[key] = out_name

# ==============================================================================
# 2. NETWORK & STUDY SITE FILTRATION
# ==============================================================================
print("[2/7] DEFINING DIVIDED ROAD NETWORK & STUDY SITES...")

# Isolate Divided Roadways (RIM_FACILI: 2=One-Way, 4=Two-Way Divided)
sql_divided = "RIM_FACILI LIKE '%2%' OR RIM_FACILI LIKE '%4%'"
arcpy.analysis.Select(work_layers["roads"], LAYER_DIVIDED_ROADS, sql_divided)

# Select signals associated with the Divided Road network
temp_signals = "memory/temp_signals"
arcpy.management.MakeFeatureLayer(work_layers["signals"], temp_signals)
arcpy.management.SelectLayerByLocation(
    temp_signals, "INTERSECT", LAYER_DIVIDED_ROADS, "10 Meters"
)
arcpy.management.CopyFeatures(temp_signals, LAYER_STUDY_SIGNALS)

# ==============================================================================
# 3. SPATIAL BINNING
# ==============================================================================
print(f"[3/7] GENERATING {BIN_INTERVAL}FT DISTANCE BINS...")

# A. Generate Rings (Dissolve=NONE ensures 1 ring per signal per interval)
arcpy.analysis.MultipleRingBuffer(
    Input_Features=LAYER_STUDY_SIGNALS,
    Output_Feature_class="Intermediate_Rings",
    Distances=list(range(BIN_INTERVAL, MAX_DISTANCE + BIN_INTERVAL, BIN_INTERVAL)),
    Buffer_Unit="Feet",
    Field_Name="distance",
    Dissolve_Option="NONE",
    Outside_Polygons_Only="FULL"
)

print("   -> Restoring attributes via ID Link...")
# B. Restore Attributes (Including COORDINATION, PREEMPTION, etc.)
try:
    arcpy.management.JoinField(
        in_data="Intermediate_Rings",
        in_field="ORIG_FID",
        join_table=LAYER_STUDY_SIGNALS,
        join_field="OBJECTID"
    )
    arcpy.management.CopyFeatures("Intermediate_Rings", "Intermediate_Rings_Ready")
except:
    print("   -> ORIG_FID missing, falling back to Spatial Join...")
    arcpy.analysis.SpatialJoin(
        target_features="Intermediate_Rings",
        join_features=LAYER_STUDY_SIGNALS,
        out_feature_class="Intermediate_Rings_Ready",
        join_operation="JOIN_ONE_TO_ONE",
        match_option="HAVE_THEIR_CENTER_IN"
    )

# C. Segmentation
print("   -> Segmentation (Cutting roads by rings)...")
arcpy.analysis.PairwiseIntersect(
    in_features=[LAYER_DIVIDED_ROADS, "Intermediate_Rings_Ready"],
    out_feature_class="Intermediate_Road_Bins",
    join_attributes="ALL",
    output_type="INPUT"
)

if arcpy.ListFields("Intermediate_Road_Bins", "Join_Count"):
    arcpy.management.DeleteField("Intermediate_Road_Bins", "Join_Count")


# ==============================================================================
# 4. VARIABLE CALCULATION LOGIC
# ==============================================================================
def add_variable(target_layer, source_layer, field_name, rule="COUNT", radius="5 Feet"):
    """
    Standardized Spatial Join to transfer counts or attributes to road bins.
    """
    print(f"    - Processing Variable: {field_name}")

    if arcpy.ListFields(target_layer, "Join_Count"):
        arcpy.management.DeleteField(target_layer, "Join_Count")

    temp_join = f"memory/temp_join_{field_name}"
    arcpy.analysis.SpatialJoin(
        target_layer, source_layer, temp_join,
        "JOIN_ONE_TO_ONE", "KEEP_ALL", match_option="INTERSECT", search_radius=radius
    )

    field_type = "LONG" if rule == "COUNT" else "DOUBLE"
    arcpy.management.AddField(target_layer, field_name, field_type)

    # Resolve source field name for Attribute Transfers (AADT/Speed)
    val_field = "Join_Count"
    if rule == "TRANSFER":
        candidates = [f.name for f in arcpy.ListFields(temp_join)]
        priorities = ["AADT", "SPEED", "SPEED_LIMIT", "RN_SPEED_LIMIT"]
        for p_field in priorities:
            for c in candidates:
                if p_field in c.upper():
                    val_field = c
                    break

    # Cursor-based data transfer for performance
    data_map = {row[0]: row[1] for row in arcpy.da.SearchCursor(temp_join, ["TARGET_FID", val_field])}
    with arcpy.da.UpdateCursor(target_layer, ["OBJECTID", field_name]) as cursor:
        for row in cursor:
            row[1] = data_map.get(row[0], 0) if data_map.get(row[0]) is not None else 0
            cursor.updateRow(row)


# ==============================================================================
# 5. EXECUTION OF SEQUENTIAL SPATIAL JOINS
# ==============================================================================
print("[5/7] CALCULATING OPERATIONAL AND SAFETY METRICS...")
arcpy.management.CopyFeatures("Intermediate_Road_Bins", FINAL_OUTPUT)

# Variable Suite
add_variable(FINAL_OUTPUT, work_layers["access"], "Access_Count", rule="COUNT", radius="5 Feet")
add_variable(FINAL_OUTPUT, work_layers["crashes"], "Crash_Count", rule="COUNT", radius=CRASH_SEARCH_RADIUS)
add_variable(FINAL_OUTPUT, work_layers["aadt"], "AADT", rule="TRANSFER", radius="20 Feet")
add_variable(FINAL_OUTPUT, work_layers["speed"], "Speed_Limit", rule="TRANSFER", radius="20 Feet")

# ==============================================================================
# 6. SIGNAL TIMING & NEIGHBOR CUTOFF (REFINED)
# ==============================================================================
print("[6/7] APPLYING SIGNAL LOGIC (TIMING & NEIGHBORS)...")

# --- A. Signal Timing Cleanup ---
# We rely on the internal attributes 'COORDINATION' and 'PREEMPTION'
# which were already carried over in Step 3. We just clean them here.
print("   -> Cleaning internal Signal Timing attributes...")

fields_to_check = ["COORDINATION", "PREEMPTION"]
# Ensure fields exist before trying to update
existing_fields = [f.name for f in arcpy.ListFields(FINAL_OUTPUT)]
fields_to_update = [f for f in fields_to_check if f in existing_fields]

if fields_to_update:
    with arcpy.da.UpdateCursor(FINAL_OUTPUT, fields_to_update) as cursor:
        for row in cursor:
            # Logic: If COORDINATION is NULL, assume 'Isolated'
            # Logic: If PREEMPTION is NULL, assume 'No'
            updated = False

            # Check COORDINATION (Index 0 if present)
            if "COORDINATION" in fields_to_update:
                idx = fields_to_update.index("COORDINATION")
                if row[idx] is None:
                    row[idx] = "Isolated"
                    updated = True

            # Check PREEMPTION (Index 1 or 0 depending on presence)
            if "PREEMPTION" in fields_to_update:
                idx = fields_to_update.index("PREEMPTION")
                if row[idx] is None:
                    row[idx] = "No"
                    updated = True

            if updated:
                cursor.updateRow(row)

# --- B. Stop at Next Signal (Neighbor Analysis) ---
print("   -> Calculating distance to nearest downstream signal...")

# 1. Generate Near Table (Signal to Signal)
nearby_table = "memory/Nearest_Signal_Analysis"
arcpy.analysis.GenerateNearTable(
    in_features=LAYER_STUDY_SIGNALS,
    near_features=LAYER_STUDY_SIGNALS,
    out_table=nearby_table,
    search_radius="2500 Feet",  # Look slightly past max study range
    closest="ALL",
    method="GEODESIC"
)

# 2. Build Dictionary {Signal_OID: Nearest_Distance}
neighbor_limit = {}
with arcpy.da.SearchCursor(nearby_table, ["IN_FID", "NEAR_DIST"]) as cursor:
    for fid, dist in cursor:
        if dist > 0:  # Ignore distance to self (0)
            if fid not in neighbor_limit or dist < neighbor_limit[fid]:
                neighbor_limit[fid] = dist

# 3. Flag "Polluted" Bins
print("   -> Flagging bins that overlap the next intersection...")
arcpy.management.AddField(FINAL_OUTPUT, "Valid_Bin", "SHORT")  # 1=Valid, 0=Invalid

# Identify the correct ID field that links back to the original Signal OID
# 'ORIG_FID' is standard from JoinField; 'TARGET_FID' from SpatialJoin
id_field = "ORIG_FID" if "ORIG_FID" in existing_fields else "TARGET_FID"

with arcpy.da.UpdateCursor(FINAL_OUTPUT, [id_field, "distance", "Valid_Bin"]) as cursor:
    for row in cursor:
        sig_oid = row[0]
        bin_dist = row[1]

        # Get limit (default to 9999 if no neighbor found)
        limit = neighbor_limit.get(sig_oid, 9999)

        # If the bin starts at or after the next signal, it's invalid
        if bin_dist >= limit:
            row[2] = 0  # INVALID: This segment belongs to the next signal
        else:
            row[2] = 1  # VALID: Clear downstream flow
        cursor.updateRow(row)

# ==============================================================================
# 7. CALCULATED FIELDS & CLEANUP
# ==============================================================================
print("[7/7] FINALIZING DATASET...")

# Access Density (Points per 50ft bin)
arcpy.management.AddField(FINAL_OUTPUT, "Access_Density", "DOUBLE")
arcpy.management.CalculateField(FINAL_OUTPUT, "Access_Density", f"!Access_Count! / {BIN_INTERVAL}", "PYTHON3")

# Workspace Cleanup
for temp_file in ["Intermediate_Rings", "Intermediate_Rings_IDs", "Intermediate_Rings_Ready", "Intermediate_Road_Bins"]:
    if arcpy.Exists(temp_file):
        arcpy.management.Delete(temp_file)

print("-" * 67)
print(f"ANALYSIS COMPLETE: {FINAL_OUTPUT}")
print(f"METRIC: Crash Analysis Radius @ {CRASH_SEARCH_RADIUS}")
print(f"NOTE: Filter 'Valid_Bin = 1' to exclude overlapping segments.")
print("-" * 67)