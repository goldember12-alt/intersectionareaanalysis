# -*- coding: utf-8 -*-
"""
Final writeback, QC flagging, and diagnostics.
"""

from collections import Counter
import os

from arcpy_utils import ensure_field, delete_if_exists, field_names, pick_field, safe_make_layer, write_qc_table
from config import *
from logging_utils import msg

def calculate_final_density_metrics(segments_fc):
    ensure_field(segments_fc, "Access_Density_1k", "DOUBLE")
    ensure_field(segments_fc, "Crash_Density_1k", "DOUBLE")

    code = f"""
def calc_density(count, length):
    try:
        if length is None or length < {MIN_VALID_LEN_FT}:
            return 0
        if count is None:
            count = 0
        return (float(count) / float(length)) * 1000.0
    except:
        return 0
"""
    arcpy.management.CalculateField(
        segments_fc,
        "Access_Density_1k",
        "calc_density(!Cnt_Access!, !Seg_Len_Ft!)",
        "PYTHON3",
        code
    )
    arcpy.management.CalculateField(
        segments_fc,
        "Crash_Density_1k",
        "calc_density(!Cnt_Crash_Total!, !Seg_Len_Ft!)",
        "PYTHON3",
        code
    )

def add_final_schema_defaults(segments_fc):
    final_fields = [
        ("LinkID_Norm", "TEXT", 80),
        ("RouteID_Norm", "TEXT", 80),
        ("RouteNm_Norm", "TEXT", 120),
        ("FromNode_Norm", "TEXT", 80),
        ("ToNode_Norm", "TEXT", 80),
        ("Signal_M", "DOUBLE", None),
        ("SegMid_M", "DOUBLE", None),
        ("Delta_M", "DOUBLE", None),
        ("Side_Code", "TEXT", 30),
        ("Flow_Role", "TEXT", 30),
        ("DirSource", "TEXT", 60),
        ("OracleMatchStatus", "TEXT", 40),
        ("OracleMatchLevel", "TEXT", 40),
        ("OracleTMSLINKID", "TEXT", 80),
        ("OracleRouteNm", "TEXT", 120),
        ("OracleBeginNode", "TEXT", 80),
        ("OracleEndNode", "TEXT", 80),
        ("OracleLinkSequence", "DOUBLE", None),
        ("OracleRouteMP", "DOUBLE", None),
        ("OracleAADT", "LONG", None),
        ("OracleDirBasis", "TEXT", 40),
        ("IntersectionNode", "TEXT", 80),
        ("IntersectionNodeBasis", "TEXT", 40),
        ("OracleNodeRelation", "TEXT", 40),
        ("AADT_Source", "TEXT", 30),
        ("Cnt_Access", "LONG", None),
        ("Cnt_Crash_Total", "LONG", None),
        ("Cnt_Crash_Up", "LONG", None),
        ("Cnt_Crash_Down", "LONG", None),
        ("Cnt_Crash_At", "LONG", None),
        ("AADT", "LONG", None),
        ("QC_LinkMissing", "SHORT", None),
        ("QC_SignalOverlap", "SHORT", None),
        ("QC_DirectionUnknown", "SHORT", None),
        ("QC_TrimmedByNeighbor", "SHORT", None),
        ("QC_CrashFarSnap", "SHORT", None),
        ("QC_OracleNoMatch", "SHORT", None),
        ("QC_OracleAmbiguous", "SHORT", None),
        ("QC_NodeMissing", "SHORT", None),
        ("QC_RouteMismatch", "SHORT", None),
        ("QC_AADTConflict", "SHORT", None),
    ]
    for n, t, l in final_fields:
        ensure_field(segments_fc, n, t, l)

def flag_unknown_direction(segments_fc):
    if "Flow_Role" not in field_names(segments_fc):
        return
    ensure_field(segments_fc, "QC_DirectionUnknown", "SHORT")
    arcpy.management.CalculateField(
        segments_fc,
        "QC_DirectionUnknown",
        "1 if !Flow_Role! in (None, '', 'Unknown') else 0",
        "PYTHON3"
    )

