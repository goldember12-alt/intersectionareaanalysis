# -*- coding: utf-8 -*-
"""
PROJECT: VDOT INTERSECTION SAFETY & ACCESS MANAGEMENT ANALYSIS
MODULE:  PHASE 2 - DYNAMIC FUNCTIONAL AREA ZONING (FAST + CLEAN SEGMENTATION)
VERSION: 2026.3

WHAT'S IMPROVED:
- Uses ERASE to make donut (Zone 2) instead of UNION (faster, cleaner).
- Uses Pairwise tools where possible.
- Removes redundant SpatialJoin for Zone_Type after segmentation.
- Deletes micro-segment slivers BEFORE crash assignment (fixes extreme density outliers).
- Keeps fast crash assignment: one SpatialJoin + Frequency tables.
"""

import arcpy
import os
import re
from collections import Counter

# ==============================================================================
# CONFIGURATION
# ==============================================================================
def msg(s: str):
    try:
        arcpy.AddMessage(s)
    except Exception:
        pass
    print(s)

# Prefer env.workspace (fast) and only fall back to ArcGISProject if needed
if not arcpy.env.workspace:
    p = arcpy.mp.ArcGISProject("CURRENT")
    default_gdb = p.defaultGeodatabase
    arcpy.env.workspace = default_gdb
else:
    default_gdb = arcpy.env.workspace

arcpy.env.overwriteOutput = True

# Scratch workspace
try:
    arcpy.env.scratchWorkspace = arcpy.env.scratchGDB
except Exception:
    pass

# Parallel processing (some tools support it)
try:
    arcpy.env.parallelProcessingFactor = "100%"
except Exception:
    pass

TARGET_SR = arcpy.SpatialReference(3968)  # NAD83 VA Lambert
OUTPUT_NAME = "Final_Functional_Zones"

INPUTS = {
    "roads": "Travelway",
    "signals": "Master_Signal_Layer",
    "crashes": "CrashData_Basic",
    "access": "layer_lrspoint",
    "speed": "SDE_VDOT_SPEED_LIMIT_MSTR_RTE",
    "aadt": "New_AADT",
}

# AASHTO / VDOT functional distances (feet)
FUNCTIONAL_DISTANCES = {
    25: (155, 355),
    30: (200, 450),
    35: (250, 550),
    40: (305, 680),
    45: (360, 810),
    50: (425, 950),
    55: (495, 1100),
}
DEFAULT_SPEED = 35

# Crash-to-segment snap radius for "closest segment" assignment
CRASH_SNAP_RADIUS = "50 Feet"

# Segment cleanup thresholds (IMPORTANT)
MIN_SEGMENT_FT = 50.0      # remove micro slivers
MIN_VALID_LEN_FT = 10.0    # safety guard when computing densities

