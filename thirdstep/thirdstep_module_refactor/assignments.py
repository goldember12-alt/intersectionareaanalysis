# -*- coding: utf-8 -*-
"""
Initial ArcPy assignment steps for access points and crashes.
"""

from arcpy_utils import delete_if_exists, make_unique_name, pick_field
from config import *
from logging_utils import msg


def assign_access_initial(segments_fc, access_fc):
    msg("    -> Initial access assignment in ArcPy")
    tmp = os.path.join(arcpy.env.scratchGDB, make_unique_name("access_assigned"))
    out_fc = STAGED["access_assigned"]
    delete_if_exists(tmp)
    delete_if_exists(out_fc)

    fmap = arcpy.FieldMappings()
    seg_oid = pick_field(segments_fc, ["SegOID"], required=True)
    fm = arcpy.FieldMap()
    fm.addInputField(access_fc, arcpy.Describe(access_fc).OIDFieldName)
    out = fm.outputField
    out.name = "AccessOID"
    out.aliasName = "AccessOID"
    fm.outputField = out
    fmap.addFieldMap(fm)

    fm2 = arcpy.FieldMap()
    fm2.addInputField(segments_fc, seg_oid)
    out2 = fm2.outputField
    out2.name = "SegOID"
    out2.aliasName = "SegOID"
    fm2.outputField = out2
    fmap.addFieldMap(fm2)

    msg(f"       Access assignment uses {ACCESS_ASSIGN_MATCH_OPTION} within {ACCESS_SNAP_RADIUS}")
    arcpy.analysis.SpatialJoin(
        target_features=access_fc,
        join_features=segments_fc,
        out_feature_class=tmp,
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_COMMON",
        field_mapping=fmap,
        match_option=ACCESS_ASSIGN_MATCH_OPTION,
        search_radius=ACCESS_SNAP_RADIUS if ACCESS_ASSIGN_MATCH_OPTION.upper() != "INTERSECT" else None
    )

    arcpy.management.CopyFeatures(tmp, out_fc)
    delete_if_exists(tmp)
    return out_fc

def assign_crashes_initial(segments_fc, crashes_fc):
    msg("    -> Initial crash assignment in ArcPy")

    crash_oid_field = pick_field(crashes_fc, ["CrashOID"], required=False)
    if not crash_oid_field:
        crash_oid_field = arcpy.Describe(crashes_fc).OIDFieldName

    tmp = os.path.join(arcpy.env.scratchGDB, make_unique_name("crash_assigned"))
    out_fc = STAGED["crash_assigned"]
    delete_if_exists(tmp)
    delete_if_exists(out_fc)

    seg_oid = pick_field(segments_fc, ["SegOID"], required=True)
    fmap = arcpy.FieldMappings()

    keep_fields = [crash_oid_field]
    coll_field = pick_field(crashes_fc, CANDIDATE_FIELDS["collision_type"], required=False)
    if coll_field and coll_field not in keep_fields:
        keep_fields.append(coll_field)

    for fld in keep_fields:
        fm = arcpy.FieldMap()
        fm.addInputField(crashes_fc, fld)
        out = fm.outputField
        out.name = "CrashOID" if fld == crash_oid_field else fld
        out.aliasName = out.name
        fm.outputField = out
        fmap.addFieldMap(fm)

    fm_seg = arcpy.FieldMap()
    fm_seg.addInputField(segments_fc, seg_oid)
    out_seg = fm_seg.outputField
    out_seg.name = "SegOID"
    out_seg.aliasName = "SegOID"
    fm_seg.outputField = out_seg
    fmap.addFieldMap(fm_seg)

    msg(f"       Crash assignment uses {CRASH_ASSIGN_MATCH_OPTION} within {CRASH_SNAP_RADIUS}")
    arcpy.analysis.SpatialJoin(
        target_features=crashes_fc,
        join_features=segments_fc,
        out_feature_class=tmp,
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_COMMON",
        field_mapping=fmap,
        match_option=CRASH_ASSIGN_MATCH_OPTION,
        search_radius=CRASH_SNAP_RADIUS if CRASH_ASSIGN_MATCH_OPTION.upper() != "INTERSECT" else None
    )

    arcpy.management.CopyFeatures(tmp, out_fc)
    delete_if_exists(tmp)
    return out_fc
