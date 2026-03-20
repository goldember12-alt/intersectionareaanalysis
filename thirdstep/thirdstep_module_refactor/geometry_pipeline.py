# -*- coding: utf-8 -*-
"""
ArcPy geometry pipeline phases for roads, signals, zones, claims, and segmentation.
"""

import os
import time

import arcpy

from arcpy_utils import (
    ensure_field, field_map_upper, pick_field, delete_if_exists,
    safe_make_layer, make_unique_name, calculate_length_ft, calculate_midpoint_xy,
    delete_short_segments, feature_class_with_only_fields,
    invalidate_field_cache
)
from config import *
from logging_utils import msg, log_phase_time
from field_normalization import calculate_link_missing_flag


def assign_speed_to_signals(signals_fc, speed_fc, out_fc):
    """
    Assign speed and functional distances to study signals.
    Keep the spatial join, but collapse the post-join field work into a single
    cursor pass instead of multiple full-table CalculateField passes.
    """
    delete_if_exists(out_fc)

    speed_names_upper = field_map_upper(speed_fc)
    speed_field_src = pick_field(speed_fc, CANDIDATE_FIELDS["speed"], required=False, names_upper=speed_names_upper)
    if speed_field_src:
        speed_slim = os.path.join(arcpy.env.scratchGDB, make_unique_name("speed_slim"))
        delete_if_exists(speed_slim)
        try:
            feature_class_with_only_fields(speed_fc, speed_slim, [speed_field_src])
            join_fc = speed_slim
            speed_join_field_name = speed_field_src
            arcpy.analysis.SpatialJoin(
                target_features=signals_fc,
                join_features=join_fc,
                out_feature_class=out_fc,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                match_option="CLOSEST",
                search_radius=SIGNAL_SPEED_SEARCH
            )
        finally:
            delete_if_exists(speed_slim)
    else:
        speed_join_field_name = None
        arcpy.analysis.SpatialJoin(
            target_features=signals_fc,
            join_features=speed_fc,
            out_feature_class=out_fc,
            join_operation="JOIN_ONE_TO_ONE",
            join_type="KEEP_ALL",
            match_option="CLOSEST",
            search_radius=SIGNAL_SPEED_SEARCH
        )

    ensure_field(out_fc, "Assigned_Speed", "SHORT")
    ensure_field(out_fc, "Dist_Lim", "LONG")
    ensure_field(out_fc, "Dist_Des", "LONG")
    ensure_field(out_fc, "SignalOID", "LONG")

    out_names_upper = field_map_upper(out_fc, cached=False)
    speed_field = pick_field(out_fc, [speed_join_field_name] if speed_join_field_name else CANDIDATE_FIELDS["speed"], required=False, names_upper=out_names_upper)
    oid_field = arcpy.Describe(out_fc).OIDFieldName

    def _choose_speed(v):
        try:
            if v is None or float(v) < 15:
                v = DEFAULT_SPEED
            return int(v)
        except Exception:
            return int(DEFAULT_SPEED)

    def _dist_pair(v):
        s = _choose_speed(v)
        key = int(5 * round(float(s) / 5))
        return FUNCTIONAL_DISTANCES.get(key, FUNCTIONAL_DISTANCES[35])

    read_fields = [oid_field]
    if speed_field:
        read_fields.append(speed_field)
    update_fields = ["SignalOID", "Assigned_Speed", "Dist_Lim", "Dist_Des"]

    with arcpy.da.UpdateCursor(out_fc, read_fields + update_fields) as cur:
        for row in cur:
            oid_val = row[0]
            raw_speed = row[1] if speed_field else None
            assigned_speed = _choose_speed(raw_speed)
            dist_lim, dist_des = _dist_pair(raw_speed)
            row[-4] = int(oid_val)
            row[-3] = int(assigned_speed)
            row[-2] = int(dist_lim)
            row[-1] = int(dist_des)
            cur.updateRow(row)

    return out_fc