def consolidate_final_qc_flags(segments_fc):
    names = set(field_names(segments_fc))
    if "LinkID_Norm" in names:
        ensure_field(segments_fc, "QC_LinkMissing", "SHORT")
        arcpy.management.CalculateField(
            segments_fc,
            "QC_LinkMissing",
            "1 if !LinkID_Norm! in (None, '', ' ') else 0",
            "PYTHON3"
        )
    if "Flow_Role" in names:
        flag_unknown_direction(segments_fc)

    zero_fill_fields = [
        f for f in ["QC_SignalOverlap", "QC_TrimmedByNeighbor", "QC_CrashFarSnap", "Cnt_Access",
                    "Cnt_Crash_Total", "Cnt_Crash_Up", "Cnt_Crash_Down", "Cnt_Crash_At", "AADT",
                    "QC_OracleNoMatch", "QC_OracleAmbiguous", "QC_NodeMissing", "QC_RouteMismatch", "QC_AADTConflict"]
        if f in names
    ]
    for fname in zero_fill_fields:
        arcpy.management.CalculateField(
            segments_fc,
            fname,
            f"0 if !{fname}! is None else !{fname}!",
            "PYTHON3"
        )



def log_final_oracle_validation(segments_fc):
    names = set(field_names(segments_fc))
    required = [
        "OracleMatchStatus", "OracleMatchLevel", "OracleDirBasis",
        "QC_OracleNoMatch", "QC_OracleAmbiguous", "IntersectionNode", "AADT_Source"
    ]
    missing = [f for f in required if f not in names]
    if missing:
        msg(f"    ! Final Oracle validation skipped missing fields: {', '.join(missing)}")
        return

    total = 0
    no_match = 0
    ambiguous = 0
    node_missing = 0
    statuses = {}
    with arcpy.da.SearchCursor(segments_fc, [
        "OracleMatchStatus", "QC_OracleNoMatch", "QC_OracleAmbiguous", "IntersectionNode"
    ]) as cur:
        for status, qc_no_match, qc_ambiguous, intersection_node in cur:
            total += 1
            statuses[status or "<null>"] = statuses.get(status or "<null>", 0) + 1
            no_match += 1 if qc_no_match == 1 else 0
            ambiguous += 1 if qc_ambiguous == 1 else 0
            node_missing += 1 if intersection_node in (None, "", " ") else 0

    msg(
        "    -> Final Oracle validation: "
        f"rows={total} | QC_OracleNoMatch={no_match} | QC_OracleAmbiguous={ambiguous} | missing_intersection_node={node_missing}"
    )
    top_status = ", ".join(f"{k}={v}" for k, v in sorted(statuses.items(), key=lambda kv: (-kv[1], str(kv[0])))[:6])
    if top_status:
        msg(f"    -> OracleMatchStatus breakdown: {top_status}")
def build_qc_layers(segments_fc, crash_assigned_fc):
    if not WRITE_QC_LAYERS:
        return

    lyr = safe_make_layer(segments_fc, "QC_DirectionUnknown = 1")
    delete_if_exists(OUTPUT_QC_UNKNOWN_DIR)
    arcpy.management.CopyFeatures(lyr, OUTPUT_QC_UNKNOWN_DIR)
    delete_if_exists(lyr)

    lyr = safe_make_layer(segments_fc, "QC_SignalOverlap = 1")
    delete_if_exists(OUTPUT_QC_OVERLAP)
    arcpy.management.CopyFeatures(lyr, OUTPUT_QC_OVERLAP)
    delete_if_exists(lyr)

    if arcpy.Exists(crash_assigned_fc):
        dist_field = pick_field(crash_assigned_fc, ["NEAR_DIST", "Join_Distance"], required=False)
        if dist_field:
            lyr = safe_make_layer(crash_assigned_fc, f"{dist_field} > {FAR_SNAP_FT}")
            delete_if_exists(OUTPUT_QC_CRASH_FAR)
            arcpy.management.CopyFeatures(lyr, OUTPUT_QC_CRASH_FAR)
            delete_if_exists(lyr)

