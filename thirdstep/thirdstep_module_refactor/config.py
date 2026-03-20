# -*- coding: utf-8 -*-
"""
Configuration and environment bootstrap for thirdstep.
"""

import os
import sys
from pathlib import Path

import arcpy

# Harden GeoPandas/PyProj startup inside ArcGIS Pro clone environments.
try:
    _proj_dir = Path(sys.prefix) / "Library" / "share" / "proj"
    if _proj_dir.exists() and not os.environ.get("PROJ_LIB"):
        os.environ["PROJ_LIB"] = str(_proj_dir)
except Exception:
    pass

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import geopandas as gpd
except Exception:
    gpd = None

# Workspace bootstrapping
if not arcpy.env.workspace:
    p = arcpy.mp.ArcGISProject("CURRENT")
    default_gdb = p.defaultGeodatabase
    arcpy.env.workspace = default_gdb
else:
    default_gdb = arcpy.env.workspace

arcpy.env.overwriteOutput = True

try:
    arcpy.env.scratchWorkspace = arcpy.env.scratchGDB
except Exception:
    pass

try:
    arcpy.env.parallelProcessingFactor = "100%"
except Exception:
    pass

# Spatial reference
TARGET_SR = arcpy.SpatialReference(3968)  # NAD83 Virginia Lambert

# Input mapping
INPUTS = {
    "roads":   "Travelway",
    "signals": "Master_Signal_Layer",
    "crashes": "CrashData_Basic",
    "access":  "layer_lrspoint",
    "aadt":    "New_AADT",
    "speed":   "SDE_VDOT_SPEED_LIMIT_MSTR_RTE",
}

# Output naming
OUTPUT_SEGMENTS_FINAL = "Final_Functional_Segments"
OUTPUT_SIGNALS_FINAL = "Final_Study_Signals"
OUTPUT_ZONES_FINAL = "Final_Functional_Zones_Stage3"
OUTPUT_QC_TABLE = "QC_ThirdStep"
OUTPUT_QC_UNKNOWN_DIR = "QC_UnknownDirection"
OUTPUT_QC_OVERLAP = "QC_OverlapClaims"
OUTPUT_QC_CRASH_FAR = "QC_CrashesFarSnap"

# ArcPy staging names
STAGED = {
    "roads_proj": "TW_Roads_Proj",
    "signals_proj": "TW_Signals_Proj",
    "crashes_proj": "TW_Crashes_Proj",
    "access_proj": "TW_Access_Proj",
    "aadt_proj": "TW_AADT_Proj",
    "speed_proj": "TW_Speed_Proj",
    "roads_study": "Study_Roads_Divided",
    "roads_study_aadt_cache": "Study_Roads_Divided_AADTCache",
    "signals_study": "Study_Signals",
    "signals_speed": "Study_Signals_Speed",
    "zones_zone1": "Zone1_Critical",
    "zones_zone2full": "Zone2_Full",
    "zones_zone2": "Zone2_Functional",
    "zones_all": "All_Functional_Zones",
    "zones_claims": "Zone_Road_Claims",
    "zones_claims_clean": "Zone_Road_Claims_Clean",
    "seg_raw": "Functional_Segments_Raw",
    "seg_clean": "Functional_Segments_Clean",
    "parent_roads": "Parent_Roads_ForLinearRef",
    "crash_assigned": "Crash_Assigned_Initial",
    "access_assigned": "Access_Assigned_Initial",
}

# Working export folder
EXPORT_DIR = os.path.join(os.path.dirname(default_gdb), "thirdstep_work")
EXPORT_GDB = os.path.join(EXPORT_DIR, "thirdstep_work.gdb")
EXPORT_SUMMARY_SEG = os.path.join(EXPORT_DIR, "segment_direction_summary.csv")
EXPORT_SUMMARY_CRASH = os.path.join(EXPORT_DIR, "crash_direction_summary.csv")
EXPORT_SUMMARY_QC = os.path.join(EXPORT_DIR, "qc_summary.csv")
EXPORT_ACCESS_SUMMARY = os.path.join(EXPORT_DIR, "access_summary.csv")