def build_functional_zones(signals_fc, zone1_fc, zone2full_fc, zone2_fc, all_fc):
    msg("    -> Building Zone 1 / Zone 2 functional areas")
    for x in [zone1_fc, zone2full_fc, zone2_fc, all_fc]:
        delete_if_exists(x)

    arcpy.analysis.PairwiseBuffer(signals_fc, zone1_fc, "Dist_Lim", dissolve_option="NONE")
    ensure_field(zone1_fc, "Zone_Type", "TEXT", 40)
    arcpy.management.CalculateField(zone1_fc, "Zone_Type", "'Zone 1: Critical'", "PYTHON3")

    arcpy.analysis.PairwiseBuffer(signals_fc, zone2full_fc, "Dist_Des", dissolve_option="NONE")
    try:
        arcpy.analysis.PairwiseErase(zone2full_fc, zone1_fc, zone2_fc)
    except Exception:
        arcpy.analysis.Erase(zone2full_fc, zone1_fc, zone2_fc)

    ensure_field(zone2_fc, "Zone_Type", "TEXT", 40)
    arcpy.management.CalculateField(zone2_fc, "Zone_Type", "'Zone 2: Functional'", "PYTHON3")

    arcpy.management.Merge([zone1_fc, zone2_fc], all_fc)

    for fld, typ, ln in [
        ("SignalOID", "LONG", None),
        ("Assigned_Speed", "SHORT", None),
        ("Dist_Lim", "LONG", None),
        ("Dist_Des", "LONG", None),
        ("QC_TrimmedByNeighbor", "SHORT", None),
    ]:
        ensure_field(all_fc, fld, typ, ln)

    return all_fc

def build_signal_neighbor_limits(signals_fc):
    msg("    -> Building signal-neighbor limits")
    sig_id_field = pick_field(signals_fc, ["SignalOID", "OBJECTID"], required=True)
    near_tbl = os.path.join(arcpy.env.scratchGDB, make_unique_name("near_sig_sig"))
    delete_if_exists(near_tbl)

    arcpy.analysis.GenerateNearTable(
        in_features=signals_fc,
        near_features=signals_fc,
        out_table=near_tbl,
        search_radius=NEIGHBOR_SIGNAL_RADIUS,
        closest="CLOSEST",
        method="GEODESIC"
    )

    limits = {}
    with arcpy.da.SearchCursor(near_tbl, ["IN_FID", "NEAR_FID", "NEAR_DIST"]) as cur:
        for in_fid, near_fid, dist in cur:
            if in_fid == near_fid:
                continue
            if in_fid not in limits or dist < limits[in_fid]:
                limits[in_fid] = float(dist)

    delete_if_exists(near_tbl)

    signal_oid_map = {}
    with arcpy.da.SearchCursor(signals_fc, ["OBJECTID", sig_id_field]) as cur:
        for oid, sid in cur:
            signal_oid_map[int(oid)] = int(sid)

    final_limits = {}
    for oid, dist in limits.items():
        final_limits[signal_oid_map.get(int(oid), int(oid))] = dist
    return final_limits

def apply_neighbor_trim_to_zones(zones_fc, signals_fc):
    """
    Apply neighbor-based trim flags using one reusable nearest-neighbor lookup.

    This keeps the cheaper map-based structure from the previous revision, but
    avoids rewriting the signal feature class row-by-row just to persist
    NeighborHalfLimit. The downstream trim logic only needs the lookup map and
    the zone-level fields.
    """
    msg("    -> Applying neighbor-based trim flags")
    ensure_field(zones_fc, "QC_TrimmedByNeighbor", "SHORT")
    ensure_field(zones_fc, "NeighborHalfLimit", "DOUBLE")

    sig_id = pick_field(zones_fc, ["SignalOID", "ORIG_FID", "TARGET_FID"], required=False)
    dist_des = pick_field(zones_fc, ["Dist_Des"], required=False)
    zone_type = pick_field(zones_fc, ["Zone_Type"], required=True)

    if not sig_id or not dist_des:
        msg("       ! Could not fully apply neighbor trim flags (missing fields)")
        return

    limit_map = build_signal_neighbor_limits(signals_fc)
    if not limit_map:
        arcpy.management.CalculateField(zones_fc, "QC_TrimmedByNeighbor", "0", "PYTHON3")
        return

    with arcpy.da.UpdateCursor(zones_fc, [sig_id, dist_des, zone_type, "NeighborHalfLimit", "QC_TrimmedByNeighbor"]) as cur:
        for row in cur:
            sid, dist_val, zone_val, _, _ = row

            try:
                sid_key = None if sid in (None, "") else int(sid)
            except Exception:
                sid_key = None

            half_limit = limit_map.get(sid_key) if sid_key is not None else None
            row[3] = half_limit

            trimmed = 0
            try:
                if zone_val and "Zone 2" in str(zone_val) and dist_val not in (None, "") and half_limit not in (None, ""):
                    trimmed = 1 if float(dist_val) > float(half_limit) else 0
            except Exception:
                trimmed = 0

            row[4] = trimmed
            cur.updateRow(row)

