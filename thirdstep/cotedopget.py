# -*- coding: utf-8 -*-
"""
PROJECT: VDOT INTERSECTION SAFETY & ACCESS MANAGEMENT ANALYSIS
MODULE:  Oracle broad lookup export for later GIS/network matching
FILE:    cotedopget.py

PURPOSE
-------
This script extracts Oracle network-reference rows from rns.eyroadxx for the
LINKIDs present in an ArcGIS feature class, then writes a broad lookup CSV that
can be matched later inside a geospatial workflow.

This script intentionally does *not* assume LINKID alone is a safe one-to-one
join key. Per project findings:

- GIS LINKID corresponds to Oracle TMSLINKID, but not one-to-one.
- One TMSLINKID can return many Oracle rows.
- A GIS LINKID can appear in multiple directional records.
- Direction/route context must also be considered later, typically using
  MASTER_RTE_NM <-> RTE_NM plus node or route-order fields.

Accordingly, the default export is a "Layer 1" broad Oracle lookup export.
A separate GIS key export is also written to support later match logic.

OUTPUTS
-------
1) Broad Oracle CSV containing route/network records for relevant TMSLINKIDs.
2) GIS key CSV containing distinct GIS-side segment keys for later matching.
3) Optional summary text file with extraction counts and configuration.

NOTES
-----
- This script is designed as a retrieval step, not the final matching step.
- Use the Oracle CSV later with GIS route names, nodes, and/or measures.
- Oracle connection can be provided either as Easy Connect DSN or TNS alias.
"""

import os
import math
from itertools import islice

import arcpy
import oracledb
import pandas as pd


# ---------------------------------------------------------------------------
# USER SETTINGS
# ---------------------------------------------------------------------------

# ArcGIS input layer containing the relevant LINKIDs.
INPUT_FC = (
    r"C:\Users\Jameson.Clements\Documents\ArcGIS\Projects\CrashIntersectionAnalysis"
    r"\CrashIntersectionAnalysis.gdb\Final_Functional_Segments"
)

# GIS fields used to define later matching keys.
LINKID_FIELD = "LinkID_Norm"
ROUTE_FIELD = "RouteNm_Norm"
FROM_NODE_FIELD = "FromNode_Norm"
TO_NODE_FIELD = "ToNode_Norm"
SEG_MID_FIELD = "SegMid_M"
SIGNAL_M_FIELD = "Signal_M"
DELTA_M_FIELD = "Delta_M"
FLOW_ROLE_FIELD = "Flow_Role"
AADT_FIELD = "AADT"

# Oracle connection.
ORACLE_USER = "guest"
ORACLE_PASSWORD = "guest"
ORACLE_DSN = "cotedop.world"

# Oracle source object.
ORACLE_TABLE = "rns.eyroadxx"

# Core Oracle fields recommended by the project note.
CORE_ORACLE_COLUMNS = [
    "TMSLINKID",
    "RTE_NM",
    "BEGINNODE",
    "ENDNODE",
    "LINKSEQUENCE",
    "ROUTEMILEPOINT",
    "BEGINOFFSET",
    "ENDOFFSET",
    "AVERAGEDAILYTRAFFIC",
    "RURALURBANDESIGNATION",
]

# Additional Oracle cross-section fields.
# Set INCLUDE_BL_BV = False if these fields do not exist in the source table.
INCLUDE_BL_BV = False
BL_BV_COLUMNS = [f"B{chr(code)}" for code in range(ord("L"), ord("V") + 1)]

# Output locations.
OUTPUT_DIR = r"C:\Users\Jameson.Clements\IntersectionCrashAnalysis\oracle_exports"
ORACLE_OUTPUT_CSV = os.path.join(OUTPUT_DIR, "cotedop_oracle_broad_lookup.csv")
GIS_KEYS_OUTPUT_CSV = os.path.join(OUTPUT_DIR, "cotedop_gis_keys.csv")
SUMMARY_TXT = os.path.join(OUTPUT_DIR, "cotedop_extract_summary.txt")

# Extraction behavior.
CHUNK_SIZE = 900          # stays under Oracle IN-list limit
DISTINCT_LINKIDS = True
FILTER_NULL_ROUTE_NAMES = False
WRITE_SUMMARY = True

# Optional Oracle session tuning.
CURSOR_ARRAYSIZE = 1000


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def msg(text):
    """Console + ArcGIS-safe messaging."""
    print(text)
    try:
        arcpy.AddMessage(text)
    except Exception:
        pass