# Tolerances / analysis params
SIGNAL_TO_ROAD_FILTER = "20 Feet"
SIGNAL_SPEED_SEARCH = "150 Feet"
CRASH_SNAP_RADIUS = "50 Feet"
ACCESS_SNAP_RADIUS = "30 Feet"
ZONE_CLAIM_SEARCH_RADIUS = "10 Feet"
NEIGHBOR_SIGNAL_RADIUS = "2500 Feet"
MIN_SEGMENT_FT = 50.0
MIN_VALID_LEN_FT = 10.0
MIDPOINT_AT_SIGNAL_TOL_FT = 15.0
CRASH_AT_SIGNAL_TOL_FT = 15.0
FAR_SNAP_FT = 75.0
CLAIM_GEOM_KEY_DECIMALS = 3
AADT_TRANSFER_SEARCH_RADIUS = "20 Feet"
ACCESS_ASSIGN_MATCH_OPTION = "CLOSEST"
CRASH_ASSIGN_MATCH_OPTION = "CLOSEST"

# Optional flags
USE_ORACLE_MATCH_RESOLUTION = True
USE_ORACLE_AADT = True
USE_GEOPANDAS = True
CACHE_PROJECTED_INPUTS = True
ROAD_METADATA_BACKFILL_REQUIRES_DIRECTIONAL_PIPELINE = False
WRITE_QC_LAYERS = True
WRITE_GPKG_EXPORT = True
KEEP_INTERMEDIATES = False
WRITE_DIAGNOSTIC_CSVS = False
WRITE_OPTIONAL_OUTPUT_COPIES = False
DIRECT_GDB_TO_GEOPANDAS = True
SEGMENT_AADT_FALLBACK_ONLY = True
ORACLE_ROUTE_MATCH_REQUIRED = True
ORACLE_NODE_MATCH_PRIORITY = True
ORACLE_MEASURE_MATCH_TOL = 75.0
ORACLE_SEQUENCE_FALLBACK_ENABLED = True


# Runtime/debug controls (may be overridden by toolbox-set environment variables)
def _env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "t", "yes", "y", "on")

def _env_int(name, default):
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default

def _env_float(name, default):
    raw = os.environ.get(name, "")
    if raw is None:
        return default
    raw = str(raw).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default

def _env_flag(name, default=False):
    raw = os.environ.get(name, "")
    if raw is None:
        return default
    raw = str(raw).strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "y", "on")

PHASE_START = _env_int("THIRDSTEP_PHASE_START", 1)
PHASE_STOP = _env_int("THIRDSTEP_PHASE_STOP", 10)
REUSE_STAGED_OUTPUTS = _env_bool("THIRDSTEP_REUSE_STAGED_OUTPUTS", False)
CACHE_ROADS_STUDY_AFTER_AADT = _env_bool("THIRDSTEP_CACHE_ROADS_STUDY_AFTER_AADT", True)
FORCE_ROADS_AADT_SPATIAL_ONLY = _env_bool("THIRDSTEP_FORCE_ROADS_AADT_SPATIAL_ONLY", False)
ROAD_AADT_ATTRIBUTE_USE_ROUTE_MEASURES = _env_bool("THIRDSTEP_ROAD_AADT_ATTRIBUTE_USE_ROUTE_MEASURES", False)
ROAD_AADT_ATTRIBUTE_MIN_OVERLAP_RATIO = _env_float("THIRDSTEP_ROAD_AADT_ATTRIBUTE_MIN_OVERLAP_RATIO", 0.50)
ROAD_AADT_ATTRIBUTE_MAX_ENDPOINT_SUM_DIFF = _env_float("THIRDSTEP_ROAD_AADT_ATTRIBUTE_MAX_ENDPOINT_SUM_DIFF", 0.25)
ROAD_AADT_ATTRIBUTE_MIN_ABSOLUTE_OVERLAP = _env_float("THIRDSTEP_ROAD_AADT_ATTRIBUTE_MIN_ABSOLUTE_OVERLAP", 0.05)
ROAD_AADT_ATTRIBUTE_ACCEPT_SINGLE_ROUTE_CANDIDATE = _env_bool("THIRDSTEP_ROAD_AADT_ATTRIBUTE_ACCEPT_SINGLE_ROUTE_CANDIDATE", True)
ROADS_STUDY_AADT_CACHE = STAGED["roads_study_aadt_cache"]