# ==============================================================================
# HELPERS
# ==============================================================================
def safe_field_name(label: str, max_len: int = 60) -> str:
    s = (label or "").strip()
    s = re.sub(r"^\s*\d+\.\s*", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    if not s:
        s = "Unknown"
    return s[:max_len]

def make_unique_name(base: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", base)[:40] or "tmp"
    name = base
    i = 2
    while arcpy.Exists(name):
        name = f"{base}_{i}"
        i += 1
    return name

def ensure_field(fc, name, ftype, length=None):
    existing = {f.name for f in arcpy.ListFields(fc)}
    if name in existing:
        return
    if length:
        arcpy.management.AddField(fc, name, ftype, field_length=length)
    else:
        arcpy.management.AddField(fc, name, ftype)

def get_crash_sql(layer):
    """Auto-detect a Year or Date field and return a SQL filter for 2023+."""
    desc = arcpy.Describe(layer)
    fields = desc.fields

    year_field = next((f for f in fields if "YEAR" in f.name.upper()), None)
    if year_field:
        msg(f"    -> Detected Year Field: '{year_field.name}' (Type: {year_field.type})")
        if year_field.type == "String":
            return f"{year_field.name} >= '2023'"
        else:
            return f"{year_field.name} >= 2023"

    date_field = next((f for f in fields if "DATE" in f.name.upper() and f.type == "Date"), None)
    if date_field:
        msg(f"    -> Detected Date Field: '{date_field.name}' (Filtering by Date)")
        return f"{date_field.name} >= date '2023-01-01 00:00:00'"

    msg("    ! WARNING: Could not auto-detect Year or Date field. No crash filter applied.")
    return ""

def count_features(label, input_layer, target_layer, query=None, out_field=None,
                   search_radius="50 Feet", match_option="INTERSECT"):
    """
    Counts input features per target feature using ONE SpatialJoin and writes Join_Count to out_field.
    """
    msg(f"    -> Counting {label}...")

    lyr_name = make_unique_name(f"lyr_{label}")
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", label)[:30] or "X"
    temp_join = os.path.join(arcpy.env.scratchGDB, f"sj_{clean}")

    if arcpy.Exists(temp_join):
        arcpy.management.Delete(temp_join)

    if query:
        arcpy.management.MakeFeatureLayer(input_layer, lyr_name, query)
    else:
        arcpy.management.MakeFeatureLayer(input_layer, lyr_name)

    arcpy.analysis.SpatialJoin(
        target_layer, lyr_name, temp_join,
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        match_option=match_option,
        search_radius=search_radius
    )

    if out_field is None:
        out_field = f"Cnt_{safe_field_name(label)}"

    if out_field not in {f.name for f in arcpy.ListFields(target_layer)}:
        arcpy.management.AddField(target_layer, out_field, "LONG")

    count_map = {r[0]: r[1] for r in arcpy.da.SearchCursor(temp_join, ["TARGET_FID", "Join_Count"])}

    with arcpy.da.UpdateCursor(target_layer, ["OBJECTID", out_field]) as cur:
        for oid, _ in cur:
            cur.updateRow((oid, count_map.get(oid, 0)))

    for tmp in (lyr_name, temp_join):
        try:
            if tmp and arcpy.Exists(tmp):
                arcpy.management.Delete(tmp)
        except Exception:
            pass

    return out_field

def delete_short_segments(fc, min_len_ft: float):
    """Deletes features in fc with geodesic length < min_len_ft."""
    msg(f"    -> Deleting segments shorter than {min_len_ft} ft (sliver cleanup)...")

    # Ensure length field exists for selection
    tmp_len_field = "TmpLenFt"
    ensure_field(fc, tmp_len_field, "DOUBLE")
    arcpy.management.CalculateGeometryAttributes(
        fc,
        [[tmp_len_field, "LENGTH_GEODESIC"]],
        length_unit="FEET_US"
    )

    lyr = make_unique_name("seglen_lyr")
    arcpy.management.MakeFeatureLayer(fc, lyr)
    arcpy.management.SelectLayerByAttribute(lyr, "NEW_SELECTION", f"{tmp_len_field} < {min_len_ft}")
    sel_count = int(arcpy.management.GetCount(lyr)[0])
    msg(f"       Selected for deletion: {sel_count}")

    if sel_count > 0:
        arcpy.management.DeleteRows(lyr)

    # Drop temp selection layer (field can remain or be deleted; leaving it is okay but we remove it)
    try:
        arcpy.management.Delete(lyr)
    except Exception:
        pass
    try:
        arcpy.management.DeleteField(fc, tmp_len_field)
    except Exception:
        pass

# ==============================================================================
# START
# ==============================================================================
msg(f"--- INITIALIZING DYNAMIC ANALYSIS IN: {default_gdb} ---")
msg(f"Scratch GDB: {arcpy.env.scratchGDB}")
msg(f"Scratch Workspace: {arcpy.env.scratchWorkspace}")

# ==============================================================================
# 1) PREP: ROADS + SIGNALS
# ==============================================================================
msg("[1/6] PREPARING NETWORK & SIGNALS...")

if not arcpy.Exists(INPUTS["signals"]):
    raise FileNotFoundError(f"CRITICAL ERROR: '{INPUTS['signals']}' not found. Run clearinggdb.py first.")

# Filter roads to divided facilities (same logic you used)
roads_lyr = make_unique_name("lyr_roads")
arcpy.management.MakeFeatureLayer(INPUTS["roads"], roads_lyr)
sql_roads = "(RIM_FACILI LIKE '%2%' OR RIM_FACILI LIKE '%4%') AND RIM_MEDIAN NOT LIKE '1-%'"
arcpy.management.SelectLayerByAttribute(roads_lyr, "NEW_SELECTION", sql_roads)

study_roads = make_unique_name("Study_Roads_Divided")
arcpy.management.CopyFeatures(roads_lyr, study_roads)

# Project signals to target SR and filter to roads
sig_proj = make_unique_name("Study_Signals_Proj")
msg(f"    -> Projecting {INPUTS['signals']}...")
arcpy.management.Project(INPUTS["signals"], sig_proj, TARGET_SR)

msg("    -> Filtering signals to divided roadway network...")
arcpy.management.SelectLayerByLocation(sig_proj, "INTERSECT", study_roads, "20 Feet")
sig_filt = make_unique_name("Study_Signals_Filtered")
arcpy.management.CopyFeatures(sig_proj, sig_filt)

# ==============================================================================
# 2) ASSIGN SPEED & COMPUTE DISTANCES
# ==============================================================================
msg("[2/6] CALCULATING DYNAMIC ZONE DIMENSIONS...")

signals_with_speed = make_unique_name("Signals_With_Speed")

# Use CLOSEST with a reasonable radius
arcpy.analysis.SpatialJoin(
    target_features=sig_filt,
    join_features=INPUTS["speed"],
    out_feature_class=signals_with_speed,
    join_operation="JOIN_ONE_TO_ONE",
    match_option="CLOSEST",
    search_radius="150 Feet"
)

for fld, ftype in (("Dist_Lim", "LONG"), ("Dist_Des", "LONG"), ("Assigned_Speed", "SHORT")):
    ensure_field(signals_with_speed, fld, ftype)

msg("    -> Applying AASHTO functional distances...")
fields = ["CAR_SPEED_LIMIT", "Dist_Lim", "Dist_Des", "Assigned_Speed"]
with arcpy.da.UpdateCursor(signals_with_speed, fields) as cursor:
    for row in cursor:
        speed = row[0]
        if speed is None or speed < 15:
            speed = DEFAULT_SPEED
        lookup_speed = int(5 * round(float(speed) / 5))
        d_lim, d_des = FUNCTIONAL_DISTANCES.get(lookup_speed, FUNCTIONAL_DISTANCES[35])
        row[1] = d_lim
        row[2] = d_des
        row[3] = int(speed)
        cursor.updateRow(row)

# ==============================================================================
# 3) BUILD ZONES (FAST DONUT VIA ERASE)
# ==============================================================================
msg("[3/6] GENERATING SPATIAL ZONES (ERASE DONUT)...")

zone1_poly = make_unique_name("Temp_Zone1_Poly")
zone2_full = make_unique_name("Temp_Zone2_Full")
zone2_poly = make_unique_name("Temp_Zone2_Poly")

# Buffer distances are per-feature fields
arcpy.analysis.PairwiseBuffer(signals_with_speed, zone1_poly, "Dist_Lim", dissolve_option="NONE")
ensure_field(zone1_poly, "Zone_Type", "TEXT", length=40)
arcpy.management.CalculateField(zone1_poly, "Zone_Type", "'Zone 1: Critical'", "PYTHON3")

arcpy.analysis.PairwiseBuffer(signals_with_speed, zone2_full, "Dist_Des", dissolve_option="NONE")

# Donut: Zone2 = Zone2Full - Zone1
# NOTE: PairwiseErase exists in newer ArcGIS Pro; if not available, fall back to Erase.
msg("    -> Creating donut zones using Erase...")
try:
    arcpy.analysis.PairwiseErase(zone2_full, zone1_poly, zone2_poly)
except Exception:
    arcpy.analysis.Erase(zone2_full, zone1_poly, zone2_poly)

ensure_field(zone2_poly, "Zone_Type", "TEXT", length=40)
arcpy.management.CalculateField(zone2_poly, "Zone_Type", "'Zone 2: Functional'", "PYTHON3")

all_zones = make_unique_name("Temp_All_Zones")
arcpy.management.Merge([zone1_poly, zone2_poly], all_zones)

# Debug: zone counts
vals = Counter()
with arcpy.da.SearchCursor(all_zones, ["Zone_Type"]) as cur:
    for (z,) in cur:
        vals[z] += 1
msg("    -> DEBUG zones created: " + str(dict(vals)))

# ==============================================================================
# 4) SEGMENTATION (CLEAN + NO REDUNDANT ZONE JOIN)
# ==============================================================================
msg("[4/6] SEGMENTING ROAD NETWORK (CLEAN)...")

# Intersect zones with roads -> road segments inherit Zone_Type directly
seg_raw = make_unique_name("Functional_Road_Segments_Raw")
arcpy.analysis.PairwiseIntersect(
    in_features=[all_zones, study_roads],
    out_feature_class=seg_raw,
    join_attributes="ALL"
)

# Remove segments that didn't inherit a zone (rare edge case)
seg_lyr = make_unique_name("seg_raw_lyr")
arcpy.management.MakeFeatureLayer(seg_raw, seg_lyr)
if "Zone_Type" in [f.name for f in arcpy.ListFields(seg_raw)]:
    arcpy.management.SelectLayerByAttribute(seg_lyr, "NEW_SELECTION", "Zone_Type IS NULL")
    null_ct = int(arcpy.management.GetCount(seg_lyr)[0])
    if null_ct > 0:
        msg(f"    -> Deleting {null_ct} segments with NULL Zone_Type...")
        arcpy.management.DeleteRows(seg_lyr)
arcpy.management.Delete(seg_lyr)

# Sliver cleanup BEFORE joins/counts
delete_short_segments(seg_raw, MIN_SEGMENT_FT)

# Add stable segment id
ensure_field(seg_raw, "SegOID", "LONG")
arcpy.management.CalculateField(seg_raw, "SegOID", "!OBJECTID!", "PYTHON3")

# Debug checkpoint
vals = Counter()
with arcpy.da.SearchCursor(seg_raw, ["Zone_Type"]) as cur:
    for (z,) in cur:
        vals[z] += 1
msg("    -> DEBUG segments by zone: " + str(dict(vals)))

target_layer = seg_raw

# ==============================================================================
# 5) VARIABLE ENRICHMENT (ACCESS + CRASHES FAST PATH)
# ==============================================================================
msg("[5/6] EXTRACTING SAFETY & ACCESS VARIABLES (FAST)...")

# A) Access count per segment (one SpatialJoin)
count_features("Access", INPUTS["access"], target_layer, out_field="Cnt_Access",
               search_radius="30 Feet", match_option="INTERSECT")

# B) Build crash layer with filter (no copying)
dynamic_sql = get_crash_sql(INPUTS["crashes"])
msg(f"    -> Applying Crash Filter: {dynamic_sql if dynamic_sql else '(none)'}")

crash_lyr = make_unique_name("lyr_crash_filtered")
if dynamic_sql:
    arcpy.management.MakeFeatureLayer(INPUTS["crashes"], crash_lyr, dynamic_sql)
else:
    arcpy.management.MakeFeatureLayer(INPUTS["crashes"], crash_lyr)

# C) Assign each crash to nearest segment (single SpatialJoin)
msg("    -> Assigning crashes to nearest segment (single SpatialJoin)...")
crash_assigned = os.path.join(arcpy.env.scratchGDB, make_unique_name("Crash_AssignedSeg"))
if arcpy.Exists(crash_assigned):
    arcpy.management.Delete(crash_assigned)

arcpy.analysis.SpatialJoin(
    target_features=crash_lyr,
    join_features=target_layer,
    out_feature_class=crash_assigned,
    join_operation="JOIN_ONE_TO_ONE",
    join_type="KEEP_COMMON",
    match_option="CLOSEST",
    search_radius=CRASH_SNAP_RADIUS
)

collision_field = "COLLISION_TYPE"
crash_fields = {f.name for f in arcpy.ListFields(crash_assigned)}
if collision_field not in crash_fields:
    raise RuntimeError(f"Expected field '{collision_field}' not found in crash_assigned output.")
if "SegOID" not in crash_fields:
    raise RuntimeError("SegOID not found in crash_assigned output. Check SpatialJoin field mapping.")

# D) Frequency tables
msg("    -> Computing crash counts (Frequency)...")
freq_total = os.path.join(arcpy.env.scratchGDB, make_unique_name("Freq_Crash_Total"))
freq_type = os.path.join(arcpy.env.scratchGDB, make_unique_name("Freq_Crash_ByType"))

for t in (freq_total, freq_type):
    if arcpy.Exists(t):
        arcpy.management.Delete(t)

arcpy.Frequency_analysis(crash_assigned, freq_total, ["SegOID"])
arcpy.Frequency_analysis(crash_assigned, freq_type, ["SegOID", collision_field])

# E) Write crash totals + per-type counts back to segments
msg("    -> Writing crash counts back to segments...")
ensure_field(target_layer, "Cnt_TotalCrash", "LONG")

total_map = {}
with arcpy.da.SearchCursor(freq_total, ["SegOID", "FREQUENCY"]) as cur:
    for seg, n in cur:
        total_map[int(seg)] = int(n)

# Determine collision types from freq table
types = set()
with arcpy.da.SearchCursor(freq_type, [collision_field]) as cur:
    for (typ,) in cur:
        types.add(str(typ) if typ is not None else "Unknown")

# Map types -> output field names
field_map = {}
used = set()
for typ in sorted(types):
    base = safe_field_name(typ)
    out = f"Cnt_{base}"
    i = 2
    while out in used or out in {"Cnt_TotalCrash", "Cnt_Access"}:
        out = f"Cnt_{base}_{i}"
        i += 1
    used.add(out)
    field_map[typ] = out

existing = {f.name for f in arcpy.ListFields(target_layer)}
for out_field in field_map.values():
    if out_field not in existing:
        arcpy.management.AddField(target_layer, out_field, "LONG")

# seg -> {out_field: count}
seg_counts = {}
with arcpy.da.SearchCursor(freq_type, ["SegOID", collision_field, "FREQUENCY"]) as cur:
    for seg, typ, n in cur:
        seg = int(seg)
        typ = str(typ) if typ is not None else "Unknown"
        out_field = field_map.get(typ)
        if out_field:
            seg_counts.setdefault(seg, {})[out_field] = int(n)

collision_fields_out = list(field_map.values())
update_fields = ["SegOID", "Cnt_TotalCrash"] + collision_fields_out

with arcpy.da.UpdateCursor(target_layer, update_fields) as cur:
    for row in cur:
        seg = int(row[0])
        row[1] = total_map.get(seg, 0)
        m = seg_counts.get(seg)
        if m:
            for i, f in enumerate(collision_fields_out, start=2):
                row[i] = m.get(f, 0)
        else:
            for i in range(2, 2 + len(collision_fields_out)):
                row[i] = 0
        cur.updateRow(row)

# F) Transfer AADT (one SpatialJoin + JoinField)
msg("    -> Transferring AADT...")
join_aadt = os.path.join(arcpy.env.scratchGDB, make_unique_name("join_aadt_tmp"))
if arcpy.Exists(join_aadt):
    arcpy.management.Delete(join_aadt)

arcpy.analysis.SpatialJoin(
    target_layer, INPUTS["aadt"], join_aadt,
    join_operation="JOIN_ONE_TO_ONE",
    join_type="KEEP_ALL",
    match_option="INTERSECT",
    search_radius="20 Feet"
)
# Bring AADT back
try:
    arcpy.management.JoinField(target_layer, "OBJECTID", join_aadt, "TARGET_FID", ["AADT"])
except Exception:
    # If AADT field name differs, fail loud with helpful message
    aadt_fields = [f.name for f in arcpy.ListFields(join_aadt)]
    raise RuntimeError(f"Could not JoinField AADT. Available fields in join_aadt: {aadt_fields}")

# ==============================================================================
# 6) FINAL METRICS (LENGTH + ACCESS DENSITY)
# ==============================================================================
msg("[6/6] CALCULATING FINAL METRICS...")

# Save final output
if arcpy.Exists(OUTPUT_NAME):
    arcpy.management.Delete(OUTPUT_NAME)
arcpy.management.CopyFeatures(target_layer, OUTPUT_NAME)

# Segment length
ensure_field(OUTPUT_NAME, "Seg_Len_Ft", "DOUBLE")
arcpy.management.CalculateGeometryAttributes(
    OUTPUT_NAME,
    [["Seg_Len_Ft", "LENGTH_GEODESIC"]],
    length_unit="FEET_US"
)

# Access density per 1k ft
ensure_field(OUTPUT_NAME, "Access_Density_1k", "DOUBLE")
code_block = f"""
def calc_density(count, length):
    try:
        if length is None or length < {MIN_VALID_LEN_FT}:
            return 0
        if count is None:
            count = 0
        return (count / length) * 1000.0
    except:
        return 0
"""
arcpy.management.CalculateField(
    OUTPUT_NAME, "Access_Density_1k",
    "calc_density(!Cnt_Access!, !Seg_Len_Ft!)",
    "PYTHON3", code_block
)

# ==============================================================================
# CLEANUP (optional but recommended for speed/space)
# ==============================================================================
msg("CLEANUP: Removing intermediates...")

temp_items = [
    roads_lyr,
    study_roads,
    sig_proj,
    sig_filt,
    signals_with_speed,
    zone1_poly,
    zone2_full,
    zone2_poly,
    all_zones,
    crash_lyr,
    crash_assigned,
    freq_total,
    freq_type,
    join_aadt,
]

for t in temp_items:
    try:
        if t and arcpy.Exists(t):
            arcpy.management.Delete(t)
    except Exception:
        pass

msg("-" * 60)
msg(f"SUCCESS. OUTPUT SAVED TO: {OUTPUT_NAME}")
msg(f"CRASH FILTER APPLIED: {dynamic_sql if dynamic_sql else '(none)'}")
msg(f"SLIVER CLEANUP: Deleted segments < {MIN_SEGMENT_FT} ft")
msg("-" * 60)