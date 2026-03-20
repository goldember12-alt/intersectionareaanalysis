# -*- coding: utf-8 -*-
"""
GeoPandas/Oracle export, directional labeling, and Oracle-first match logic.

The directional stage now treats Oracle reference CSVs as part of the core
runtime contract for production runs. GIS-side FromNode_Norm / ToNode_Norm may
be present for compatibility, but they are not assumed to be authoritative.
"""

import math
import os
import sys
import time
import config as cfg
from arcpy_utils import (
    delete_if_exists, field_map_upper, geopandas_pipeline_enabled, safe_field_name
)
from config import *
from field_normalization import normalize_linkid_value
from logging_utils import msg, log_phase_time


def ensure_export_dir():
    if not os.path.exists(EXPORT_DIR):
        os.makedirs(EXPORT_DIR, exist_ok=True)

def export_fc_to_gdb(in_fc, out_gdb, out_name, field_names=None):
    if not WRITE_GPKG_EXPORT:
        return
    if not arcpy.Exists(in_fc):
        return
    if not arcpy.Exists(out_gdb):
        arcpy.management.CreateFileGDB(os.path.dirname(out_gdb), os.path.basename(out_gdb))

    out_fc = os.path.join(out_gdb, out_name)
    if arcpy.Exists(out_fc):
        arcpy.management.Delete(out_fc)

    if field_names:
        fmap = arcpy.FieldMappings()
        existing = field_map_upper(in_fc)
        for fld in field_names:
            real = existing.get(fld.upper())
            if real:
                fm = arcpy.FieldMap()
                fm.addInputField(in_fc, real)
                fmap.addFieldMap(fm)
        arcpy.conversion.FeatureClassToFeatureClass(in_fc, out_gdb, out_name, field_mapping=fmap)
    else:
        arcpy.conversion.FeatureClassToFeatureClass(in_fc, out_gdb, out_name)

def export_table_to_csv(in_table, out_csv):
    """Minimal table export retained only for Oracle lookup fallback paths."""
    if pd is None:
        return
    fields = [f.name for f in arcpy.ListFields(in_table) if f.type not in ("Geometry", "Blob", "Raster")]
    rows = [r for r in arcpy.da.SearchCursor(in_table, fields)]
    df = pd.DataFrame(rows, columns=fields)
    df.to_csv(out_csv, index=False)

def export_working_layers(segments_fc, signals_fc, crashes_fc, parent_roads_fc):
    if not geopandas_pipeline_enabled():
        msg("    -> Skipping export; GeoPandas pipeline is unavailable or disabled")
        return

    if DIRECT_GDB_TO_GEOPANDAS:
        msg("    -> Direct GeoPandas reads enabled; skipping FGDB export handoff")
        return

    msg("    -> Exporting working layers for GeoPandas")
    ensure_export_dir()

    if not arcpy.Exists(EXPORT_GDB):
        arcpy.management.CreateFileGDB(os.path.dirname(EXPORT_GDB), os.path.basename(EXPORT_GDB))

    export_fc_to_gdb(segments_fc, EXPORT_GDB, "segments", EXPORT_FIELDS["segments"])
    export_fc_to_gdb(signals_fc, EXPORT_GDB, "signals", EXPORT_FIELDS["signals"])
    export_fc_to_gdb(crashes_fc, EXPORT_GDB, "crashes", EXPORT_FIELDS["crashes"])
    export_fc_to_gdb(parent_roads_fc, EXPORT_GDB, "parent_roads", EXPORT_FIELDS["parent_roads"])

def _read_fc_direct_to_gdf(in_fc, field_names=None):
    if gpd is None:
        raise RuntimeError("GeoPandas is not available in this Python environment.")
    if not arcpy.Exists(in_fc):
        raise RuntimeError(f"Feature class not found for GeoPandas read: {in_fc}")

    desc = arcpy.Describe(in_fc)
    catalog_path = desc.catalogPath
    fc_name = os.path.basename(catalog_path)
    workspace = os.path.dirname(catalog_path)

    kwargs = {}
    if field_names:
        kwargs["columns"] = [f for f in field_names if f]

    try:
        return gpd.read_file(workspace, layer=fc_name, **kwargs)
    except TypeError:
        return gpd.read_file(workspace, layer=fc_name)
    except Exception:
        return gpd.read_file(catalog_path)

def read_fc_to_gdf(layer_or_path, layer_name=None, field_names=None):
    if gpd is None:
        raise RuntimeError("GeoPandas is not available in this Python environment.")

    if layer_or_path and arcpy.Exists(layer_or_path):
        return _read_fc_direct_to_gdf(layer_or_path, field_names=field_names)

    if DIRECT_GDB_TO_GEOPANDAS and layer_or_path is None and layer_name in STAGED:
        return _read_fc_direct_to_gdf(STAGED[layer_name], field_names=field_names)

    if DIRECT_GDB_TO_GEOPANDAS and layer_or_path is None:
        mapped = {
            "segments": STAGED["seg_clean"],
            "signals": STAGED["signals_speed"],
            "crashes": STAGED["crash_assigned"],
            "parent_roads": STAGED["roads_study"],
        }.get(layer_name)
        if mapped and arcpy.Exists(mapped):
            return _read_fc_direct_to_gdf(mapped, field_names=field_names)

    if layer_name and arcpy.Exists(EXPORT_GDB):
        try:
            return gpd.read_file(EXPORT_GDB, layer=layer_name, columns=field_names or None)
        except TypeError:
            return gpd.read_file(EXPORT_GDB, layer=layer_name)

    if layer_or_path and os.path.exists(layer_or_path):
        return gpd.read_file(layer_or_path)

    raise RuntimeError(f"Could not read layer {layer_name or layer_or_path} into GeoPandas.")

def write_df_to_table(df, out_csv):
    if pd is None:
        raise RuntimeError("pandas is not available in this Python environment.")
    df.to_csv(out_csv, index=False)
    return out_csv

def classify_side_by_measure(delta, tol=MIDPOINT_AT_SIGNAL_TOL_FT):
    if delta is None or (isinstance(delta, float) and math.isnan(delta)):
        return "Unknown"
    if abs(delta) <= tol:
        return "AtSignal"
    return "Positive" if delta > 0 else "Negative"

def _is_blankish(value):
    if value in (None, "", " "):
        return True
    try:
        return bool(pd is not None and pd.isna(value))
    except Exception:
        return False


def normalize_dir_text(value):
    if _is_blankish(value):
        return None
    s = str(value).strip().upper()
    mapping = {
        "NORTHBOUND": "NB", "NB": "NB",
        "SOUTHBOUND": "SB", "SB": "SB",
        "EASTBOUND": "EB", "EB": "EB",
        "WESTBOUND": "WB", "WB": "WB",
        "WITH": "WITH", "DIGITIZED": "WITH", "POSITIVE": "POSITIVE",
        "AGAINST": "AGAINST", "NEGATIVE": "NEGATIVE",
    }
    return mapping.get(s, s)

def normalize_route_name(value):
    if _is_blankish(value):
        return ""
    return " ".join(str(value).strip().upper().split())

def route_name_from_context(context):
    """Authoritative normalized route name from RouteNm_Norm only.

    RouteID_Norm is intentionally not used as a fallback route-name source.
    Blank route names should bypass route filtering rather than forcing mismatch.
    """
    return normalize_route_name((context or {}).get("RouteNm_Norm"))

def normalize_node_value(value):
    if _is_blankish(value):
        return ""
    return str(value).strip()

def normalize_measure_value(value):
    try:
        if _is_blankish(value):
            return None
        return float(value)
    except Exception:
        return None

def validate_oracle_schema(df):
    cols_upper = {str(c).upper(): c for c in df.columns}
    missing = [c for c in ORACLE_REQUIRED_COLUMNS if c.upper() not in cols_upper]
    if missing:
        raise RuntimeError(f"Oracle broad lookup missing required columns: {', '.join(missing)}")
    return cols_upper

def validate_oracle_gis_keys_schema(df):
    cols_upper = {str(c).upper(): c for c in df.columns}
    missing = [c for c in ORACLE_GIS_KEYS_REQUIRED_COLUMNS if c.upper() not in cols_upper]
    if missing:
        raise RuntimeError(f"Oracle GIS-keys export missing required columns: {', '.join(missing)}")
    return cols_upper