def summarize_qc_counts(segments_fc, qc_csv_table=None):
    rows = []
    fields = ["QC_LinkMissing", "QC_SignalOverlap", "QC_DirectionUnknown", "QC_TrimmedByNeighbor",
              "QC_OracleNoMatch", "QC_OracleAmbiguous", "QC_NodeMissing", "QC_RouteMismatch",
              "QC_AADTConflict", "Seg_Len_Ft"]
    miss = overlap = unk = trim = oracle_nomatch = oracle_amb = node_missing = route_mismatch = aadt_conflict = short = 0
    with arcpy.da.SearchCursor(segments_fc, fields) as cur:
        for q1, q2, q3, q4, q5, q6, q7, q8, q9, seglen in cur:
            miss += 1 if q1 == 1 else 0
            overlap += 1 if q2 == 1 else 0
            unk += 1 if q3 == 1 else 0
            trim += 1 if q4 == 1 else 0
            oracle_nomatch += 1 if q5 == 1 else 0
            oracle_amb += 1 if q6 == 1 else 0
            node_missing += 1 if q7 == 1 else 0
            route_mismatch += 1 if q8 == 1 else 0
            aadt_conflict += 1 if q9 == 1 else 0
            short += 1 if seglen is not None and seglen < MIN_SEGMENT_FT else 0
    rows.extend([
        {"QC_Type": "QCFlag", "QC_Value": "MissingLinkID", "QC_Count": miss},
        {"QC_Type": "QCFlag", "QC_Value": "OverlapClaim", "QC_Count": overlap},
        {"QC_Type": "QCFlag", "QC_Value": "UnknownDirection", "QC_Count": unk},
        {"QC_Type": "QCFlag", "QC_Value": "TrimmedByNeighbor", "QC_Count": trim},
        {"QC_Type": "QCFlag", "QC_Value": "OracleNoMatch", "QC_Count": oracle_nomatch},
        {"QC_Type": "QCFlag", "QC_Value": "OracleAmbiguous", "QC_Count": oracle_amb},
        {"QC_Type": "QCFlag", "QC_Value": "NodeMissing", "QC_Count": node_missing},
        {"QC_Type": "QCFlag", "QC_Value": "RouteMismatch", "QC_Count": route_mismatch},
        {"QC_Type": "QCFlag", "QC_Value": "AADTConflict", "QC_Count": aadt_conflict},
        {"QC_Type": "QCFlag", "QC_Value": "SuspiciousShortSegment", "QC_Count": short},
    ])

    if qc_csv_table and arcpy.Exists(qc_csv_table):
        try:
            with arcpy.da.SearchCursor(qc_csv_table, ["QC_Type", "QC_Value", "QC_Count"]) as cur:
                for a, b, c in cur:
                    rows.append({"QC_Type": a, "QC_Value": b, "QC_Count": int(c)})
        except Exception:
            pass

    write_qc_table(rows, OUTPUT_QC_TABLE)


def _norm_writeback_key(value):
    if value in (None, "", " "):
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith('.0'):
        s = s[:-2]
    s = s.lstrip('0') or '0'
    return s


def _safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _rows_match_on_existing_payload(row, payload, fields):
    for field_name in fields:
        row_val = row.get(field_name)
        payload_val = payload.get(field_name)
        if row_val in (None, "", " ") and payload_val in (None, "", " "):
            continue
        if row_val != payload_val:
            return False
    return True



def _norm_text(value):
    if value in (None, "", " "):
        return None
    s = str(value).strip()
    return s or None


def _fallback_key_tuple(rec, fields):
    vals = []
    for field_name in fields:
        value = rec.get(field_name)
        if field_name in ("LinkID_Norm", "RouteID_Norm", "RouteNm_Norm", "FromNode_Norm", "ToNode_Norm", "DirCode_Norm"):
            vals.append(_norm_writeback_key(value))
        else:
            vals.append(_norm_text(value))
    return tuple(vals)


def _key_is_complete(key):
    return all(v is not None for v in key)


def _key_to_text(fields, key):
    return " | ".join(f"{name}={value}" for name, value in zip(fields, key))


def _ensure_table(table_path, fields_spec):
    workspace, name = os.path.dirname(table_path), os.path.basename(table_path)
    delete_if_exists(table_path)
    arcpy.management.CreateTable(workspace, name)
    reserved = {"OBJECTID", "OID", "FID", "Shape", "Shape_Length", "Shape_Area", "GLOBALID"}
    existing = {f.name.upper() for f in arcpy.ListFields(table_path)}
    for field_name, field_type, field_len in fields_spec:
        if field_name.upper() in reserved or field_name.upper() in existing:
            continue
        if field_type == "TEXT":
            arcpy.management.AddField(table_path, field_name, field_type, field_length=field_len)
        else:
            arcpy.management.AddField(table_path, field_name, field_type)
        existing.add(field_name.upper())
    return table_path