def resolve_signal_claims_by_roads(all_zones_fc, roads_fc, claims_fc, claims_clean_fc):
    """
    Intersect roads with zones to get road-claim pieces, then choose one owner per piece.
    The singleton/contested split is still done in ArcPy, but contested ranking is now
    pushed almost entirely into ArcPy tables as well:
      1) compute contested nearest-signal distance once
      2) calculate rank components on the contested FC
      3) use Statistics to pick the lowest score per ClaimGroupKey
      4) break ties with the minimum ClaimSrcOID
    That removes the prior Python-side group assembly and ranking pass.
    """
    msg("    -> Resolving overlapping signal claims")
    for x in [claims_fc, claims_clean_fc]:
        delete_if_exists(x)

    t_intersect = time.time()

    zone_keep = ["SignalOID", "Zone_Type", "Assigned_Speed", "Dist_Lim", "Dist_Des", "QC_TrimmedByNeighbor"]
    road_keep = [
        "ParentRoadOID", "LinkID_Norm", "RouteID_Norm", "RouteNm_Norm",
        "DirCode_Norm", "FromNode_Norm", "ToNode_Norm", "AADT"
    ]

    zone_slim = os.path.join(arcpy.env.scratchGDB, make_unique_name("zones_slim"))
    road_slim = os.path.join(arcpy.env.scratchGDB, make_unique_name("roads_slim"))
    claims_groups = os.path.join(arcpy.env.scratchGDB, make_unique_name("claims_groups"))
    contested_fc = os.path.join(arcpy.env.scratchGDB, make_unique_name("claims_contested"))
    singleton_fc = os.path.join(arcpy.env.scratchGDB, make_unique_name("claims_singleton"))
    kept_contested_fc = os.path.join(arcpy.env.scratchGDB, make_unique_name("claims_kept_contested"))
    contested_bestscore = os.path.join(arcpy.env.scratchGDB, make_unique_name("claims_bestscore"))
    contested_bestoid = os.path.join(arcpy.env.scratchGDB, make_unique_name("claims_bestoid"))
    delete_if_exists(zone_slim)
    delete_if_exists(road_slim)
    delete_if_exists(claims_groups)
    delete_if_exists(contested_fc)
    delete_if_exists(singleton_fc)
    delete_if_exists(kept_contested_fc)
    delete_if_exists(contested_bestscore)
    delete_if_exists(contested_bestoid)

    def _copy_with_fields(in_fc, out_fc, keep_fields):
        fmap = arcpy.FieldMappings()
        existing = field_map_upper(in_fc)
        keep = []
        for fld in keep_fields:
            real = existing.get(fld.upper())
            if real:
                keep.append(real)
        for fld in keep:
            fm = arcpy.FieldMap()
            fm.addInputField(in_fc, fld)
            fmap.addFieldMap(fm)
        arcpy.conversion.FeatureClassToFeatureClass(in_fc, os.path.dirname(out_fc), os.path.basename(out_fc), field_mapping=fmap)

    _copy_with_fields(all_zones_fc, zone_slim, zone_keep)
    _copy_with_fields(roads_fc, road_slim, road_keep)

    arcpy.analysis.PairwiseIntersect(
        in_features=[zone_slim, road_slim],
        out_feature_class=claims_fc,
        join_attributes="ALL"
    )
    log_phase_time("Claim resolution - intersect creation", t_intersect)

    ensure_field(claims_fc, "ClaimRank", "LONG")
    ensure_field(claims_fc, "KeepClaim", "SHORT")
    ensure_field(claims_fc, "QC_SignalOverlap", "SHORT")
    ensure_field(claims_fc, "ClaimSrcOID", "LONG")
    ensure_field(claims_fc, "ClaimGroupKey", "TEXT", 120)
    arcpy.management.CalculateField(claims_fc, "ClaimSrcOID", "!OBJECTID!", "PYTHON3")
    arcpy.management.CalculateField(claims_fc, "ClaimRank", "999999", "PYTHON3")
    arcpy.management.CalculateField(claims_fc, "KeepClaim", "0", "PYTHON3")
    arcpy.management.CalculateField(claims_fc, "QC_SignalOverlap", "0", "PYTHON3")

    oid = "OBJECTID"

    t_groupkey = time.time()
    group_block = f"""
DEC = {int(CLAIM_GEOM_KEY_DECIMALS)}
def _r(v):
    try:
        return round(float(v), DEC)
    except Exception:
        return None

def build_key(parent_oid, zone_type, shp_len, x, y):
    return "|".join([
        str(parent_oid) if parent_oid not in (None, '') else '',
        str(zone_type) if zone_type not in (None, '') else '',
        str(_r(shp_len)),
        str(_r(x)),
        str(_r(y)),
    ])
"""
    ensure_field(claims_fc, "ClaimLenTmp", "DOUBLE")
    ensure_field(claims_fc, "ClaimCentX", "DOUBLE")
    ensure_field(claims_fc, "ClaimCentY", "DOUBLE")
    arcpy.management.CalculateGeometryAttributes(
        claims_fc,
        [["ClaimLenTmp", "LENGTH"], ["ClaimCentX", "CENTROID_X"], ["ClaimCentY", "CENTROID_Y"]],
        length_unit="FEET_US"
    )
    arcpy.management.CalculateField(
        claims_fc,
        "ClaimGroupKey",
        "build_key(!ParentRoadOID!, !Zone_Type!, !ClaimLenTmp!, !ClaimCentX!, !ClaimCentY!)",
        "PYTHON3",
        group_block
    )
    log_phase_time("Claim resolution - group key creation", t_groupkey)

    t_stats = time.time()
    arcpy.analysis.Statistics(
        in_table=claims_fc,
        out_table=claims_groups,
        statistics_fields=[[oid, "COUNT"]],
        case_field="ClaimGroupKey"
    )
    log_phase_time("Claim resolution - claim group stats", t_stats)

    arcpy.management.JoinField(claims_fc, "ClaimGroupKey", claims_groups, "ClaimGroupKey", ["COUNT_OBJECTID"])
    invalidate_field_cache(claims_fc)

    singleton_lyr = safe_make_layer(claims_fc, "COUNT_OBJECTID = 1")
    contested_lyr = safe_make_layer(claims_fc, "COUNT_OBJECTID > 1")
    try:
        singleton_cnt = int(arcpy.management.GetCount(singleton_lyr)[0])
        contested_cnt = int(arcpy.management.GetCount(contested_lyr)[0])
    finally:
        pass

    msg(f"       Claim pieces: {singleton_cnt + contested_cnt:,} total | {contested_cnt:,} contested pieces")

    if singleton_cnt > 0:
        arcpy.management.CalculateField(singleton_lyr, "KeepClaim", "1", "PYTHON3")
        arcpy.management.CalculateField(singleton_lyr, "ClaimRank", "0", "PYTHON3")
        arcpy.management.CopyFeatures(singleton_lyr, singleton_fc)

    if contested_cnt > 0:
        arcpy.management.CopyFeatures(contested_lyr, contested_fc)
        ensure_field(contested_fc, "ClaimHasLink", "SHORT")
        ensure_field(contested_fc, "ClaimHasRoute", "SHORT")
        ensure_field(contested_fc, "ClaimNearDist", "DOUBLE")
        ensure_field(contested_fc, "BestSrcOID", "LONG")
        ensure_field(contested_fc, "BestRank", "LONG")

        names_upper = field_map_upper(contested_fc, cached=False)
        link_norm = pick_field(contested_fc, ["LinkID_Norm"], required=False, names_upper=names_upper)
        route_norm = pick_field(contested_fc, ["RouteID_Norm"], required=False, names_upper=names_upper)

        if link_norm:
            arcpy.management.CalculateField(contested_fc, "ClaimHasLink", f"0 if !{link_norm}! in (None, '', ' ') else 1", "PYTHON3")
        else:
            arcpy.management.CalculateField(contested_fc, "ClaimHasLink", "0", "PYTHON3")

        if route_norm:
            arcpy.management.CalculateField(contested_fc, "ClaimHasRoute", f"0 if !{route_norm}! in (None, '', ' ') else 1", "PYTHON3")
        else:
            arcpy.management.CalculateField(contested_fc, "ClaimHasRoute", "0", "PYTHON3")

        sig_fc = safe_make_layer(pick_signal_centroid_source(all_zones_fc))
        tmp_near = os.path.join(arcpy.env.scratchGDB, make_unique_name("near_claim_sig"))
        delete_if_exists(tmp_near)
        try:
            t_near = time.time()
            arcpy.analysis.GenerateNearTable(
                in_features=contested_fc,
                near_features=sig_fc,
                out_table=tmp_near,
                search_radius=NEIGHBOR_SIGNAL_RADIUS,
                closest="CLOSEST",
                method="GEODESIC"
            )
            log_phase_time("Claim resolution - contested near table generation", t_near)
            arcpy.management.JoinField(contested_fc, "OBJECTID", tmp_near, "IN_FID", ["NEAR_DIST"])
            invalidate_field_cache(contested_fc)
        finally:
            delete_if_exists(sig_fc)
            delete_if_exists(tmp_near)

        arcpy.management.CalculateField(
            contested_fc,
            "ClaimNearDist",
            "999999.0 if !NEAR_DIST! in (None, '') else float(!NEAR_DIST!)",
            "PYTHON3"
        )
        arcpy.management.CalculateField(
            contested_fc,
            "ClaimRank",
            "int(((1 - int(!ClaimHasLink!)) * 10000) + ((1 - int(!ClaimHasRoute!)) * 1000) + round(float(!ClaimNearDist!)))",
            "PYTHON3"
        )

        t_rank = time.time()
        arcpy.analysis.Statistics(
            in_table=contested_fc,
            out_table=contested_bestscore,
            statistics_fields=[["ClaimRank", "MIN"]],
            case_field="ClaimGroupKey"
        )
        bestscore_field = pick_field(contested_bestscore, ["MIN_ClaimRank", "MIN_CLAIMRANK"], required=True)
        arcpy.management.JoinField(contested_fc, "ClaimGroupKey", contested_bestscore, "ClaimGroupKey", [bestscore_field])
        invalidate_field_cache(contested_fc)

        bestscore_lyr = safe_make_layer(contested_fc, f"ClaimRank = {bestscore_field}")
        try:
            arcpy.analysis.Statistics(
                in_table=bestscore_lyr,
                out_table=contested_bestoid,
                statistics_fields=[["ClaimSrcOID", "MIN"]],
                case_field="ClaimGroupKey"
            )
        finally:
            delete_if_exists(bestscore_lyr)

        bestoid_field = pick_field(contested_bestoid, ["MIN_ClaimSrcOID", "MIN_CLAIMSRCOID"], required=True)
        arcpy.management.JoinField(contested_fc, "ClaimGroupKey", contested_bestoid, "ClaimGroupKey", [bestoid_field])
        invalidate_field_cache(contested_fc)
        arcpy.management.CalculateField(contested_fc, "BestSrcOID", f"!{bestoid_field}!", "PYTHON3")
        arcpy.management.CalculateField(contested_fc, "BestRank", f"!{bestscore_field}!", "PYTHON3")
        arcpy.management.CalculateField(contested_fc, "KeepClaim", "1 if !ClaimSrcOID! == !BestSrcOID! else 0", "PYTHON3")
        arcpy.management.CalculateField(contested_fc, "QC_SignalOverlap", "0 if !KeepClaim! == 1 else 1", "PYTHON3")
        log_phase_time("Claim resolution - contested ArcPy ranking", t_rank)

        kept_lyr = safe_make_layer(contested_fc, "KeepClaim = 1")
        try:
            arcpy.management.CopyFeatures(kept_lyr, kept_contested_fc)
        finally:
            delete_if_exists(kept_lyr)

    merge_inputs = [fc for fc in [singleton_fc, kept_contested_fc] if arcpy.Exists(fc)]
    if len(merge_inputs) == 1:
        arcpy.management.CopyFeatures(merge_inputs[0], claims_clean_fc)
    elif merge_inputs:
        arcpy.management.Merge(merge_inputs, claims_clean_fc)
    else:
        arcpy.management.CopyFeatures(claims_fc, claims_clean_fc)

    for fld in [
        "ClaimLenTmp", "ClaimCentX", "ClaimCentY", "COUNT_OBJECTID", "ClaimGroupKey",
        "ClaimHasLink", "ClaimHasRoute", "ClaimNearDist", "NEAR_DIST", "BestSrcOID", "BestRank",
        "MIN_CLAIMRANK", "MIN_ClaimRank", "MIN_CLAIMSRCOID", "MIN_ClaimSrcOID"
    ]:
        try:
            arcpy.management.DeleteField(claims_clean_fc, fld)
        except Exception:
            pass

    delete_if_exists(singleton_lyr)
    delete_if_exists(contested_lyr)
    delete_if_exists(zone_slim)
    delete_if_exists(road_slim)
    delete_if_exists(claims_groups)
    delete_if_exists(contested_fc)
    delete_if_exists(singleton_fc)
    delete_if_exists(kept_contested_fc)
    delete_if_exists(contested_bestscore)
    delete_if_exists(contested_bestoid)