def _normalize_oracle_gis_keys_df(df):
    cols_upper = validate_oracle_gis_keys_schema(df)
    rename = {cols_upper[k.upper()]: k for k in ORACLE_GIS_KEYS_REQUIRED_COLUMNS if k.upper() in cols_upper}
    out = df.rename(columns=rename).copy()
    out["LINKID"] = out["LINKID"].map(normalize_linkid_value)
    out["MASTER_RTE_NM"] = out["MASTER_RTE_NM"].map(normalize_route_name)
    out["FromNode_Norm"] = out["FromNode_Norm"].map(normalize_node_value)
    out["ToNode_Norm"] = out["ToNode_Norm"].map(normalize_node_value)
    for c in ["SegMid_M", "Signal_M", "Delta_M", "AADT_GIS"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    sort_cols = [c for c in ["LINKID", "MASTER_RTE_NM", "FromNode_Norm", "ToNode_Norm", "SegMid_M", "Signal_M"] if c in out.columns]
    return out.drop_duplicates().sort_values(by=sort_cols, kind="mergesort", na_position="last").reset_index(drop=True)

def _build_oracle_gis_key_indexes(gis_keys_df):
    if gis_keys_df is None or gis_keys_df.empty:
        return {
            "df": gis_keys_df,
            "by_link": {},
            "by_link_route": {},
            "by_link_route_nodes": {},
            "by_link_route_signal": {},
        }
    by_link = {k: g.copy() for k, g in gis_keys_df.groupby("LINKID", dropna=False)}
    by_link_route = {(k1, k2): g.copy() for (k1, k2), g in gis_keys_df.groupby(["LINKID", "MASTER_RTE_NM"], dropna=False)}
    by_link_route_nodes = {(k1, k2, k3, k4): g.copy() for (k1, k2, k3, k4), g in gis_keys_df.groupby(["LINKID", "MASTER_RTE_NM", "FromNode_Norm", "ToNode_Norm"], dropna=False)}
    signal_groups = {}
    if "Signal_M" in gis_keys_df.columns:
        tmp = gis_keys_df.copy()
        tmp["__Signal_M_round"] = tmp["Signal_M"].round(3)
        signal_groups = {
            (k1, k2, k3): g.drop(columns=["__Signal_M_round"]).copy()
            for (k1, k2, k3), g in tmp.groupby(["LINKID", "MASTER_RTE_NM", "__Signal_M_round"], dropna=False)
        }
    return {
        "df": gis_keys_df,
        "by_link": by_link,
        "by_link_route": by_link_route,
        "by_link_route_nodes": by_link_route_nodes,
        "by_link_route_signal": signal_groups,
    }


def _oracle_mode_required():
    return bool(USE_ORACLE_MATCH_RESOLUTION and ORACLE_INTEGRATION_REQUIRED and not ALLOW_GIS_ONLY_DIRECTION_FALLBACK)


def validate_oracle_runtime_contract(segment_linkids=None):
    """Validate Oracle prerequisites before expensive GeoPandas work starts."""
    diagnostics = {
        "oracle_enabled": bool(USE_ORACLE_MATCH_RESOLUTION),
        "oracle_required": bool(_oracle_mode_required()),
        "gis_only_fallback_allowed": bool(ALLOW_GIS_ONLY_DIRECTION_FALLBACK),
        "broad_lookup_source": ORACLE_BROAD_LOOKUP_SOURCE,
        "gis_keys_source": ORACLE_GIS_KEYS_SOURCE,
        "broad_lookup_exists": False,
        "gis_keys_exists": False,
        "broad_lookup_rows": 0,
        "gis_keys_rows": 0,
        "oracle_distinct_linkids": 0,
        "segment_distinct_linkids": 0,
        "covered_segment_linkids": 0,
        "segment_linkid_coverage_pct": None,
    }

    if not USE_ORACLE_MATCH_RESOLUTION:
        if _oracle_mode_required():
            raise RuntimeError("Oracle integration is required, but USE_ORACLE_MATCH_RESOLUTION is False.")
        return diagnostics

    missing = []
    if not ORACLE_BROAD_LOOKUP_SOURCE:
        missing.append("ORACLE_BROAD_LOOKUP_SOURCE is not set")
    elif not os.path.exists(ORACLE_BROAD_LOOKUP_SOURCE):
        missing.append(f"Oracle broad lookup source not found: {ORACLE_BROAD_LOOKUP_SOURCE}")
    else:
        diagnostics["broad_lookup_exists"] = True

    if ORACLE_GIS_KEYS_REQUIRED:
        if not ORACLE_GIS_KEYS_SOURCE:
            missing.append("ORACLE_GIS_KEYS_SOURCE is not set")
        elif not os.path.exists(ORACLE_GIS_KEYS_SOURCE):
            missing.append(f"Oracle GIS-keys source not found: {ORACLE_GIS_KEYS_SOURCE}")
        else:
            diagnostics["gis_keys_exists"] = True
    elif ORACLE_GIS_KEYS_SOURCE and os.path.exists(ORACLE_GIS_KEYS_SOURCE):
        diagnostics["gis_keys_exists"] = True

    if missing:
        if _oracle_mode_required():
            raise RuntimeError("Oracle preflight failed: " + " | ".join(missing))
        for item in missing:
            msg(f"    ! {item}")
        return diagnostics

    if pd is None:
        if _oracle_mode_required():
            raise RuntimeError("Oracle preflight failed: pandas is unavailable.")
        msg("    ! pandas unavailable; Oracle preflight diagnostics limited")
        return diagnostics

    broad_df = pd.read_csv(ORACLE_BROAD_LOOKUP_SOURCE)
    validate_oracle_schema(broad_df)
    broad_cols_upper = {str(c).upper(): c for c in broad_df.columns}
    broad_link_col = broad_cols_upper.get("TMSLINKID")
    diagnostics["broad_lookup_rows"] = int(len(broad_df))
    if broad_link_col:
        diagnostics["oracle_distinct_linkids"] = int(
            broad_df[broad_link_col].map(normalize_linkid_value).replace("", pd.NA).dropna().nunique()
        )

    if diagnostics["gis_keys_exists"]:
        gis_keys_df = pd.read_csv(ORACLE_GIS_KEYS_SOURCE)
        validate_oracle_gis_keys_schema(gis_keys_df)
        diagnostics["gis_keys_rows"] = int(len(gis_keys_df))

    if segment_linkids:
        norm_segment_linkids = {normalize_linkid_value(v) for v in segment_linkids if normalize_linkid_value(v)}
        diagnostics["segment_distinct_linkids"] = int(len(norm_segment_linkids))
        if norm_segment_linkids:
            broad_linkids = set()
            if broad_link_col:
                broad_linkids = {normalize_linkid_value(v) for v in broad_df[broad_link_col].tolist() if normalize_linkid_value(v)}
            covered = len(norm_segment_linkids & broad_linkids)
            diagnostics["covered_segment_linkids"] = int(covered)
            diagnostics["segment_linkid_coverage_pct"] = round((covered / float(len(norm_segment_linkids))) * 100.0, 2)

    return diagnostics


def log_oracle_preflight(diagnostics):
    if diagnostics is None:
        return
    msg(
        "    -> Oracle mode: "
        f"enabled={diagnostics.get('oracle_enabled')} | required={diagnostics.get('oracle_required')} | "
        f"fallback_allowed={diagnostics.get('gis_only_fallback_allowed')}"
    )
    msg(
        "    -> Oracle inputs: "
        f"broad_lookup_exists={diagnostics.get('broad_lookup_exists')} rows={diagnostics.get('broad_lookup_rows')} | "
        f"gis_keys_exists={diagnostics.get('gis_keys_exists')} rows={diagnostics.get('gis_keys_rows')}"
    )
    coverage = diagnostics.get("segment_linkid_coverage_pct")
    if coverage is not None:
        msg(
            "    -> Oracle link coverage: "
            f"covered_segment_linkids={diagnostics.get('covered_segment_linkids')} / "
            f"segment_linkids={diagnostics.get('segment_distinct_linkids')} | "
            f"oracle_linkids={diagnostics.get('oracle_distinct_linkids')} | "
            f"distinct_link_coverage_pct={coverage}"
        )

def load_oracle_reference_data():
    if not USE_ORACLE_MATCH_RESOLUTION:
        return None
    diagnostics = validate_oracle_runtime_contract()
    log_oracle_preflight(diagnostics)
    if not ORACLE_BROAD_LOOKUP_SOURCE:
        return None
    if pd is None:
        msg("    ! pandas unavailable; skipping Oracle resolution")
        return None
    if not os.path.exists(ORACLE_BROAD_LOOKUP_SOURCE):
        msg(f"    ! Oracle broad lookup source not found: {ORACLE_BROAD_LOOKUP_SOURCE}")
        return None

    msg(f"    -> Loading Oracle broad lookup: {ORACLE_BROAD_LOOKUP_SOURCE}")
    df = pd.read_csv(ORACLE_BROAD_LOOKUP_SOURCE)
    cols_upper = validate_oracle_schema(df)
    rename = {cols_upper[k.upper()]: k for k in ORACLE_REQUIRED_COLUMNS if k.upper() in cols_upper}
    df = df.rename(columns=rename).copy()

    df["TMSLINKID"] = df["TMSLINKID"].map(normalize_linkid_value)
    df["RTE_NM"] = df["RTE_NM"].map(normalize_route_name)
    df["BEGINNODE"] = df["BEGINNODE"].map(normalize_node_value)
    df["ENDNODE"] = df["ENDNODE"].map(normalize_node_value)
    for c in ["LINKSEQUENCE", "ROUTEMILEPOINT", "BEGINOFFSET", "ENDOFFSET", "AVERAGEDAILYTRAFFIC"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    sort_cols = ["TMSLINKID", "RTE_NM", "LINKSEQUENCE", "ROUTEMILEPOINT", "BEGINNODE", "ENDNODE"]
    df = df.drop_duplicates().sort_values(by=sort_cols, kind="mergesort", na_position="last").reset_index(drop=True)

    gis_keys_df = None
    gis_key_index = None
    if ORACLE_GIS_KEYS_SOURCE and os.path.exists(ORACLE_GIS_KEYS_SOURCE):
        try:
            gis_keys_df = _normalize_oracle_gis_keys_df(pd.read_csv(ORACLE_GIS_KEYS_SOURCE))
            gis_key_index = _build_oracle_gis_key_indexes(gis_keys_df)
        except Exception as ex:
            if ORACLE_GIS_KEYS_REQUIRED and _oracle_mode_required():
                raise RuntimeError(f"Oracle GIS-keys source could not be used: {ex}")
            msg(f"    ! Oracle GIS-keys source could not be used: {ex}")
            gis_keys_df = None
            gis_key_index = None

    return {
        "df": df,
        "by_link": {k: g.copy() for k, g in df.groupby("TMSLINKID", dropna=False)},
        "by_link_route": {(k1, k2): g.copy() for (k1, k2), g in df.groupby(["TMSLINKID", "RTE_NM"], dropna=False)},
        "by_full": {(k1, k2, k3, k4): g.copy() for (k1, k2, k3, k4), g in df.groupby(["TMSLINKID", "RTE_NM", "BEGINNODE", "ENDNODE"], dropna=False)},
        "gis_keys_df": gis_keys_df,
        "gis_key_index": gis_key_index,
    }

def _oracle_context_measure(context):
    ref_m = normalize_measure_value(context.get("Signal_M"))
    if ref_m is None:
        ref_m = normalize_measure_value(context.get("SegMid_M"))
    return ref_m

def _oracle_gis_key_candidates(context, oracle_ref):
    gis_idx = (oracle_ref or {}).get("gis_key_index") if oracle_ref else None
    if not gis_idx:
        return None
    linkid = normalize_linkid_value(context.get("LinkID_Norm"))
    route_nm = route_name_from_context(context)
    from_node = normalize_node_value(context.get("FromNode_Norm"))
    to_node = normalize_node_value(context.get("ToNode_Norm"))
    signal_m = normalize_measure_value(context.get("Signal_M"))
    if linkid and route_nm and signal_m is not None:
        key = (linkid, route_nm, round(signal_m, 3))
        if key in gis_idx.get("by_link_route_signal", {}):
            return gis_idx["by_link_route_signal"][key].copy()
    if linkid and route_nm and from_node and to_node and (linkid, route_nm, from_node, to_node) in gis_idx["by_link_route_nodes"]:
        return gis_idx["by_link_route_nodes"][(linkid, route_nm, from_node, to_node)].copy()
    if linkid and route_nm and (linkid, route_nm) in gis_idx["by_link_route"]:
        return gis_idx["by_link_route"][(linkid, route_nm)].copy()
    if linkid in gis_idx["by_link"]:
        return gis_idx["by_link"][linkid].copy()
    return None

def _oracle_gis_key_guidance(context, oracle_ref):
    gis_keys = _oracle_gis_key_candidates(context, oracle_ref)
    if gis_keys is None or len(gis_keys) == 0:
        return None

    tmp = gis_keys.copy()
    signal_m = normalize_measure_value(context.get("Signal_M"))
    seg_m = normalize_measure_value(context.get("SegMid_M"))
    ref_m = seg_m if seg_m is not None else signal_m

    if ref_m is not None:
        base_col = "SegMid_M" if seg_m is not None and "SegMid_M" in tmp.columns else "Signal_M"
        if base_col in tmp.columns:
            tmp["__m_diff"] = (tmp[base_col] - ref_m).abs()
        else:
            tmp["__m_diff"] = 999999.0
    else:
        tmp["__m_diff"] = 999999.0

    def infer_intersection_from_row(row):
        flow = str(row.get("Flow_Role") or "").strip().lower()
        from_node = normalize_node_value(row.get("FromNode_Norm"))
        to_node = normalize_node_value(row.get("ToNode_Norm"))
        if flow == "upstream":
            return to_node
        if flow == "downstream":
            return from_node
        return None

    tmp["__intersection"] = tmp.apply(infer_intersection_from_row, axis=1)
    tmp["__has_intersection"] = tmp["__intersection"].notna().astype(int)
    tmp = tmp.sort_values(["__has_intersection", "__m_diff", "MASTER_RTE_NM", "FromNode_Norm", "ToNode_Norm"], ascending=[False, True, True, True, True], kind="mergesort", na_position="last")

    top = tmp.iloc[0]
    guidance = {
        "rows": tmp,
        "best_row": top.to_dict(),
        "expected_flow_role": top.get("Flow_Role"),
        "intersection_node": normalize_node_value(top.get("__intersection")),
        "measure_diff": top.get("__m_diff"),
        "from_node": normalize_node_value(top.get("FromNode_Norm")),
        "to_node": normalize_node_value(top.get("ToNode_Norm")),
        "basis": "GISKeys"
    }
    return guidance

def _oracle_candidate_subset_for_context(context, oracle_ref):
    if not oracle_ref:
        return None
    linkid = normalize_linkid_value(context.get("LinkID_Norm"))
    route_nm = route_name_from_context(context)
    if not linkid:
        return None
    if route_nm and (linkid, route_nm) in oracle_ref["by_link_route"]:
        return oracle_ref["by_link_route"][(linkid, route_nm)].copy()
    return oracle_ref["by_link"].get(linkid)

def resolve_intersection_node(context, oracle_ref=None, oracle_ctx=None):
    candidates = []
    for key in ["IntersectionNode", "SignalNode", "Signal_Node", "IntersectNode_Norm"]:
        val = normalize_node_value(context.get(key))
        if val:
            candidates.append((val, "ExistingContextField"))

    guidance = _oracle_gis_key_guidance(context, oracle_ref)
    if guidance and guidance.get("intersection_node"):
        candidates.append((guidance.get("intersection_node"), "GISKeysFlowRoleIntersection"))

    gis_keys = _oracle_gis_key_candidates(context, oracle_ref)
    ref_m = _oracle_context_measure(context)
    if gis_keys is not None and len(gis_keys) > 0:
        tmp = gis_keys.copy()
        if ref_m is not None:
            base_col = "SegMid_M" if context.get("SegMid_M") not in (None, "", " ") and "SegMid_M" in tmp.columns else "Signal_M"
            if base_col in tmp.columns:
                tmp["__m_diff"] = (tmp[base_col] - ref_m).abs()
                tmp = tmp.sort_values(["__m_diff", "MASTER_RTE_NM", "FromNode_Norm", "ToNode_Norm"], kind="mergesort", na_position="last")
        top = tmp.iloc[0]
        shared = set()
        for col in ["FromNode_Norm", "ToNode_Norm"]:
            v = normalize_node_value(top.get(col))
            if v:
                shared.add(v)
        if len(shared) == 1:
            candidates.append((list(shared)[0], "GISKeysSharedNode"))

    oracle_candidates = _oracle_candidate_subset_for_context(context, oracle_ref)
    if oracle_candidates is not None and len(oracle_candidates) > 0:
        best_node = _oracle_consensus_node(_oracle_cluster_candidates(oracle_candidates))
        if best_node:
            candidates.append((best_node, "OracleNodeConsensus"))

    if not candidates:
        return None, "NoIntersectionNode"

    counts = {}
    src_rank = {"ExistingContextField": 6, "GISKeysFlowRoleIntersection": 5, "GISKeysSharedNode": 4, "OracleNodeConsensus": 2}
    for val, src in candidates:
        counts.setdefault(val, {"count": 0, "best": 0, "src": src})
        counts[val]["count"] += 1
        rank = src_rank.get(src, 0)
        if rank > counts[val]["best"]:
            counts[val]["best"] = rank
            counts[val]["src"] = src
    best_val = sorted(counts.items(), key=lambda kv: (-kv[1]["count"], -kv[1]["best"], str(kv[0])))[0][0]
    return best_val, counts[best_val]["src"]

def _oracle_node_subset(df, from_node, to_node):
    if df is None or len(df) == 0:
        return None, None, None
    exact = None
    reversed_df = None
    partial = None
    if from_node and to_node:
        exact = df[(df["BEGINNODE"].map(normalize_node_value) == from_node) & (df["ENDNODE"].map(normalize_node_value) == to_node)]
        reversed_df = df[(df["BEGINNODE"].map(normalize_node_value) == to_node) & (df["ENDNODE"].map(normalize_node_value) == from_node)]
    if from_node or to_node:
        cond = False
        if from_node:
            cond = ((df["BEGINNODE"].map(normalize_node_value) == from_node) | (df["ENDNODE"].map(normalize_node_value) == from_node))
        if to_node:
            cond = cond | ((df["BEGINNODE"].map(normalize_node_value) == to_node) | (df["ENDNODE"].map(normalize_node_value) == to_node))
        partial = df[cond]
    return exact, reversed_df, partial

def _oracle_result_defaults(context, status="NoOracleMatch", level="NoOracleMatch", basis="NoOracleMatch", reason=None, route_filter_mode=None):
    return {
        "OracleMatchStatus": status,
        "OracleMatchLevel": level,
        "OracleDirBasis": basis,
        "QC_OracleNoMatch": 1 if status in ("NoOracleMatch", "MissingLinkID", "OracleDisabled") else 0,
        "QC_OracleAmbiguous": 1 if str(status).startswith("Ambiguous") else 0,
        "QC_RouteMismatch": 0,
        "DebugRouteNameInput": route_name_from_context(context),
        "DebugRouteFilterMode": route_filter_mode or status,
        "DebugRouteFilterApplied": 0,
        "DebugRouteFilterMatched": 0,
        "DebugOracleCandidateCount": 0,
        "DebugOraclePostRouteCount": 0,
        "DebugOracleClusterCount": 0,
        "DebugOracleTopScore": None,
        "DebugBestMeasureDiff": None,
        "DebugBestSequence": None,
        "DebugMeasureGuardRejected": 0,
        "DebugAmbiguityReason": reason or status,
        "DebugOracleTopRouteMatch": 0,
    }

def _oracle_measure_guard_threshold(context):
    strict = float(getattr(cfg, "ORACLE_MEASURE_MATCH_TOL", ORACLE_MEASURE_MATCH_TOL))
    base = float(getattr(cfg, "ORACLE_MEASURE_GUARD_TOL", max(strict * 3.0, strict + 75.0)))
    delta = normalize_measure_value(context.get("Delta_M"))
    flow_role = str(context.get("Flow_Role") or "").strip().lower()
    if flow_role == "atsignal" or (delta is not None and abs(delta) <= max(strict, MIDPOINT_AT_SIGNAL_TOL_FT)):
        return max(strict * 1.5, strict + 25.0)
    return base

def _oracle_cluster_candidates(df):
    if df is None or len(df) == 0:
        return df
    tmp = df.copy()
    tmp["__route_name_norm"] = tmp["RTE_NM"].map(normalize_route_name)
    tmp["__begin_norm"] = tmp["BEGINNODE"].map(normalize_node_value)
    tmp["__end_norm"] = tmp["ENDNODE"].map(normalize_node_value)
    tmp["__route_mp_round"] = pd.to_numeric(tmp["ROUTEMILEPOINT"], errors="coerce").round(3)
    tmp["__linkseq_num"] = pd.to_numeric(tmp["LINKSEQUENCE"], errors="coerce")
    group_cols = ["TMSLINKID", "__route_name_norm", "__begin_norm", "__end_norm", "__linkseq_num", "__route_mp_round"]
    agg_map = {
        "RTE_NM": "first",
        "BEGINNODE": "first",
        "ENDNODE": "first",
        "LINKSEQUENCE": "first",
        "ROUTEMILEPOINT": "first",
        "AVERAGEDAILYTRAFFIC": "first",
    }
    for optional_col in ["BEGINOFFSET", "ENDOFFSET", "RURALURBANDESIGNATION"]:
        if optional_col in tmp.columns:
            agg_map[optional_col] = "first"
    clustered = tmp.groupby(group_cols, dropna=False, as_index=False).agg(agg_map)
    counts = tmp.groupby(group_cols, dropna=False).size().reset_index(name="__cluster_size")
    clustered = clustered.merge(counts, on=group_cols, how="left")
    return clustered

def _oracle_consensus_node(df):
    if df is None or len(df) == 0:
        return None
    counts = {}
    for col in ["BEGINNODE", "ENDNODE"]:
        if col not in df.columns:
            continue
        for v in df[col].map(normalize_node_value).tolist():
            if v:
                counts[v] = counts.get(v, 0) + 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]

def _oracle_pick_best_candidate(candidates_df, context, oracle_ref=None):
    if candidates_df is None or len(candidates_df) == 0:
        return _oracle_result_defaults(context, status="NoOracleMatch", level="NoOracleMatch", basis="NoOracleMatch", reason="NoCandidates", route_filter_mode="NoCandidates")

    raw_df = candidates_df.copy()
    linkid = normalize_linkid_value(context.get("LinkID_Norm"))
    route_nm = route_name_from_context(context)
    from_node = normalize_node_value(context.get("FromNode_Norm"))
    to_node = normalize_node_value(context.get("ToNode_Norm"))
    intersection_node = normalize_node_value(context.get("IntersectionNode"))
    flow_role = str(context.get("Flow_Role") or "").strip()
    side_code = str(context.get("Side_Code") or "").strip()
    delta_m = normalize_measure_value(context.get("Delta_M"))
    ref_m = normalize_measure_value(context.get("Signal_M"))
    if ref_m is None:
        ref_m = normalize_measure_value(context.get("SegMid_M"))

    route_filter_applied = 0
    route_filter_matched = 0
    route_filter_mode = "RouteBlankBypassed" if not route_nm else "RouteNameProvided"
    route_mismatch_penalty = 0.0

    df = raw_df.copy()
    if route_nm:
        route_filter_applied = 1
        route_df = df[df["RTE_NM"].map(normalize_route_name) == route_nm]
        if len(route_df) > 0:
            df = route_df.copy()
            route_filter_matched = 1
            route_filter_mode = "ExactRouteMatch"
        else:
            route_filter_mode = "NoExactRouteMatchSoftPenalty"
            route_mismatch_penalty = float(getattr(cfg, "ORACLE_ROUTE_MISMATCH_PENALTY", 40.0))

    if len(df) == 0:
        out = _oracle_result_defaults(context, status="NoOracleMatch", level="NoOracleMatch", basis="NoOracleMatch", reason="NoCandidatesAfterRouteFilter", route_filter_mode=route_filter_mode)
        out.update({
            "DebugRouteFilterApplied": route_filter_applied,
            "DebugRouteFilterMatched": route_filter_matched,
            "DebugOracleCandidateCount": int(len(raw_df)),
        })
        return out

    guidance = _oracle_gis_key_guidance(context, oracle_ref)
    expected_flow = str((guidance or {}).get("expected_flow_role") or "").strip()
    guidance_intersection = normalize_node_value((guidance or {}).get("intersection_node"))
    if guidance_intersection and not intersection_node:
        intersection_node = guidance_intersection

    clustered_df = _oracle_cluster_candidates(df)
    duplicate_rows_removed = max(int(len(df)) - int(len(clustered_df)), 0)

    work = clustered_df.copy()
    work["__begin_norm"] = work["BEGINNODE"].map(normalize_node_value)
    work["__end_norm"] = work["ENDNODE"].map(normalize_node_value)
    work["__route_name_norm"] = work["RTE_NM"].map(normalize_route_name)
    work["__measure_diff"] = (pd.to_numeric(work["ROUTEMILEPOINT"], errors="coerce") - ref_m).abs() if ref_m is not None else 999999.0
    work["__sequence_num"] = pd.to_numeric(work["LINKSEQUENCE"], errors="coerce")
    work["__node_exact"] = ((work["__begin_norm"] == from_node) & (work["__end_norm"] == to_node)).astype(int) if (from_node and to_node) else 0
    work["__node_reversed"] = ((work["__begin_norm"] == to_node) & (work["__end_norm"] == from_node)).astype(int) if (from_node and to_node) else 0
    work["__node_partial"] = (((work["__begin_norm"] == from_node) | (work["__end_norm"] == from_node) | (work["__begin_norm"] == to_node) | (work["__end_norm"] == to_node))).astype(int) if (from_node or to_node) else 0
    work["__intersection_match"] = (((work["__begin_norm"] == intersection_node) | (work["__end_norm"] == intersection_node))).astype(int) if intersection_node else 0
    work["__flow_consistent"] = 0
    if intersection_node and expected_flow.lower() == "upstream":
        work["__flow_consistent"] = (work["__end_norm"] == intersection_node).astype(int)
    elif intersection_node and expected_flow.lower() == "downstream":
        work["__flow_consistent"] = (work["__begin_norm"] == intersection_node).astype(int)
    work["__route_match"] = (work["__route_name_norm"] == route_nm).astype(int) if route_nm else 0
    work["__node_family_score"] = (work["__node_exact"] * 4) + (work["__node_reversed"] * 3) + (work["__flow_consistent"] * 3) + (work["__intersection_match"] * 2) + (work["__node_partial"] * 1)

    family_consensus = _oracle_consensus_node(work)
    work["__consensus_match"] = (((work["__begin_norm"] == family_consensus) | (work["__end_norm"] == family_consensus))).astype(int) if family_consensus else 0

    measure_guard = _oracle_measure_guard_threshold(context) if ref_m is not None else None
    work["__measure_guard_reject"] = ((work["__measure_diff"] > measure_guard).astype(int) if measure_guard is not None else 0)

    measure_tol = float(getattr(cfg, "ORACLE_MEASURE_MATCH_TOL", ORACLE_MEASURE_MATCH_TOL))
    at_signal_like = str(flow_role).lower() == "atsignal" or str(side_code).lower() == "atsignal" or (delta_m is not None and abs(delta_m) <= max(measure_tol, MIDPOINT_AT_SIGNAL_TOL_FT))

    work["__score"] = (
        (work["__route_match"] * 10)
        + (work["__node_exact"] * 16)
        + (work["__node_reversed"] * 12)
        + (work["__flow_consistent"] * 10)
        + (work["__intersection_match"] * 8)
        + (work["__node_partial"] * 5)
        + (work["__consensus_match"] * 2)
        + (pd.to_numeric(work.get("__cluster_size", 1), errors="coerce").fillna(1).clip(upper=5) * 0.25)
    )
    if route_nm and route_mismatch_penalty:
        work.loc[work["__route_match"] == 0, "__score"] = work.loc[work["__route_match"] == 0, "__score"] - route_mismatch_penalty

    if ref_m is not None:
        measure_bonus = (measure_tol - work["__measure_diff"].clip(upper=measure_tol)) / max(measure_tol, 1.0)
        work["__score"] = work["__score"] + (measure_bonus * (20.0 if at_signal_like else 12.0))
        if measure_guard is not None:
            work.loc[work["__measure_guard_reject"] == 1, "__score"] = work.loc[work["__measure_guard_reject"] == 1, "__score"] - (60.0 if at_signal_like else 35.0)

    sort_cols = ["__measure_guard_reject", "__node_family_score", "__measure_diff", "__sequence_num", "ROUTEMILEPOINT"]
    ascending = [True, False, True, True, True]
    if not at_signal_like:
        sort_cols = ["__measure_guard_reject", "__node_family_score", "__measure_diff", "__sequence_num", "ROUTEMILEPOINT", "__score"]
        ascending = [True, False, True, True, True, False]
    work = work.sort_values(sort_cols, ascending=ascending, kind="mergesort", na_position="last")

    valid = work[work["__measure_guard_reject"] == 0].copy()
    measure_guard_rejected = int(work["__measure_guard_reject"].sum())
    if ref_m is not None and len(valid) == 0:
        fallback = work.iloc[0]
        out = _oracle_result_defaults(context, status="AmbiguousFarFromMeasure", level="NodeBridgeFar", basis="MeasureGuard", reason="AmbiguousFarFromMeasure", route_filter_mode=route_filter_mode)
        out.update({
            "OracleTMSLINKID": fallback.get("TMSLINKID", linkid),
            "OracleRouteNm": fallback.get("RTE_NM"),
            "OracleBeginNode": fallback.get("BEGINNODE"),
            "OracleEndNode": fallback.get("ENDNODE"),
            "OracleLinkSequence": fallback.get("LINKSEQUENCE"),
            "OracleRouteMP": fallback.get("ROUTEMILEPOINT"),
            "OracleAADT": fallback.get("AVERAGEDAILYTRAFFIC"),
            "DebugRouteFilterApplied": route_filter_applied,
            "DebugRouteFilterMatched": route_filter_matched,
            "DebugOracleCandidateCount": int(len(raw_df)),
            "DebugOraclePostRouteCount": int(len(df)),
            "DebugOracleClusterCount": int(len(clustered_df)),
            "DebugOracleTopScore": float(fallback.get("__score", 0.0)),
            "DebugBestMeasureDiff": None if pd.isna(fallback.get("__measure_diff")) else float(fallback.get("__measure_diff", 0.0)),
            "DebugBestSequence": None if pd.isna(fallback.get("__sequence_num")) else int(float(fallback.get("__sequence_num"))),
            "DebugMeasureGuardRejected": measure_guard_rejected,
            "DebugOracleTopRouteMatch": int(fallback.get("__route_match", 0)),
        })
        if guidance is not None:
            out["OracleGISKeyFlowRole"] = guidance.get("expected_flow_role")
            out["OracleGISKeyIntersectionNode"] = guidance.get("intersection_node")
        return out

    scored = valid if len(valid) > 0 else work
    top = scored.iloc[0]

    same_family = scored[scored["__node_family_score"] == top["__node_family_score"]].copy()
    best_measure = float(top.get("__measure_diff", 999999.0)) if not pd.isna(top.get("__measure_diff")) else 999999.0
    close_measure = same_family[same_family["__measure_diff"].sub(best_measure).abs() <= 1e-9].copy()
    if len(close_measure) == 0:
        close_measure = same_family.head(1).copy()

    ambiguous_reason = None
    ambiguous = False
    if len(close_measure) > 1:
        ambiguous = True
        if duplicate_rows_removed > 0 and len(clustered_df) == 1:
            ambiguous_reason = "AmbiguousDuplicateOracleRows"
        elif ref_m is not None and best_measure > measure_tol:
            ambiguous_reason = "AmbiguousFarFromMeasure"
        elif ref_m is not None:
            ambiguous_reason = "AmbiguousMeasureTie"
        elif float(top.get("__node_family_score", 0)) > 0:
            ambiguous_reason = "AmbiguousNodeCluster"
        else:
            ambiguous_reason = "AmbiguousNoGuidance"

    if float(top.get("__node_family_score", 0)) <= 0 and ref_m is None:
        ambiguous = True
        ambiguous_reason = ambiguous_reason or "AmbiguousNoGuidance"

    if at_signal_like and ref_m is not None and len(close_measure) == 1 and best_measure <= max(measure_tol, MIDPOINT_AT_SIGNAL_TOL_FT):
        ambiguous = False

    if ambiguous:
        status = ambiguous_reason or "Ambiguous"
    else:
        status = "MatchedWithRoutePenalty" if route_nm and int(top.get("__route_match", 0)) == 0 else "Matched"

    if not ambiguous:
        if at_signal_like and ref_m is not None and best_measure <= max(measure_tol, MIDPOINT_AT_SIGNAL_TOL_FT):
            level = "AtSignalMeasureResolved"
            basis = "MeasurePrimary"
        elif float(top.get("__node_family_score", 0)) > 0 and ref_m is not None and best_measure <= measure_tol:
            if int(top.get("__consensus_match", 0)) == 1 and int(top.get("__intersection_match", 0)) == 1:
                level = "NodeConsensusMeasureResolved"
            else:
                level = "NodeAndMeasureResolved"
            basis = "NodeMeasure"
        elif float(top.get("__node_family_score", 0)) > 0:
            level = "NodeConsensusMeasureResolved"
            basis = "NodeMeasure"
        elif ref_m is not None and best_measure <= measure_tol:
            level = "RouteAndMeasure"
            basis = "RouteMeasure"
        elif ORACLE_SEQUENCE_FALLBACK_ENABLED:
            level = "RouteAndSequence" if route_nm else "LinkOnlyAmbiguous"
            basis = "RouteOrder"
        else:
            level = "LinkOnlyAmbiguous"
            basis = "LinkOnlyAmbiguous"
    else:
        if ambiguous_reason == "AmbiguousFarFromMeasure":
            level = "NodeBridgeFar"
            basis = "MeasureGuard"
        else:
            level = "NodeBridgeAmbiguous" if float(top.get("__node_family_score", 0)) > 0 else "LinkOnlyAmbiguous"
            basis = "NodeBridge" if float(top.get("__node_family_score", 0)) > 0 else "LinkOnlyAmbiguous"

    out = {
        "OracleMatchStatus": status,
        "OracleMatchLevel": level,
        "OracleTMSLINKID": top.get("TMSLINKID", linkid),
        "OracleRouteNm": top.get("RTE_NM"),
        "OracleBeginNode": top.get("BEGINNODE"),
        "OracleEndNode": top.get("ENDNODE"),
        "OracleLinkSequence": top.get("LINKSEQUENCE"),
        "OracleRouteMP": top.get("ROUTEMILEPOINT"),
        "OracleAADT": top.get("AVERAGEDAILYTRAFFIC"),
        "OracleDirBasis": basis,
        "QC_OracleNoMatch": 0,
        "QC_OracleAmbiguous": 1 if ambiguous else 0,
        "QC_RouteMismatch": 0,
        "DebugRouteNameInput": route_nm,
        "DebugRouteFilterMode": route_filter_mode,
        "DebugRouteFilterApplied": route_filter_applied,
        "DebugRouteFilterMatched": route_filter_matched,
        "DebugOracleCandidateCount": int(len(raw_df)),
        "DebugOraclePostRouteCount": int(len(df)),
        "DebugOracleClusterCount": int(len(clustered_df)),
        "DebugOracleTopScore": float(top.get("__score", 0.0)),
        "DebugBestMeasureDiff": None if pd.isna(top.get("__measure_diff")) else float(top.get("__measure_diff", 0.0)),
        "DebugBestSequence": None if pd.isna(top.get("__sequence_num")) else int(float(top.get("__sequence_num"))),
        "DebugMeasureGuardRejected": measure_guard_rejected,
        "DebugAmbiguityReason": ambiguous_reason or ("DuplicateRowsCollapsed" if duplicate_rows_removed > 0 else "Resolved"),
        "DebugOracleTopRouteMatch": int(top.get("__route_match", 0)),
    }
    if guidance is not None:
        out["OracleGISKeyFlowRole"] = guidance.get("expected_flow_role")
        out["OracleGISKeyIntersectionNode"] = guidance.get("intersection_node")
    return out

def resolve_oracle_context(context, oracle_ref):
    if not oracle_ref:
        return _oracle_result_defaults(context, status="OracleDisabled", level="OracleDisabled", basis="OracleDisabled", reason="OracleDisabled", route_filter_mode="OracleDisabled")

    linkid = normalize_linkid_value(context.get("LinkID_Norm"))
    if not linkid:
        return _oracle_result_defaults(context, status="MissingLinkID", level="NoOracleMatch", basis="MissingLinkID", reason="MissingLinkID", route_filter_mode="MissingLinkID")

    route_nm = route_name_from_context(context)
    candidates = None
    if route_nm and (linkid, route_nm) in oracle_ref["by_link_route"]:
        candidates = oracle_ref["by_link_route"][(linkid, route_nm)].copy()
    else:
        candidates = oracle_ref["by_link"].get(linkid)
    return _oracle_pick_best_candidate(candidates, context, oracle_ref=oracle_ref)

def project_point_onto_line(line_geom, point_geom):
    if line_geom is None or point_geom is None:
        return None
    try:
        return float(line_geom.project(point_geom))
    except Exception:
        return None

def has_valid_midpoint_xy(row_obj):
    try:
        x = getattr(row_obj, "Mid_X", None)
        y = getattr(row_obj, "Mid_Y", None)
        if x is None or y is None:
            return False
        if pd is not None and (pd.isna(x) or pd.isna(y)):
            return False
        return True
    except Exception:
        return False

def build_parent_line_reference(parent_roads_gdf):
    if parent_roads_gdf.empty:
        return {}

    group_cols = ["ParentRoadOID"]
    for c in ["LinkID_Norm", "RouteID_Norm", "RouteNm_Norm", "DirCode_Norm", "FromNode_Norm", "ToNode_Norm"]:
        if c in parent_roads_gdf.columns and c not in group_cols:
            group_cols.append(c)

    attr_by_parent = (
        parent_roads_gdf[group_cols]
        .drop_duplicates(subset=["ParentRoadOID"])
        .set_index("ParentRoadOID")
        .to_dict(orient="index")
    )

    if parent_roads_gdf["ParentRoadOID"].is_unique:
        source_rows = parent_roads_gdf[["ParentRoadOID", "geometry"]].itertuples(index=False)
    else:
        source_rows = parent_roads_gdf.dissolve(by="ParentRoadOID", as_index=False)[["ParentRoadOID", "geometry"]].itertuples(index=False)

    ref = {}
    for r in source_rows:
        pid = r.ParentRoadOID
        ref[pid] = {
            "geometry": r.geometry,
            "attrs": attr_by_parent.get(pid, {})
        }
    return ref

def infer_flow_role(side_code, dir_code=None, oracle_ctx=None, delta_m=None):
    if side_code == "AtSignal":
        return "AtSignal", "MeasureTolerance"

    oracle_ctx = oracle_ctx or {}
    begin_node = normalize_node_value(oracle_ctx.get("OracleBeginNode"))
    end_node = normalize_node_value(oracle_ctx.get("OracleEndNode"))
    intersection_node = normalize_node_value(oracle_ctx.get("IntersectionNode"))
    dir_basis = oracle_ctx.get("OracleDirBasis")

    if intersection_node:
        if end_node and end_node == intersection_node:
            return "Upstream", "OracleNodeTopology"
        if begin_node and begin_node == intersection_node:
            return "Downstream", "OracleNodeTopology"

    if dir_basis in ("RouteMeasure", "RouteOrder") and delta_m is not None:
        try:
            d = float(delta_m)
            if d < (-1.0 * MIDPOINT_AT_SIGNAL_TOL_FT):
                return "Upstream", f"Oracle{dir_basis}"
            if d > MIDPOINT_AT_SIGNAL_TOL_FT:
                return "Downstream", f"Oracle{dir_basis}"
        except Exception:
            pass

    trusted = normalize_dir_text(dir_code)
    if trusted in ("NB", "EB", "POSITIVE", "WITH", "DIGITIZED"):
        if side_code == "Positive":
            return "Downstream", "TrustedGISPositiveDirection"
        if side_code == "Negative":
            return "Upstream", "TrustedGISPositiveDirection"

    if trusted in ("SB", "WB", "NEGATIVE", "AGAINST"):
        if side_code == "Positive":
            return "Upstream", "TrustedGISNegativeDirection"
        if side_code == "Negative":
            return "Downstream", "TrustedGISNegativeDirection"

    return "Unknown", "NoReliableDirection"

def nearest_signal_measure_table(signals_gdf, parent_ref, oracle_ref=None):
    rows = []
    geom_cache = {pid: payload.get("geometry") for pid, payload in parent_ref.items()}
    attr_cache = {pid: payload.get("attrs", {}) for pid, payload in parent_ref.items()}

    for r in signals_gdf.itertuples(index=False):
        pid = getattr(r, "ParentRoadOID", None)
        line = geom_cache.get(pid)
        if line is None:
            continue

        attrs = attr_cache.get(pid, {})
        signal_m = project_point_onto_line(line, r.geometry)
        base = {
            "SignalOID": getattr(r, "SignalOID", None),
            "ParentRoadOID": pid,
            "Signal_M": signal_m,
            "LinkID_Norm": getattr(r, "LinkID_Norm", attrs.get("LinkID_Norm")),
            "RouteID_Norm": getattr(r, "RouteID_Norm", attrs.get("RouteID_Norm")),
            "RouteNm_Norm": getattr(r, "RouteNm_Norm", attrs.get("RouteNm_Norm")),
            "DirCode_Norm": getattr(r, "DirCode_Norm", attrs.get("DirCode_Norm")),
            "FromNode_Norm": getattr(r, "FromNode_Norm", attrs.get("FromNode_Norm")),
            "ToNode_Norm": getattr(r, "ToNode_Norm", attrs.get("ToNode_Norm")),
        }
        intersection_node, intersection_basis = resolve_intersection_node(base, oracle_ref=oracle_ref)
        base["IntersectionNode"] = intersection_node
        base["IntersectionNodeBasis"] = intersection_basis
        base.update(resolve_oracle_context(base, oracle_ref))
        rows.append(base)
    return pd.DataFrame(rows)

def label_segments_direction(segments_gdf, signal_m_df, parent_ref, oracle_ref=None):
    columns = [
        "SegOID", "SegStableID", "SignalOID", "ParentRoadOID", "LinkID_Norm", "RouteID_Norm", "RouteNm_Norm",
        "FromNode_Norm", "ToNode_Norm", "Signal_M", "SegMid_M", "Delta_M", "Side_Code",
        "IntersectionNode", "IntersectionNodeBasis",
        "Flow_Role", "DirSource", "OracleMatchStatus", "OracleMatchLevel", "OracleTMSLINKID",
        "OracleRouteNm", "OracleBeginNode", "OracleEndNode", "OracleLinkSequence", "OracleRouteMP",
        "OracleAADT", "OracleDirBasis", "QC_OracleNoMatch", "QC_OracleAmbiguous", "QC_NodeMissing",
        "QC_RouteMismatch", "AADT_Source", "QC_AADTConflict",
        "DebugRouteNameInput", "DebugRouteFilterMode", "DebugRouteFilterApplied", "DebugRouteFilterMatched",
        "DebugOracleCandidateCount", "DebugOraclePostRouteCount", "DebugOracleClusterCount", "DebugOracleTopScore",
        "DebugBestMeasureDiff", "DebugBestSequence", "DebugMeasureGuardRejected", "DebugAmbiguityReason", "DebugOracleTopRouteMatch"
    ]
    if segments_gdf.empty:
        return pd.DataFrame(columns=columns)

    from shapely.geometry import Point

    parent_geom = {pid: payload.get("geometry") for pid, payload in parent_ref.items()}
    sig_map = {r.SignalOID: r._asdict() for r in signal_m_df.drop_duplicates(subset=["SignalOID"]).itertuples(index=False)}
    has_midxy = {"Mid_X", "Mid_Y"}.issubset(set(segments_gdf.columns))

    out_rows = []
    for r in segments_gdf.itertuples(index=False):
        rec = r._asdict()
        seg_oid = rec.get("SegOID")
        pid = rec.get("ParentRoadOID")
        sid = rec.get("SignalOID")
        line = parent_geom.get(pid)
        sig_info = sig_map.get(sid)
        sig_m = None if sig_info is None else sig_info.get("Signal_M")

        base = {
            "SegOID": seg_oid,
            "SignalOID": sid,
            "ParentRoadOID": pid,
            "LinkID_Norm": rec.get("LinkID_Norm"),
            "RouteID_Norm": rec.get("RouteID_Norm"),
            "RouteNm_Norm": rec.get("RouteNm_Norm"),
            "FromNode_Norm": rec.get("FromNode_Norm"),
            "ToNode_Norm": rec.get("ToNode_Norm"),
        }

        if line is None or sig_info is None or sig_m is None:
            base.update({
                "Signal_M": None,
                "SegMid_M": None,
                "Delta_M": None,
                "Side_Code": "Unknown",
                "Flow_Role": "Unknown",
                "DirSource": "MissingParentOrSignal",
                "OracleMatchStatus": "NoOracleMatch",
                "OracleMatchLevel": "NoOracleMatch",
                "OracleDirBasis": "MissingParentOrSignal",
                "QC_OracleNoMatch": 1,
                "QC_OracleAmbiguous": 0,
                "QC_NodeMissing": 1,
                "QC_RouteMismatch": 0,
                "AADT_Source": "GIS",
                "QC_AADTConflict": 0,
                "DebugRouteNameInput": route_name_from_context(base),
                "DebugRouteFilterMode": "MissingParentOrSignal",
                "DebugRouteFilterApplied": 0,
                "DebugRouteFilterMatched": 0,
                "DebugOracleCandidateCount": 0,
                "DebugOraclePostRouteCount": 0,
                "DebugOracleClusterCount": 0,
                "DebugOracleTopScore": None,
                "DebugBestMeasureDiff": None,
                "DebugBestSequence": None,
                "DebugMeasureGuardRejected": 0,
                "DebugAmbiguityReason": "MissingParentOrSignal",
                "DebugOracleTopRouteMatch": 0,
            })
            out_rows.append(base)
            continue

        try:
            if has_midxy and getattr(r, "Mid_X", None) not in (None, "") and getattr(r, "Mid_Y", None) not in (None, ""):
                midpoint = Point(float(r.Mid_X), float(r.Mid_Y))
            else:
                midpoint = r.geometry.interpolate(0.5, normalized=True)
        except Exception:
            midpoint = None

        seg_m = project_point_onto_line(line, midpoint)
        delta = None if seg_m is None else float(seg_m) - float(sig_m)
        side = classify_side_by_measure(delta, MIDPOINT_AT_SIGNAL_TOL_FT)

        context = dict(base)
        context["Signal_M"] = sig_m
        context["SegMid_M"] = seg_m
        context["Delta_M"] = delta
        intersection_node, intersection_basis = resolve_intersection_node(context, oracle_ref=oracle_ref)
        context["IntersectionNode"] = intersection_node
        context["IntersectionNodeBasis"] = intersection_basis
        oracle_ctx = resolve_oracle_context(context, oracle_ref)
        oracle_ctx["IntersectionNode"] = intersection_node
        oracle_ctx["IntersectionNodeBasis"] = intersection_basis
        flow_role, source = infer_flow_role(side_code=side, dir_code=sig_info.get("DirCode_Norm"), oracle_ctx=oracle_ctx, delta_m=delta)

        gis_aadt = rec.get("AADT")
        oracle_aadt = oracle_ctx.get("OracleAADT")
        qc_conflict = 0
        aadt_source = "GIS"
        if gis_aadt not in (None, "", 0) and oracle_aadt not in (None, ""):
            try:
                if int(float(gis_aadt)) != int(float(oracle_aadt)):
                    qc_conflict = 1
            except Exception:
                pass
        if gis_aadt in (None, "", 0) and USE_ORACLE_AADT and oracle_aadt not in (None, ""):
            aadt_source = "Oracle"
        elif gis_aadt in (None, "", 0):
            aadt_source = "SpatialFallback"

        base.update({
            "Signal_M": sig_m,
            "SegMid_M": seg_m,
            "Delta_M": delta,
            "Side_Code": side,
            "IntersectionNode": intersection_node,
            "IntersectionNodeBasis": intersection_basis,
            "Flow_Role": flow_role,
            "DirSource": source,
            "AADT_Source": aadt_source,
            "QC_AADTConflict": qc_conflict,
        })
        base.update(oracle_ctx)
        base["QC_NodeMissing"] = 0 if any([
            normalize_node_value(base.get("FromNode_Norm")),
            normalize_node_value(base.get("ToNode_Norm")),
            normalize_node_value(base.get("IntersectionNode")),
            normalize_node_value(base.get("OracleBeginNode")),
            normalize_node_value(base.get("OracleEndNode")),
        ]) else 1
        out_rows.append(base)

    return pd.DataFrame(out_rows, columns=columns)

def label_crashes_direction(crashes_gdf, segments_gdf, signal_m_df, parent_ref):
    if crashes_gdf.empty:
        return pd.DataFrame(columns=[
            "CrashOID", "SegOID", "SignalOID", "Crash_M", "Delta_M",
            "CrashSide", "CrashFlowRole", "DirSource", "CrashType",
            "OracleMatchLevel", "OracleDirBasis", "IntersectionNode", "IntersectionNodeBasis"
        ])

    parent_geom = {pid: payload.get("geometry") for pid, payload in parent_ref.items()}
    sig_map = {r.SignalOID: r._asdict() for r in signal_m_df.drop_duplicates(subset=["SignalOID"]).itertuples(index=False)}
    seg_subset_cols = [c for c in ["SegOID", "ParentRoadOID", "SignalOID", "OracleMatchLevel", "OracleDirBasis", "OracleBeginNode", "OracleEndNode", "IntersectionNode", "IntersectionNodeBasis", "DirSource", "Flow_Role"] if c in segments_gdf.columns]
    seg_map = {r.SegOID: r._asdict() for r in segments_gdf[seg_subset_cols].drop_duplicates(subset=["SegOID"]).itertuples(index=False)}

    coll_upper = {x.upper() for x in CANDIDATE_FIELDS["collision_type"]}
    coll_col = next((c for c in crashes_gdf.columns if c.upper() in coll_upper), None)

    rows = []
    for r in crashes_gdf.itertuples(index=False):
        crash_oid = getattr(r, "CrashOID", None)
        seg_oid = getattr(r, "SegOID", None)
        seg_info = seg_map.get(seg_oid)
        pid = None if seg_info is None else seg_info.get("ParentRoadOID")
        sid = None if seg_info is None else seg_info.get("SignalOID")

        sig_info = sig_map.get(sid)
        line = parent_geom.get(pid)
        sig_m = None if sig_info is None else sig_info.get("Signal_M")
        crash_type = getattr(r, coll_col, "Unknown") if coll_col else "Unknown"

        if line is None or sid is None or sig_m is None:
            rows.append({
                "CrashOID": crash_oid,
                "SegOID": seg_oid,
                "SignalOID": sid,
                "Crash_M": None,
                "Delta_M": None,
                "CrashSide": "Unknown",
                "CrashFlowRole": "Unknown",
                "DirSource": "MissingParentOrSignal",
                "CrashType": crash_type,
                "OracleMatchLevel": None,
                "OracleDirBasis": None,
                "IntersectionNode": None,
                "IntersectionNodeBasis": None,
            })
            continue

        crash_m = project_point_onto_line(line, r.geometry)
        delta = None if crash_m is None else float(crash_m) - float(sig_m)
        side = classify_side_by_measure(delta, CRASH_AT_SIGNAL_TOL_FT)
        oracle_ctx = dict(sig_info)
        if seg_info:
            oracle_ctx.update(seg_info)
        flow_role, source = infer_flow_role(side_code=side, dir_code=sig_info.get("DirCode_Norm"), oracle_ctx=oracle_ctx, delta_m=delta)
        rows.append({
            "CrashOID": crash_oid,
            "SegOID": seg_oid,
            "SignalOID": sid,
            "Crash_M": crash_m,
            "Delta_M": delta,
            "CrashSide": side,
            "CrashFlowRole": flow_role,
            "DirSource": source,
            "CrashType": crash_type,
            "OracleMatchLevel": oracle_ctx.get("OracleMatchLevel"),
            "OracleDirBasis": oracle_ctx.get("OracleDirBasis"),
            "IntersectionNode": oracle_ctx.get("IntersectionNode"),
            "IntersectionNodeBasis": oracle_ctx.get("IntersectionNodeBasis"),
        })

    return pd.DataFrame(rows)

def summarize_access_by_segment(access_assigned_gdf):
    """
    Access counts are now summarized natively in ArcPy via Frequency_analysis during
    write-back. This helper is intentionally bypassed to avoid split logic.
    """
    if pd is None:
        return None
    return pd.DataFrame(columns=["SegOID", "Cnt_Access"])

def summarize_crashes_by_segment(crash_dir_df):
    if crash_dir_df.empty:
        return pd.DataFrame(columns=["SegOID", "Cnt_Crash_Total", "Cnt_Crash_Up", "Cnt_Crash_Down", "Cnt_Crash_At"])

    base = crash_dir_df.groupby("SegOID").size().reset_index(name="Cnt_Crash_Total")

    dir_piv = (
        crash_dir_df.pivot_table(index="SegOID", columns="CrashFlowRole", values="CrashOID", aggfunc="count", fill_value=0)
        .reset_index()
    )
    dir_piv.columns = [str(c) for c in dir_piv.columns]
    rename = {
        "Upstream": "Cnt_Crash_Up",
        "Downstream": "Cnt_Crash_Down",
        "AtSignal": "Cnt_Crash_At",
        "Unknown": "Cnt_Crash_Unknown",
    }
    dir_piv = dir_piv.rename(columns=rename)

    crash_dir_df["CrashTypeSafe"] = crash_dir_df["CrashType"].fillna("Unknown").astype(str).map(safe_field_name)
    crash_dir_df["TypeDir"] = crash_dir_df["CrashFlowRole"].fillna("Unknown").astype(str) + "_" + crash_dir_df["CrashTypeSafe"]
    type_dir = (
        crash_dir_df.pivot_table(index="SegOID", columns="TypeDir", values="CrashOID", aggfunc="count", fill_value=0)
        .reset_index()
    )

    new_cols = []
    for c in type_dir.columns:
        if c == "SegOID":
            new_cols.append(c)
        else:
            new_cols.append(f"Cnt_{safe_field_name(str(c), max_len=50)}")
    type_dir.columns = new_cols

    out = base.merge(dir_piv, on="SegOID", how="left").merge(type_dir, on="SegOID", how="left")
    for c in out.columns:
        if c != "SegOID":
            out[c] = out[c].fillna(0).astype(int)
    return out

def run_geopandas_directional_pipeline():
    if not cfg.USE_GEOPANDAS:
        msg("    -> GeoPandas disabled; skipping directional pipeline")
        return None

    if not geopandas_pipeline_enabled():
        msg("    ! GeoPandas/pandas unavailable; skipping directional pipeline")
        return None

    msg("    -> Running GeoPandas directional pipeline")
    oracle_ref = load_oracle_reference_data()

    t = time.time()
    segments_gdf = read_fc_to_gdf(STAGED["seg_clean"], field_names=EXPORT_FIELDS["segments"])
    signals_gdf = read_fc_to_gdf(STAGED["signals_speed"], field_names=EXPORT_FIELDS["signals"])
    crashes_gdf = read_fc_to_gdf(STAGED["crash_assigned"], field_names=EXPORT_FIELDS["crashes"])
    parent_roads_gdf = read_fc_to_gdf(STAGED["roads_study"], field_names=EXPORT_FIELDS["parent_roads"])
    log_phase_time("GeoPandas - layer reads", t)

    t = time.time()
    parent_ref = build_parent_line_reference(parent_roads_gdf)
    log_phase_time("GeoPandas - parent reference creation", t)

    t = time.time()
    signal_m_df = nearest_signal_measure_table(signals_gdf, parent_ref, oracle_ref)
    log_phase_time("GeoPandas - nearest-signal measure creation", t)

    t = time.time()
    seg_dir_df = label_segments_direction(segments_gdf, signal_m_df, parent_ref, oracle_ref)
    log_phase_time("GeoPandas - segment labeling", t)

    t = time.time()
    crash_dir_df = label_crashes_direction(crashes_gdf, seg_dir_df, signal_m_df, parent_ref)
    log_phase_time("GeoPandas - crash labeling", t)

    t = time.time()
    seg_summary = summarize_crashes_by_segment(crash_dir_df)
    seg_summary = seg_dir_df.merge(seg_summary, on="SegOID", how="left")
    log_phase_time("GeoPandas - crash summarization", t)

    qc_rows = []
    if not seg_dir_df.empty:
        for val, n in seg_dir_df["Flow_Role"].fillna("Unknown").value_counts().items():
            qc_rows.append({"QC_Type": "SegmentFlowRole", "QC_Value": str(val), "QC_Count": int(n)})
        for val, n in seg_dir_df["DirSource"].fillna("Unknown").value_counts().items():
            qc_rows.append({"QC_Type": "DirSource", "QC_Value": str(val), "QC_Count": int(n)})
        if "OracleMatchStatus" in seg_dir_df.columns:
            for val, n in seg_dir_df["OracleMatchStatus"].fillna("Unknown").value_counts().items():
                qc_rows.append({"QC_Type": "OracleMatchStatus", "QC_Value": str(val), "QC_Count": int(n)})
        if "OracleMatchLevel" in seg_dir_df.columns:
            for val, n in seg_dir_df["OracleMatchLevel"].fillna("Unknown").value_counts().items():
                qc_rows.append({"QC_Type": "OracleMatchLevel", "QC_Value": str(val), "QC_Count": int(n)})
        if "DebugRouteFilterMode" in seg_dir_df.columns:
            for val, n in seg_dir_df["DebugRouteFilterMode"].fillna("Unknown").value_counts().items():
                qc_rows.append({"QC_Type": "DebugRouteFilterMode", "QC_Value": str(val), "QC_Count": int(n)})
        if "DebugOracleTopRouteMatch" in seg_dir_df.columns:
            for val, n in seg_dir_df["DebugOracleTopRouteMatch"].fillna(-1).value_counts().items():
                qc_rows.append({"QC_Type": "DebugOracleTopRouteMatch", "QC_Value": str(val), "QC_Count": int(n)})
        if "DebugAmbiguityReason" in seg_dir_df.columns:
            for val, n in seg_dir_df["DebugAmbiguityReason"].fillna("Unknown").value_counts().items():
                qc_rows.append({"QC_Type": "DebugAmbiguityReason", "QC_Value": str(val), "QC_Count": int(n)})
        if "DebugMeasureGuardRejected" in seg_dir_df.columns:
            for val, n in seg_dir_df["DebugMeasureGuardRejected"].fillna(0).value_counts().items():
                qc_rows.append({"QC_Type": "DebugMeasureGuardRejected", "QC_Value": str(val), "QC_Count": int(n)})

    qc_df = pd.DataFrame(qc_rows)

    if not seg_dir_df.empty:
        route_blank_count = int(seg_dir_df["DebugRouteNameInput"].fillna("").astype(str).str.strip().eq("").sum()) if "DebugRouteNameInput" in seg_dir_df.columns else 0
        soft_penalty_count = int(seg_dir_df["QC_RouteMismatch"].fillna(0).sum()) if "QC_RouteMismatch" in seg_dir_df.columns else 0
        measure_guard_rejections = int(seg_dir_df["DebugMeasureGuardRejected"].fillna(0).sum()) if "DebugMeasureGuardRejected" in seg_dir_df.columns else 0
        atsignal_resolved = int(((seg_dir_df.get("Flow_Role") == "AtSignal") & (seg_dir_df.get("OracleMatchLevel") == "AtSignalMeasureResolved")).sum()) if {"Flow_Role", "OracleMatchLevel"}.issubset(seg_dir_df.columns) else 0
        nodebridge_ambiguous = int((seg_dir_df.get("OracleMatchLevel") == "NodeBridgeAmbiguous").sum()) if "OracleMatchLevel" in seg_dir_df.columns else 0
        nodebridge_resolved = int(seg_dir_df.get("OracleMatchLevel").isin(["NodeConsensusMeasureResolved", "NodeAndMeasureResolved"]).sum()) if "OracleMatchLevel" in seg_dir_df.columns else 0
        msg(
            "    -> Validation debug: "
            f"route_name_blank={route_blank_count} | "
            f"soft_route_penalty_rows={soft_penalty_count} | "
            f"measure_guard_rejections={measure_guard_rejections} | "
            f"atsignal_resolved={atsignal_resolved} | "
            f"nodebridge_resolved={nodebridge_resolved} | "
            f"nodebridge_ambiguous={nodebridge_ambiguous}"
        )
        if "DebugAmbiguityReason" in seg_dir_df.columns:
            amb_counts = seg_dir_df["DebugAmbiguityReason"].fillna("Unknown").value_counts()
            for val, n in amb_counts.items():
                msg(f"       ambiguity_reason[{val}]={int(n)}")

    if WRITE_DIAGNOSTIC_CSVS:
        write_df_to_table(seg_summary, EXPORT_SUMMARY_SEG)
        write_df_to_table(crash_dir_df, EXPORT_SUMMARY_CRASH)
        write_df_to_table(qc_df, EXPORT_SUMMARY_QC)
        return {
            "seg_summary_csv": EXPORT_SUMMARY_SEG,
            "crash_summary_csv": EXPORT_SUMMARY_CRASH,
            "qc_csv": EXPORT_SUMMARY_QC,
            "seg_summary_df": seg_summary,
            "crash_summary_df": crash_dir_df,
            "qc_df": qc_df
        }

    return {
        "seg_summary_df": seg_summary,
        "crash_summary_df": crash_dir_df,
        "qc_df": qc_df
    }

def join_csv_back_to_fgdb(csv_path, out_table_name):
    if not os.path.exists(csv_path):
        return None
    delete_if_exists(out_table_name)
    arcpy.conversion.TableToTable(csv_path, arcpy.env.workspace, out_table_name)
    return out_table_name