def ensure_output_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)



def chunked(iterable, size):
    it = iter(iterable)
    while True:
        batch = list(islice(it, size))
        if not batch:
            break
        yield batch



def normalize_scalar(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None



def normalize_route_name(value):
    value = normalize_scalar(value)
    if value is None:
        return None
    return " ".join(value.split())



def normalize_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None



def list_field_names(fc):
    return [f.name for f in arcpy.ListFields(fc)]



def require_fields(fc, required_fields):
    existing_upper = {name.upper() for name in list_field_names(fc)}
    missing = [f for f in required_fields if f.upper() not in existing_upper]
    if missing:
        raise RuntimeError(
            "Missing required fields in {}: {}".format(fc, ", ".join(missing))
        )



def build_oracle_column_list():
    cols = list(CORE_ORACLE_COLUMNS)
    if INCLUDE_BL_BV:
        cols.extend(BL_BV_COLUMNS)
    # Preserve order while removing duplicates.
    seen = set()
    ordered = []
    for c in cols:
        cu = c.upper()
        if cu not in seen:
            ordered.append(c)
            seen.add(cu)
    return ordered



def quote_ident_list(columns):
    # Table/view column names here are trusted static config, not user input.
    return ", ".join(columns)



def read_gis_keys(fc):
    """
    Read distinct GIS-side keys that can later be used to match Oracle rows.

    We intentionally export more than LINKID because LINKID alone is not a safe
    final join key for direction-aware workflow.
    """
    required = [LINKID_FIELD]
    require_fields(fc, required)

    fields_to_read = [
        LINKID_FIELD,
        ROUTE_FIELD,
        FROM_NODE_FIELD,
        TO_NODE_FIELD,
        SEG_MID_FIELD,
        SIGNAL_M_FIELD,
        DELTA_M_FIELD,
        FLOW_ROLE_FIELD,
        AADT_FIELD,
    ]
    available_upper = {f.upper(): f for f in list_field_names(fc)}
    actual_fields = [f for f in fields_to_read if f.upper() in available_upper]

    rows = []
    with arcpy.da.SearchCursor(fc, actual_fields) as cursor:
        for row in cursor:
            rec = dict(zip(actual_fields, row))
            linkid = normalize_scalar(rec.get(LINKID_FIELD))
            if linkid is None:
                continue

            route_nm = normalize_route_name(rec.get(ROUTE_FIELD))
            if FILTER_NULL_ROUTE_NAMES and not route_nm:
                continue

            rows.append(
                {
                    "LINKID": linkid,
                    "MASTER_RTE_NM": route_nm,
                    "FromNode_Norm": normalize_scalar(rec.get(FROM_NODE_FIELD)),
                    "ToNode_Norm": normalize_scalar(rec.get(TO_NODE_FIELD)),
                    "SegMid_M": normalize_number(rec.get(SEG_MID_FIELD)),
                    "Signal_M": normalize_number(rec.get(SIGNAL_M_FIELD)),
                    "Delta_M": normalize_number(rec.get(DELTA_M_FIELD)),
                    "Flow_Role": normalize_scalar(rec.get(FLOW_ROLE_FIELD)),
                    "AADT_GIS": normalize_number(rec.get(AADT_FIELD)),
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Make the GIS export stable and deduplicated.
    if DISTINCT_LINKIDS:
        linkids = sorted(df["LINKID"].dropna().astype(str).unique().tolist())
    else:
        linkids = df["LINKID"].dropna().astype(str).tolist()

    df = df.drop_duplicates().sort_values(
        by=[c for c in ["LINKID", "MASTER_RTE_NM", "FromNode_Norm", "ToNode_Norm", "SegMid_M"] if c in df.columns],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)

    return df, linkids



def oracle_connect(user, password, dsn):
    return oracledb.connect(user=user, password=password, dsn=dsn)



def query_oracle_by_linkid_chunk(cursor, table_name, columns, linkid_chunk):
    """
    Broad lookup export.

    This intentionally queries Oracle by TMSLINKID only, because the current
    task is to export the reference-network rows first. Route/name/node/measure
    disambiguation happens later in the GIS matching step.
    """
    placeholders = ", ".join(f":{i+1}" for i in range(len(linkid_chunk)))
    sql = f"""
        SELECT {quote_ident_list(columns)}
        FROM {table_name}
        WHERE TMSLINKID IN ({placeholders})
        ORDER BY TMSLINKID, RTE_NM, LINKSEQUENCE, ROUTEMILEPOINT
    """
    cursor.execute(sql, linkid_chunk)
    rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=columns)



def sanitize_oracle_df(df):
    if df.empty:
        return df

    out = df.copy()

    # Normalize key text fields.
    for col in [c for c in ["TMSLINKID", "RTE_NM", "BEGINNODE", "ENDNODE"] if c in out.columns]:
        out[col] = out[col].map(normalize_scalar)

    if "RTE_NM" in out.columns:
        out["RTE_NM"] = out["RTE_NM"].map(normalize_route_name)

    # Sort/dedupe for stable export.
    sort_cols = [c for c in ["TMSLINKID", "RTE_NM", "LINKSEQUENCE", "ROUTEMILEPOINT", "BEGINNODE", "ENDNODE"] if c in out.columns]
    out = out.drop_duplicates()
    if sort_cols:
        out = out.sort_values(by=sort_cols, kind="mergesort", na_position="last")
    return out.reset_index(drop=True)



def write_summary_txt(path, gis_df, oracle_df, oracle_columns, linkids):
    with open(path, "w", encoding="utf-8") as f:
        f.write("COTEDOP ORACLE EXTRACTION SUMMARY\n")
        f.write("=" * 72 + "\n")
        f.write(f"Input feature class: {INPUT_FC}\n")
        f.write(f"Oracle table/view:   {ORACLE_TABLE}\n")
        f.write(f"Oracle DSN:          {ORACLE_DSN}\n")
        f.write(f"Chunk size:          {CHUNK_SIZE}\n")
        f.write(f"Unique LINKIDs read: {len(linkids)}\n")
        f.write(f"GIS key rows:        {0 if gis_df is None else len(gis_df)}\n")
        f.write(f"Oracle rows output:  {0 if oracle_df is None else len(oracle_df)}\n")
        f.write("\n")
        f.write("Oracle columns exported:\n")
        for col in oracle_columns:
            f.write(f"- {col}\n")
        f.write("\n")
        f.write("Design note:\n")
        f.write(
            "This is a broad lookup export. Final GIS-to-Oracle matching should use\n"
            "LINKID/TMSLINKID plus route name and, where possible, node or measure\n"
            "fields rather than LINKID alone.\n"
        )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    msg("-" * 72)
    msg("Starting cotedopget.py")
    msg("Reading GIS segment keys...")

    ensure_output_dir(OUTPUT_DIR)

    oracle_columns = build_oracle_column_list()
    gis_df, linkids = read_gis_keys(INPUT_FC)

    if not linkids:
        raise RuntimeError("No non-null LINKID values found in the input feature class.")

    msg(f"Found {len(linkids)} relevant LINKIDs in GIS.")
    msg(f"Writing GIS-side key export: {GIS_KEYS_OUTPUT_CSV}")
    gis_df.to_csv(GIS_KEYS_OUTPUT_CSV, index=False)

    msg("Connecting to Oracle...")
    conn = oracle_connect(ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN)
    cur = conn.cursor()
    cur.arraysize = CURSOR_ARRAYSIZE

    dfs = []
    total_chunks = int(math.ceil(len(linkids) / float(CHUNK_SIZE)))

    try:
        for i, id_chunk in enumerate(chunked(linkids, CHUNK_SIZE), start=1):
            msg(f"Querying Oracle chunk {i}/{total_chunks} ({len(id_chunk)} LINKIDs)...")
            dfs.append(query_oracle_by_linkid_chunk(cur, ORACLE_TABLE, oracle_columns, id_chunk))
    finally:
        try:
            cur.close()
        finally:
            conn.close()

    if dfs:
        oracle_df = pd.concat(dfs, ignore_index=True)
    else:
        oracle_df = pd.DataFrame(columns=oracle_columns)

    oracle_df = sanitize_oracle_df(oracle_df)

    msg(f"Writing Oracle broad lookup CSV: {ORACLE_OUTPUT_CSV}")
    oracle_df.to_csv(ORACLE_OUTPUT_CSV, index=False)

    if WRITE_SUMMARY:
        msg(f"Writing summary text file: {SUMMARY_TXT}")
        write_summary_txt(SUMMARY_TXT, gis_df, oracle_df, oracle_columns, linkids)

    msg("Done.")
    msg("This export is intended for later route/node/measure-aware GIS matching.")
    msg("-" * 72)


if __name__ == "__main__":
    main()
