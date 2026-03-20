# -*- coding: utf-8 -*-
"""
Generic ArcPy helpers for thirdstep.
"""

import os
import re

import config as cfg
from config import *
from logging_utils import msg

_FIELD_CACHE = {}

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

def _cache_key(fc):
    try:
        catalog_path = arcpy.Describe(fc).catalogPath
        if catalog_path:
            return os.path.abspath(catalog_path).lower()
    except Exception:
        pass
    try:
        return os.path.abspath(str(fc)).lower()
    except Exception:
        return str(fc)

def invalidate_field_cache(fc):
    if fc:
        _FIELD_CACHE.pop(_cache_key(fc), None)

def field_names(fc, cached=True):
    key = _cache_key(fc)
    if cached and key in _FIELD_CACHE:
        return list(_FIELD_CACHE[key]["names"])
    fields = arcpy.ListFields(fc)
    names = [f.name for f in fields]
    upper = {f.name.upper(): f.name for f in fields}
    _FIELD_CACHE[key] = {"names": names, "upper": upper}
    return list(names)

def field_map_upper(fc, cached=True):
    key = _cache_key(fc)
    if cached and key in _FIELD_CACHE:
        return dict(_FIELD_CACHE[key]["upper"])
    field_names(fc, cached=False)
    return dict(_FIELD_CACHE[key]["upper"])

def pick_field(fc, candidates, required=False, names_upper=None):
    if names_upper is None:
        names_upper = field_map_upper(fc)
    for c in candidates:
        if c.upper() in names_upper:
            return names_upper[c.upper()]
    if required:
        raise RuntimeError(f"Could not find required field in {fc}. Candidates: {candidates}")
    return None

def find_field_by_tokens(fc, include_tokens, exclude_tokens=None, prefer_exact_prefixes=None):
    include_tokens = [t.upper() for t in (include_tokens or [])]
    exclude_tokens = [t.upper() for t in (exclude_tokens or [])]
    prefer_exact_prefixes = [t.upper() for t in (prefer_exact_prefixes or [])]

    names = field_names(fc, cached=False)
    scored = []
    for name in names:
        upper = name.upper()
        if exclude_tokens and any(tok in upper for tok in exclude_tokens):
            continue
        if include_tokens and not all(tok in upper for tok in include_tokens):
            continue
        score = 0
        if upper in prefer_exact_prefixes:
            score += 100
        if any(upper.startswith(p) for p in prefer_exact_prefixes):
            score += 20
        if upper.endswith('_NORM'):
            score += 5
        score -= upper.count('_')
        score -= len(upper) / 1000.0
        scored.append((score, name))

    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored[0][1]

def find_segment_inherited_field(fc, base_name):
    names = field_names(fc, cached=False)
    upper_map = {n.upper(): n for n in names}
    base_upper = base_name.upper()
    if base_upper in upper_map:
        return upper_map[base_upper]

    preferred = []
    for nm in names:
        up = nm.upper()
        if up == base_upper:
            preferred.append((0, nm))
        elif up.startswith(base_upper + '_'):
            suffix = up[len(base_upper) + 1:]
            penalty = 1
            if suffix.isdigit():
                penalty += int(suffix)
            preferred.append((penalty, nm))
        elif base_upper in up:
            preferred.append((50, nm))
    if not preferred:
        return None
    preferred.sort(key=lambda x: (x[0], x[1]))
    return preferred[0][1]

def geopandas_pipeline_enabled():
    return bool(cfg.USE_GEOPANDAS and cfg.gpd is not None and cfg.pd is not None)

def ensure_effective_geopandas_flag():
    if cfg.USE_GEOPANDAS and not geopandas_pipeline_enabled():
        msg("    ! USE_GEOPANDAS requested, but pandas/geopandas are not available in this Python environment; disabling GeoPandas pipeline")
        cfg.USE_GEOPANDAS = False

def ensure_field(fc, name, ftype, length=None):
    existing_upper = {f.upper() for f in field_names(fc, cached=False)}
    if name.upper() in existing_upper:
        return
    if length is not None:
        arcpy.management.AddField(fc, name, ftype, field_length=length)
    else:
        arcpy.management.AddField(fc, name, ftype)
    invalidate_field_cache(fc)
    field_names(fc, cached=False)

def delete_if_exists(path):
    try:
        if path and arcpy.Exists(path):
            arcpy.management.Delete(path)
    except Exception:
        pass