# Oracle broad lookup inputs exported by cotedopget.py.
# Oracle integration is optional by default and should only be required when
# explicitly enabled for a second-pass directional refinement.
ORACLE_INTEGRATION_REQUIRED = _env_bool("THIRDSTEP_ORACLE_INTEGRATION_REQUIRED", False)
ORACLE_GIS_KEYS_REQUIRED = _env_bool("THIRDSTEP_ORACLE_GIS_KEYS_REQUIRED", False)
ALLOW_GIS_ONLY_DIRECTION_FALLBACK = _env_bool("THIRDSTEP_ALLOW_GIS_ONLY_DIRECTION_FALLBACK", True)
ORACLE_BROAD_LOOKUP_SOURCE = os.environ.get("THIRDSTEP_ORACLE_BROAD_LOOKUP_SOURCE") or None
ORACLE_GIS_KEYS_SOURCE = os.environ.get("THIRDSTEP_ORACLE_GIS_KEYS_SOURCE") or None
ORACLE_REQUIRED_COLUMNS = [
    "TMSLINKID", "RTE_NM", "BEGINNODE", "ENDNODE", "LINKSEQUENCE", "ROUTEMILEPOINT",
    "BEGINOFFSET", "ENDOFFSET", "AVERAGEDAILYTRAFFIC", "RURALURBANDESIGNATION"
]
ORACLE_GIS_KEYS_REQUIRED_COLUMNS = [
    "LINKID", "MASTER_RTE_NM", "FromNode_Norm", "ToNode_Norm", "SegMid_M", "Signal_M", "Delta_M", "Flow_Role", "AADT_GIS"
]
ORACLE_NODE_INTERSECTION_TOL = 25.0
ORACLE_GIS_KEYS_MATCH_ENABLED = True

# GIS-side From/To node fields are retained for compatibility, but they are
# frequently blank in the current base layers and should not be treated as
# authoritative unless a trusted upstream source is introduced.
# OracleBeginNode / OracleEndNode / IntersectionNode are the authoritative
# node-aware outputs for downstream interpretation.

EXPORT_FIELDS = {
    "segments": [
        "SegOID", "SegStableID", "ParentRoadOID", "SignalOID", "LinkID_Norm", "RouteID_Norm", "RouteNm_Norm",
        "DirCode_Norm", "FromNode_Norm", "ToNode_Norm", "AADT", "Seg_Len_Ft", "Mid_X", "Mid_Y"
    ],
    "signals": [
        "SignalOID", "ParentRoadOID", "LinkID_Norm", "RouteID_Norm", "RouteNm_Norm",
        "DirCode_Norm", "FromNode_Norm", "ToNode_Norm"
    ],
    "crashes": [
        "CrashOID", "SegOID"
    ],
    "parent_roads": [
        "ParentRoadOID", "LinkID_Norm", "RouteID_Norm", "RouteNm_Norm",
        "DirCode_Norm", "FromNode_Norm", "ToNode_Norm"
    ],
}