def _insert_rows(table_path, field_names_list, rows):
    if not rows:
        return
    with arcpy.da.InsertCursor(table_path, field_names_list) as cur:
        for row in rows:
            cur.insertRow([row.get(f) for f in field_names_list])


def _export_unresolved_writeback_audit(segments_fc, unresolved_rows):
    table_path = os.path.join(os.path.dirname(segments_fc), "QC_Writeback_Unresolved")
    fields_spec = [
        ("SegmentObjectID", "LONG", None),
        ("Reason", "TEXT", 80),
        ("FallbackTier", "TEXT", 40),
        ("CandidateCount", "LONG", None),
        ("LinkID_Norm", "TEXT", 80),
        ("RouteID_Norm", "TEXT", 80),
        ("FromNode_Norm", "TEXT", 80),
        ("ToNode_Norm", "TEXT", 80),
        ("SignalOID", "LONG", None),
        ("ParentRoadOID", "LONG", None),
        ("SegOID", "LONG", None),
        ("FallbackKey", "TEXT", 255),
    ]
    _ensure_table(table_path, fields_spec)
    field_names_list = [f[0] for f in fields_spec]
    _insert_rows(table_path, field_names_list, unresolved_rows)
    return table_path


def _export_ambiguous_writeback_audit(segments_fc, ambiguous_rows):
    table_path = os.path.join(os.path.dirname(segments_fc), "QC_Writeback_AmbiguousKeys")
    fields_spec = [
        ("FallbackTier", "TEXT", 40),
        ("KeyFields", "TEXT", 160),
        ("FallbackKey", "TEXT", 255),
        ("SummaryCount", "LONG", None),
        ("TargetCount", "LONG", None),
        ("SummarySegOIDs", "TEXT", 255),
        ("TargetObjectIDs", "TEXT", 255),
    ]
    _ensure_table(table_path, fields_spec)
    field_names_list = [f[0] for f in fields_spec]
    _insert_rows(table_path, field_names_list, ambiguous_rows)
    return table_path