def copy_or_project(in_fc, out_fc, sr=TARGET_SR, cache=True):
    desc = arcpy.Describe(in_fc)
    same_sr = False
    try:
        if desc.spatialReference and desc.spatialReference.factoryCode == sr.factoryCode:
            same_sr = True
    except Exception:
        same_sr = False

    if cache and arcpy.Exists(out_fc):
        msg(f"    -> Reusing cached staged input: {out_fc}")
        return out_fc

    delete_if_exists(out_fc)

    if same_sr:
        msg(f"    -> Copying {in_fc} -> {out_fc}")
        arcpy.management.CopyFeatures(in_fc, out_fc)
    else:
        msg(f"    -> Projecting {in_fc} -> {out_fc}")
        arcpy.management.Project(in_fc, out_fc, sr)
    return out_fc

def check_required_fields(fc, label, required_groups):
    missing = []
    present = field_names(fc)
    present_upper = {x.upper() for x in present}
    for group_name, candidates in required_groups.items():
        if not any(c.upper() in present_upper for c in candidates):
            missing.append((group_name, candidates))
    if missing:
        details = "; ".join([f"{g}: {c}" for g, c in missing])
        raise RuntimeError(f"{label} missing required fields/groups -> {details}")

def calculate_length_ft(fc, out_field="Seg_Len_Ft"):
    ensure_field(fc, out_field, "DOUBLE")
    arcpy.management.CalculateGeometryAttributes(
        fc,
        [[out_field, "LENGTH_GEODESIC"]],
        length_unit="FEET_US"
    )

def calculate_midpoint_xy(fc, x_field="Mid_X", y_field="Mid_Y"):
    ensure_field(fc, x_field, "DOUBLE")
    ensure_field(fc, y_field, "DOUBLE")
    arcpy.management.CalculateGeometryAttributes(
        fc,
        [[x_field, "CENTROID_X"], [y_field, "CENTROID_Y"]]
    )

def delete_short_segments(fc, min_len_ft: float, length_field="Seg_Len_Ft"):
    msg(f"    -> Deleting slivers shorter than {min_len_ft} ft")
    ensure_field(fc, length_field, "DOUBLE")
    lyr = make_unique_name("lyr_short")
    arcpy.management.MakeFeatureLayer(fc, lyr)
    arcpy.management.SelectLayerByAttribute(lyr, "NEW_SELECTION", f"{length_field} < {min_len_ft}")
    n = int(arcpy.management.GetCount(lyr)[0])
    msg(f"       Selected for deletion: {n}")
    if n > 0:
        arcpy.management.DeleteRows(lyr)
    delete_if_exists(lyr)
    return n

def get_crash_sql(layer):
    desc = arcpy.Describe(layer)
    fields = desc.fields

    year_field = next((f for f in fields if "YEAR" in f.name.upper()), None)
    if year_field:
        msg(f"    -> Detected crash year field: {year_field.name} ({year_field.type})")
        if year_field.type == "String":
            return f"{year_field.name} >= '2023'"
        return f"{year_field.name} >= 2023"

    date_field = next((f for f in fields if "DATE" in f.name.upper() and f.type == "Date"), None)
    if date_field:
        msg(f"    -> Detected crash date field: {date_field.name} (Date)")
        return f"{date_field.name} >= date '2023-01-01 00:00:00'"

    msg("    ! Could not auto-detect crash year/date field; no crash filter will be applied")
    return ""

def write_qc_table(rows, out_table):
    delete_if_exists(out_table)
    folder, name = os.path.split(out_table)
    if not folder:
        folder = arcpy.env.workspace

    arcpy.management.CreateTable(folder, name)
    ensure_field(out_table, "QC_Type", "TEXT", 100)
    ensure_field(out_table, "QC_Value", "TEXT", 255)
    ensure_field(out_table, "QC_Count", "LONG")

    with arcpy.da.InsertCursor(out_table, ["QC_Type", "QC_Value", "QC_Count"]) as cur:
        for r in rows:
            cur.insertRow([r.get("QC_Type"), r.get("QC_Value"), int(r.get("QC_Count", 0))])

def join_fields_back(target_fc, target_key, join_table, join_key, fields_to_add):
    existing = {f.name for f in arcpy.ListFields(join_table)}
    keep = [f for f in fields_to_add if f in existing]
    if not keep:
        msg(f"    -> No fields available to join from {join_table}")
        return
    arcpy.management.JoinField(target_fc, target_key, join_table, join_key, keep)
    invalidate_field_cache(target_fc)