def pick_signal_centroid_source(zones_fc):
    if arcpy.Exists(STAGED["signals_speed"]):
        return STAGED["signals_speed"]
    return zones_fc

def segment_roads_from_clean_claims(claims_clean_fc, out_fc):
    msg("    -> Segmenting roads from cleaned road-claim pieces")
    delete_if_exists(out_fc)
    arcpy.management.CopyFeatures(claims_clean_fc, out_fc)

    ensure_field(out_fc, "SegOID", "LONG")
    ensure_field(out_fc, "SegStableID", "LONG")
    if "ClaimSrcOID" in field_map_upper(out_fc):
        arcpy.management.CalculateField(out_fc, "SegStableID", "!ClaimSrcOID!", "PYTHON3")
    else:
        arcpy.management.CalculateField(out_fc, "SegStableID", "!OBJECTID!", "PYTHON3")
    arcpy.management.CalculateField(out_fc, "SegOID", "!OBJECTID!", "PYTHON3")

    for fld, typ, ln in [
        ("Zone_Type", "TEXT", 40),
        ("SignalOID", "LONG", None),
        ("ParentRoadOID", "LONG", None),
        ("LinkID_Norm", "TEXT", 80),
        ("RouteID_Norm", "TEXT", 80),
        ("RouteNm_Norm", "TEXT", 120),
        ("DirCode_Norm", "TEXT", 40),
        ("FromNode_Norm", "TEXT", 80),
        ("ToNode_Norm", "TEXT", 80),
        ("AADT", "LONG", None),
        ("Seg_Len_Ft", "DOUBLE", None),
        ("Mid_X", "DOUBLE", None),
        ("Mid_Y", "DOUBLE", None),
        ("QC_LinkMissing", "SHORT", None),
        ("QC_DirectionUnknown", "SHORT", None),
        ("QC_TrimmedByNeighbor", "SHORT", None),
        ("QC_SignalOverlap", "SHORT", None),
        ("QC_CrashFarSnap", "SHORT", None),
    ]:
        ensure_field(out_fc, fld, typ, ln)

    calculate_length_ft(out_fc, "Seg_Len_Ft")
    calculate_midpoint_xy(out_fc, "Mid_X", "Mid_Y")
    delete_short_segments(out_fc, MIN_SEGMENT_FT)
    arcpy.management.CalculateField(out_fc, "SegOID", "!OBJECTID!", "PYTHON3")
    if "SegStableID" not in field_map_upper(out_fc):
        ensure_field(out_fc, "SegStableID", "LONG")
        arcpy.management.CalculateField(out_fc, "SegStableID", "!SegOID!", "PYTHON3")

    calculate_link_missing_flag(out_fc)

    return out_fc