# Candidate field groups
CANDIDATE_FIELDS = {
    "signal_id": ["SignalID", "SIGNAL_ID", "REG_SIGNAL_ID", "SIGNAL_NO", "ID", "INTERSECTION_ID", "OBJECTID"],
    "link_id": ["LINKID", "LinkID", "LINK_ID", "TMSLINKID", "TMS_LINKID", "LRS_LINKID", "LRS_LINK_ID"],
    "route_id": ["RTE_ID", "RouteID", "ROUTEID", "ROUTE_ID", "MASTER_RTE_NM", "RTE_NM"],
    "route_name": ["ROUTE_COMMON_NAME", "RTE_COMMON", "MASTER_RTE_NM", "RTE_NM", "RouteName", "ROUTE_NAME", "STREET_NAME", "RD_NAME"],
    "dir_code": ["DIRECTIONALITY", "LOC_COMP_DIRECTIONALITY_NAME", "LOC_COMP_D", "DirCode", "DIR_CODE", "DIRECTION", "CARDINAL_DIR", "RTE_DIR", "NB_SB_EB_WB"],
    "from_node": ["BEGINNODE", "FromNode", "FROM_NODE", "BEG_NODE", "START_NODE"],
    "to_node": ["ENDNODE", "ToNode", "TO_NODE", "END_NODE", "FIN_NODE"],
    "parent_road_oid": ["ParentRoadOID", "PARENT_ROAD_OID"],
    "seg_id": ["SegOID", "SEG_OID", "SEGMENT_ID"],
    "collision_type": ["COLLISION_TYPE", "CrashType", "CRASH_TYPE", "TYPE"],
    "aadt": ["AADT", "AVERAGEDAILYTRAFFIC", "CUR_AADT", "AADT_2023"],
    "speed": ["CAR_SPEED_LIMIT", "CARSPEEDLIMIT", "SPEED_LIMIT", "SPEED", "RN_SPEED_LIMIT"],
}

# Additional field-detection helpers used by field_normalization.py
# These extend exact-candidate matching with token-based scoring while avoiding
# obvious join/artifact fields.

ROAD_FIELD_EXTRA_CANDIDATES = {
    "link_id": [
        "LinkID_Norm", "LINKID_NORM",
        "TMSLINKID", "TMS_LINKID",
        "LINK_ID", "LRS_LINKID", "LRS_LINK_ID",
    ],
    "route_id": [
        "RouteID_Norm", "ROUTEID_NORM",
        "MASTER_RTE_NM", "RTE_NM",
        "ROUTE_ID", "ROUTEID", "RTE_ID",
    ],
    "route_name": [
        "RouteNm_Norm", "ROUTENM_NORM",
        "ROUTE_COMMON_NAME", "RTE_COMMON",
        "ROUTE_NAME", "RouteName",
        "STREET_NAME", "RD_NAME",
    ],
    "dir_code": [
        "DirCode_Norm", "DIRCODE_NORM",
        "DIRECTIONALITY", "LOC_COMP_DIRECTIONALITY_NAME", "LOC_COMP_D",
        "DIR_CODE", "DIRECTION", "CARDINAL_DIR", "RTE_DIR",
        "NB_SB_EB_WB",
    ],
    "from_node": [
        "FromNode_Norm", "FROMNODE_NORM",
        "BEGINNODE", "FROM_NODE", "FromNode",
        "BEG_NODE", "START_NODE",
    ],
    "to_node": [
        "ToNode_Norm", "TONODE_NORM",
        "ENDNODE", "TO_NODE", "ToNode",
        "END_NODE", "FIN_NODE",
    ],
    "aadt": [
        "AADT", "AADT_2023", "CUR_AADT",
        "AVERAGEDAILYTRAFFIC",
    ],
}

ROAD_FIELD_TOKEN_HINTS = {
    "link_id": [
        ("LINK", "ID"),
        ("TMS", "LINK"),
        ("LRS", "LINK"),
    ],
    "route_id": [
        ("RTE",),
        ("ROUTE",),
        ("MASTER", "RTE"),
    ],
    "route_name": [
        ("ROUTE", "NAME"),
        ("STREET", "NAME"),
        ("ROAD", "NAME"),
        ("COMMON",),
    ],
    "dir_code": [
        ("DIR",),
        ("DIRECTION",),
        ("CARDINAL",),
    ],
    "from_node": [
        ("BEGIN", "NODE"),
        ("FROM", "NODE"),
        ("START", "NODE"),
        ("BEG", "NODE"),
    ],
    "to_node": [
        ("END", "NODE"),
        ("TO", "NODE"),
        ("FIN", "NODE"),
    ],
    "aadt": [
        ("AADT",),
        ("AVERAGE", "DAILY", "TRAFFIC"),
        ("TRAFFIC",),
    ],
}