def safe_make_layer(fc, where=None):
    lyr = make_unique_name("lyr")
    if where:
        msg(f"    -> MakeFeatureLayer WHERE: {where}")
        arcpy.management.MakeFeatureLayer(fc, lyr, where)
    else:
        msg(f"    -> MakeFeatureLayer WHERE: <none>")
        arcpy.management.MakeFeatureLayer(fc, lyr)
    return lyr

def copy_rows_to_table_from_csv(csv_path, out_table):
    if not os.path.exists(csv_path):
        return None
    delete_if_exists(out_table)
    arcpy.conversion.TableToTable(csv_path, arcpy.env.workspace, os.path.basename(out_table))
    return out_table

def feature_class_with_only_fields(in_fc, out_fc, keep_fields):
    delete_if_exists(out_fc)
    fmap = arcpy.FieldMappings()
    existing = field_map_upper(in_fc)
    keep = []
    for fld in keep_fields:
        real = existing.get(fld.upper())
        if real and real not in keep:
            keep.append(real)
    for fld in keep:
        fm = arcpy.FieldMap()
        fm.addInputField(in_fc, fld)
        fmap.addFieldMap(fm)
    arcpy.conversion.FeatureClassToFeatureClass(in_fc, os.path.dirname(out_fc), os.path.basename(out_fc), field_mapping=fmap)
    invalidate_field_cache(out_fc)
    return out_fc

def _chunked_oid_groups(oid_values, chunk_size=500):
    vals = sorted({int(v) for v in oid_values if v not in (None, "")})
    for i in range(0, len(vals), chunk_size):
        yield vals[i:i + chunk_size]

def _select_layer_by_oids(in_fc, oid_values, layer_name):
    lyr = safe_make_layer(in_fc)
    oid_field = arcpy.Describe(in_fc).OIDFieldName
    first = True
    for chunk in _chunked_oid_groups(oid_values):
        where = f"{arcpy.AddFieldDelimiters(in_fc, oid_field)} IN ({','.join(str(v) for v in chunk)})"
        arcpy.management.SelectLayerByAttribute(
            lyr,
            "NEW_SELECTION" if first else "ADD_TO_SELECTION",
            where
        )
        first = False
    return lyr

def _make_backfill_fieldmap(target_layer, target_oid_field, join_fc, join_fields):
    fmap = arcpy.FieldMappings()

    fm_oid = arcpy.FieldMap()
    fm_oid.addInputField(target_layer, target_oid_field)
    out_oid = fm_oid.outputField
    out_oid.name = "TARGET_OID"
    out_oid.aliasName = "TARGET_OID"
    fm_oid.outputField = out_oid
    fmap.addFieldMap(fm_oid)

    for src_field in [f for f in join_fields if f]:
        fm = arcpy.FieldMap()
        fm.addInputField(join_fc, src_field)
        out = fm.outputField
        safe = re.sub(r"[^A-Za-z0-9_]", "_", str(src_field)).upper()
        out.name = f"SJ_{safe}"[:64]
        out.aliasName = out.name
        fm.outputField = out
        fmap.addFieldMap(fm)

    return fmap

def _subset_where_missing_expr(fc, include_link=True, include_aadt=False, include_route=False, include_dir=False):
    names_upper = field_map_upper(fc)
    parts = []

    def text_missing_expr(field_name):
        real_name = names_upper.get(field_name.upper())
        if not real_name:
            return None
        fld = arcpy.AddFieldDelimiters(fc, real_name)
        return f"({fld} IS NULL OR {fld} = '' OR {fld} = ' ')"

    def numeric_missing_expr(field_name):
        real_name = names_upper.get(field_name.upper())
        if not real_name:
            return None
        fld = arcpy.AddFieldDelimiters(fc, real_name)
        return f"({fld} IS NULL OR {fld} = 0)"

    if include_link:
        expr = text_missing_expr("LinkID_Norm")
        if expr:
            parts.append(expr)

    if include_aadt:
        expr = numeric_missing_expr("AADT")
        if expr:
            parts.append(expr)

    if include_route:
        expr = text_missing_expr("RouteID_Norm")
        if expr:
            parts.append(expr)

    if include_dir:
        expr = text_missing_expr("DirCode_Norm")
        if expr:
            parts.append(expr)

    return " OR ".join(parts)