def write_directional_summary_back(segments_fc, seg_summary_table):
    if not seg_summary_table or not arcpy.Exists(seg_summary_table):
        msg("    -> Directional writeback skipped; no segment summary table available")
        return {
            "summary_rows": 0,
            "direct_matches": 0,
            "fallback_matches": 0,
            "ambiguous_fallback_keys": 0,
            "unresolved_rows": 0,
            "already_matching": 0,
            "unresolved_audit_table": None,
            "ambiguous_audit_table": None,
        }

    target_fields = [
        "Signal_M", "SegMid_M", "Delta_M", "Side_Code", "Flow_Role", "DirSource",
        "OracleMatchStatus", "OracleMatchLevel", "OracleTMSLINKID", "OracleRouteNm",
        "OracleBeginNode", "OracleEndNode", "OracleLinkSequence", "OracleRouteMP",
        "OracleAADT", "OracleDirBasis", "IntersectionNode", "IntersectionNodeBasis",
        "OracleNodeRelation", "AADT_Source", "QC_OracleNoMatch", "QC_OracleAmbiguous",
        "QC_NodeMissing", "QC_RouteMismatch", "QC_AADTConflict",
    ]

    add_final_schema_defaults(segments_fc)

    seg_fields = set(field_names(seg_summary_table, cached=False))
    cnt_fields = [
        f for f in seg_fields
        if f.upper().startswith("CNT_") and f.upper() not in {"CNT_ACCESS"}
    ]
    for fname in cnt_fields:
        ensure_field(segments_fc, fname, "LONG")
    for fname in cnt_fields:
        if fname not in target_fields:
            target_fields.append(fname)

    keep_fields = [f for f in target_fields if f in seg_fields]
    lookup_fields = [
        f for f in [
            "SegOID", "SignalOID", "ParentRoadOID", "LinkID_Norm", "RouteID_Norm",
            "FromNode_Norm", "ToNode_Norm", "RouteNm_Norm"
        ] if f in seg_fields
    ]
    read_fields = lookup_fields + keep_fields
    if "SegOID" not in read_fields:
        raise RuntimeError("SegDirSummary_Stage3 is missing required field SegOID for writeback")

    fallback_tiers = [
        ("tier1_link_route_nodes", ["LinkID_Norm", "RouteID_Norm", "FromNode_Norm", "ToNode_Norm"]),
        ("tier2_link_route_from", ["LinkID_Norm", "RouteID_Norm", "FromNode_Norm"]),
        ("tier3_link_route_to", ["LinkID_Norm", "RouteID_Norm", "ToNode_Norm"]),
        ("tier4_link_route", ["LinkID_Norm", "RouteID_Norm"]),
    ]

    summary_row_count = 0
    direct_payload = {}
    summary_records = []
    summary_index = {tier_name: {} for tier_name, _ in fallback_tiers}
    with arcpy.da.SearchCursor(seg_summary_table, read_fields) as cur:
        for values in cur:
            summary_row_count += 1
            rec = dict(zip(read_fields, values))
            seg_oid = _safe_int(rec.get("SegOID"))
            if seg_oid is not None and seg_oid not in direct_payload:
                direct_payload[seg_oid] = {f: rec.get(f) for f in keep_fields}
            summary_records.append(rec)
            for tier_name, tier_fields in fallback_tiers:
                if all(f in rec for f in tier_fields):
                    key = _fallback_key_tuple(rec, tier_fields)
                    if _key_is_complete(key):
                        summary_index[tier_name].setdefault(key, []).append(rec)

    target_lookup_fields = [
        f for f in [
            "OBJECTID", "SegOID", "SegStableID", "SignalOID", "ParentRoadOID", "LinkID_Norm",
            "RouteID_Norm", "FromNode_Norm", "ToNode_Norm", "RouteNm_Norm"
        ] if f in field_names(segments_fc)
    ]
    update_fields = target_lookup_fields + keep_fields

    target_rows_for_index = []
    with arcpy.da.SearchCursor(segments_fc, target_lookup_fields) as cur:
        for values in cur:
            target_rows_for_index.append(dict(zip(target_lookup_fields, values)))

    target_index = {tier_name: {} for tier_name, _ in fallback_tiers}
    for row in target_rows_for_index:
        for tier_name, tier_fields in fallback_tiers:
            if all(f in row for f in tier_fields):
                key = _fallback_key_tuple(row, tier_fields)
                if _key_is_complete(key):
                    target_index[tier_name].setdefault(key, []).append(row)

    ambiguous_diagnostics = []
    unique_fallback = {tier_name: {} for tier_name, _ in fallback_tiers}
    ambiguous_pairs = set()
    for tier_name, tier_fields in fallback_tiers:
        summary_keys = summary_index[tier_name]
        target_keys = target_index[tier_name]
        for key in sorted(set(summary_keys) | set(target_keys), key=lambda k: tuple('' if v is None else str(v) for v in k)):
            srows = summary_keys.get(key, [])
            trows = target_keys.get(key, [])
            if len(srows) == 1 and len(trows) == 1:
                unique_fallback[tier_name][key] = {f: srows[0].get(f) for f in keep_fields}
            elif len(srows) > 1 or len(trows) > 1:
                ambiguous_pairs.add((tier_name, key))
                ambiguous_diagnostics.append({
                    "FallbackTier": tier_name,
                    "KeyFields": ", ".join(tier_fields),
                    "FallbackKey": _key_to_text(tier_fields, key),
                    "SummaryCount": len(srows),
                    "TargetCount": len(trows),
                    "SummarySegOIDs": ", ".join(str(_safe_int(r.get("SegOID"))) for r in srows[:20] if _safe_int(r.get("SegOID")) is not None),
                    "TargetObjectIDs": ", ".join(str(_safe_int(r.get("OBJECTID"))) for r in trows[:20] if _safe_int(r.get("OBJECTID")) is not None),
                })

    direct_matches = 0
    fallback_matches = 0
    unresolved_rows = 0
    already_matching = 0
    unresolved_audit_rows = []

    with arcpy.da.UpdateCursor(segments_fc, update_fields) as cur:
        for values in cur:
            row = dict(zip(update_fields, values))
            objectid = _safe_int(row.get("OBJECTID"))
            target_seg_oid = _safe_int(row.get("SegOID"))
            target_seg_stable = _safe_int(row.get("SegStableID"))
            payload = None
            direct_key_used = None
            for candidate_key in (target_seg_stable, target_seg_oid, objectid):
                if candidate_key is None:
                    continue
                payload = direct_payload.get(candidate_key)
                if payload is not None:
                    direct_key_used = candidate_key
                    break
            matched_via = None
            matched_tier = None
            unresolved_reason = None
            candidate_count = 0
            key_text = None

            if payload is not None:
                matched_via = "direct"
            else:
                for tier_name, tier_fields in fallback_tiers:
                    if not all(f in row for f in tier_fields):
                        continue
                    key = _fallback_key_tuple(row, tier_fields)
                    if not _key_is_complete(key):
                        continue
                    key_text = _key_to_text(tier_fields, key)
                    tcount = len(target_index[tier_name].get(key, []))
                    scount = len(summary_index[tier_name].get(key, []))
                    if key in unique_fallback[tier_name]:
                        payload = unique_fallback[tier_name][key]
                        matched_via = "fallback"
                        matched_tier = tier_name
                        break
                    if (tier_name, key) in ambiguous_pairs:
                        candidate_count = max(tcount, scount)
                        unresolved_reason = "AmbiguousFallbackKey"
                        matched_tier = tier_name
                        break
                if payload is None and unresolved_reason is None:
                    has_min_key = _key_is_complete(_fallback_key_tuple(row, ["LinkID_Norm", "RouteID_Norm"])) if all(f in row for f in ["LinkID_Norm", "RouteID_Norm"]) else False
                    unresolved_reason = "NoUniqueFallbackMatch" if has_min_key else "MissingFallbackKeyFields"

            if payload is None:
                unresolved_rows += 1
                unresolved_audit_rows.append({
                    "SegmentObjectID": objectid,
                    "Reason": unresolved_reason,
                    "FallbackTier": matched_tier,
                    "CandidateCount": candidate_count,
                    "LinkID_Norm": row.get("LinkID_Norm"),
                    "RouteID_Norm": row.get("RouteID_Norm"),
                    "FromNode_Norm": row.get("FromNode_Norm"),
                    "ToNode_Norm": row.get("ToNode_Norm"),
                    "SignalOID": _safe_int(row.get("SignalOID")),
                    "ParentRoadOID": _safe_int(row.get("ParentRoadOID")),
                    "SegOID": _safe_int(row.get("SegOID")),
                    "FallbackKey": key_text,
                })
                continue

            if _rows_match_on_existing_payload(row, payload, keep_fields):
                already_matching += 1
                continue

            new_row = list(values)
            changed = False
            for idx, field_name in enumerate(update_fields[len(target_lookup_fields):], start=len(target_lookup_fields)):
                payload_val = payload.get(field_name)
                if new_row[idx] != payload_val:
                    new_row[idx] = payload_val
                    changed = True
            if changed:
                cur.updateRow(new_row)
                if matched_via == "direct":
                    direct_matches += 1
                else:
                    fallback_matches += 1
            else:
                already_matching += 1

    unresolved_table = _export_unresolved_writeback_audit(segments_fc, unresolved_audit_rows)
    ambiguous_table = _export_ambiguous_writeback_audit(segments_fc, ambiguous_diagnostics)

    msg(f"    -> Directional writeback summary rows: {summary_row_count}")
    msg(f"    -> Directional writeback direct stable-id/SegOID/OBJECTID matches applied: {direct_matches}")
    msg(f"    -> Directional writeback fallback canonical matches applied: {fallback_matches}")
    msg(f"    -> Directional writeback ambiguous fallback keys: {len(ambiguous_diagnostics)}")
    msg(f"    -> Directional writeback unresolved rows after fallback: {unresolved_rows}")
    msg(f"    -> Directional writeback unresolved audit table: {unresolved_table}")
    msg(f"    -> Directional writeback ambiguous-key audit table: {ambiguous_table}")

    return {
        "summary_rows": summary_row_count,
        "direct_matches": direct_matches,
        "fallback_matches": fallback_matches,
        "ambiguous_fallback_keys": len(ambiguous_diagnostics),
        "unresolved_rows": unresolved_rows,
        "already_matching": already_matching,
        "unresolved_audit_table": unresolved_table,
        "ambiguous_audit_table": ambiguous_table,
    }