ROAD_FIELD_EXCLUDE_TOKENS = {
    "link_id": {"JOIN", "TARGET", "ORACLE", "MATCH", "STATUS", "LEVEL", "SEQUENCE", "MP"},
    "route_id": {"JOIN", "TARGET", "ORACLE", "MATCH", "STATUS", "LEVEL", "SEQUENCE", "MP"},
    "route_name": {"JOIN", "TARGET", "ORACLE", "MATCH", "STATUS", "LEVEL", "SEQUENCE", "MP"},
    "dir_code": {"JOIN", "TARGET", "ORACLE", "MATCH", "STATUS", "LEVEL", "SEQUENCE", "MP"},
    "from_node": {"JOIN", "TARGET", "ORACLE", "MATCH", "STATUS", "LEVEL", "SEQUENCE", "MP"},
    "to_node": {"JOIN", "TARGET", "ORACLE", "MATCH", "STATUS", "LEVEL", "SEQUENCE", "MP"},
    "aadt": {"JOIN", "TARGET", "ORACLE", "MATCH", "STATUS", "LEVEL", "SEQUENCE", "MP"},
}


# Explicit schema-aware overrides for known base layers. These are consulted
# before generic token-based field detection to avoid misclassifying layers
# whose schemas intentionally do not contain certain concepts.
EXPLICIT_NORMALIZATION_SOURCE_FIELDS = {
    "TRAVELWAY": {
        "route_id": ["RTE_ID"],
        "route_name": ["RTE_COMMON", "RTE_NM"],
        "dir_code": ["LOC_COMP_D"],
        "link_id": [],
        "from_node": [],
        "to_node": [],
        "aadt": [],
    },
    "TW_ROADS_PROJ": {
        "route_id": ["RTE_ID"],
        "route_name": ["RTE_COMMON", "RTE_NM"],
        "dir_code": ["LOC_COMP_D"],
        "link_id": [],
        "from_node": [],
        "to_node": [],
        "aadt": [],
    },
    "TW_ROADS": {
        "route_id": ["RTE_ID"],
        "route_name": ["RTE_COMMON", "RTE_NM"],
        "dir_code": ["LOC_COMP_D"],
        "link_id": [],
        "from_node": [],
        "to_node": [],
        "aadt": [],
    },
    "NEW_AADT": {
        "link_id": ["LINKID"],
        "route_id": ["MASTER_RTE_NM", "RTE_NM"],
        "route_name": ["MASTER_RTE_NM", "RTE_NM"],
        "dir_code": ["DIRECTIONALITY"],
        "from_node": [],
        "to_node": [],
        "aadt": ["AADT"],
    },
}

EXPECTED_MISSING_CANONICAL_FIELDS = {
    "TRAVELWAY": {"LinkID_Norm", "FromNode_Norm", "ToNode_Norm", "AADT"},
    "TW_ROADS_PROJ": {"LinkID_Norm", "FromNode_Norm", "ToNode_Norm", "AADT"},
    "TW_ROADS": {"LinkID_Norm", "FromNode_Norm", "ToNode_Norm", "AADT"},
    "NEW_AADT": {"FromNode_Norm", "ToNode_Norm"},
}

# Functional distances by speed
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


# Road normalization/enrichment controls
ROAD_ROLE_FOR_NORMALIZATION = "TRAVELWAY"
REQUIRE_ROAD_ROLE_FIELDS = False
ENABLE_ROAD_AADT_ENRICHMENT = True
STRICT_ROAD_AADT_ENRICHMENT = False
