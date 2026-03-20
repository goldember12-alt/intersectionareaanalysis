# -*- coding: utf-8 -*-
"""
Missing-only backfill logic for roads and segments.
"""

import os
import re
import time

import config as cfg
from config import *
from logging_utils import msg, log_phase_time
from arcpy_utils import (
    ensure_field, field_map_upper, pick_field, safe_make_layer, delete_if_exists,
    find_segment_inherited_field, _make_backfill_fieldmap, _subset_where_missing_expr
)
from field_normalization import (
    normalize_linkid_value, field_is_blank, numeric_field_is_missing,
    calculate_link_missing_flag, detect_best_source_field, summarize_missing_counts,
    log_missing_counts, fill_missing_fields_from_source_by_spatial_join,
    _normalize_text_value, _normalize_long_value, resolve_source_field,
    audit_canonical_mapping, log_canonical_gap_audit
)

def transfer_aadt_fields_missing_only(target_fc, aadt_fc, target_label="targets"):
    """
    Missing-only AADT backfill in two tiers:
      1) LinkID_Norm only
      2) AADT / RouteID_Norm / DirCode_Norm only where still missing

    Performance notes:
    - feeds the missing-only layer directly into SpatialJoin instead of CopyFeatures
    - reads the joined subset once and updates only eligible target rows
    - does not JoinField raw source columns back onto the full target FC
    """
    ensure_field(target_fc, "LinkID_Norm", "TEXT", 80)
    ensure_field(target_fc, "AADT", "LONG")
    ensure_field(target_fc, "RouteID_Norm", "TEXT", 80)
    ensure_field(target_fc, "DirCode_Norm", "TEXT", 40)

    aadt_names_upper = field_map_upper(aadt_fc)
    link_field_aadt = pick_field(aadt_fc, CANDIDATE_FIELDS["link_id"], required=True, names_upper=aadt_names_upper)
    aadt_field_aadt = pick_field(aadt_fc, CANDIDATE_FIELDS["aadt"], required=False, names_upper=aadt_names_upper)
    route_field_aadt = pick_field(aadt_fc, ["MASTER_RTE_NM", "RTE_NM"], required=False, names_upper=aadt_names_upper)
    dir_field_aadt = pick_field(aadt_fc, ["DIRECTIONALITY"], required=False, names_upper=aadt_names_upper)

    total_updates = 0
    target_oid_field = arcpy.Describe(target_fc).OIDFieldName

    def _run_tier(tier_name, subset_where, join_fields, fill_specs):
        nonlocal total_updates
        if not subset_where:
            msg(f"    -> {tier_name}: no eligible fields to evaluate")
            return

        subset_lyr = safe_make_layer(target_fc, subset_where)
        join_fc = os.path.join(arcpy.env.scratchGDB, make_unique_name(f"{tier_name.lower()}_join"))
        delete_if_exists(join_fc)

        try:
            subset_count = int(arcpy.management.GetCount(subset_lyr)[0])
            if subset_count == 0:
                msg(f"    -> {tier_name}: no {target_label} require backfill")
                return

            msg(f"    -> {tier_name}: {subset_count:,} {target_label} require backfill")
            fmap = _make_backfill_fieldmap(subset_lyr, target_oid_field, aadt_fc, join_fields)

            t = time.time()
            arcpy.analysis.SpatialJoin(
                target_features=subset_lyr,
                join_features=aadt_fc,
                out_feature_class=join_fc,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                field_mapping=fmap,
                match_option="INTERSECT",
                search_radius=AADT_TRANSFER_SEARCH_RADIUS
            )
            log_phase_time(f"{tier_name} - spatial join creation", t)

            names_upper = field_map_upper(join_fc, cached=False)
            joined_value_fields = {"TARGET_OID": pick_field(join_fc, ["TARGET_OID"], required=True, names_upper=names_upper)}
            for src_field, _, _, _ in fill_specs:
                if not src_field:
                    continue
                safe = re.sub(r"[^A-Za-z0-9_]", "_", str(src_field)).upper()
                joined_value_fields[src_field] = pick_field(join_fc, [f"SJ_{safe}"], required=False, names_upper=names_upper)

            update_by_oid = {}
            read_fields = [joined_value_fields["TARGET_OID"]] + [
                joined_value_fields.get(src_field)
                for src_field, _, _, _ in fill_specs
                if src_field and joined_value_fields.get(src_field)
            ]
            dedup_fields = []
            for f in read_fields:
                if f and f not in dedup_fields:
                    dedup_fields.append(f)

            if dedup_fields:
                with arcpy.da.SearchCursor(join_fc, dedup_fields) as cur:
                    for row in cur:
                        rec = dict(zip(dedup_fields, row))
                        oid_val = rec.get(joined_value_fields["TARGET_OID"])
                        if oid_val is None:
                            continue
                        oid_val = int(oid_val)
                        payload = update_by_oid.setdefault(oid_val, {})
                        for src_field, _, _, _ in fill_specs:
                            actual = joined_value_fields.get(src_field)
                            if actual and actual in rec and src_field not in payload:
                                payload[src_field] = rec.get(actual)

            update_fields = [target_oid_field]
            for _, dest_field, _, _ in fill_specs:
                if dest_field and dest_field not in update_fields:
                    update_fields.append(dest_field)

            t = time.time()
            updates_here = 0
            if update_by_oid:
                with arcpy.da.UpdateCursor(target_fc, update_fields, subset_where) as cur:
                    for row in cur:
                        oid_val = row[0]
                        src_payload = update_by_oid.get(int(oid_val))
                        if not src_payload:
                            continue
                        changed = False
                        for src_field, dest_field, missing_fn, convert_fn in fill_specs:
                            dest_idx = update_fields.index(dest_field)
                            if src_field not in src_payload:
                                continue
                            src_val = src_payload.get(src_field)
                            if missing_fn(row[dest_idx]) and not field_is_blank(src_val):
                                try:
                                    row[dest_idx] = convert_fn(src_val)
                                    changed = True
                                except Exception:
                                    pass
                        if changed:
                            cur.updateRow(row)
                            updates_here += 1
            total_updates += updates_here
            log_phase_time(f"{tier_name} - targeted update fill", t)
        finally:
            delete_if_exists(subset_lyr)
            delete_if_exists(join_fc)

    _run_tier(
        tier_name="Tier 1 LinkID",
        subset_where=_subset_where_missing_expr(target_fc, include_link=True, include_aadt=False, include_route=False, include_dir=False),
        join_fields=[link_field_aadt],
        fill_specs=[
            (link_field_aadt, "LinkID_Norm", field_is_blank, normalize_linkid_value),
        ]
    )

    _run_tier(
        tier_name="Tier 2 AADT/Route/Dir",
        subset_where=_subset_where_missing_expr(target_fc, include_link=False, include_aadt=True, include_route=True, include_dir=True),
        join_fields=[aadt_field_aadt, route_field_aadt, dir_field_aadt],
        fill_specs=[
            (aadt_field_aadt, "AADT", numeric_field_is_missing, lambda v: int(float(v))),
            (route_field_aadt, "RouteID_Norm", field_is_blank, lambda v: str(v)),
            (dir_field_aadt, "DirCode_Norm", field_is_blank, lambda v: str(v)),
        ]
    )

    if total_updates > 0:
        calculate_link_missing_flag(target_fc)
    msg(f"    -> Missing-only AADT transfer complete: {total_updates:,} value fill operations")


def transfer_linkid_from_aadt_if_missing(roads_fc, aadt_fc):
    field_specs = [("LinkID_Norm", "TEXT"), ("RouteID_Norm", "TEXT"), ("DirCode_Norm", "TEXT"), ("AADT", "LONG")]
    counts_before, total = summarize_missing_counts(roads_fc, field_specs)
    missing_any = sum(counts_before.values())
    if missing_any == 0:
        msg("    -> Road metadata backfill not needed; canonical road metadata already populated")
        return

    msg("    -> Road metadata backfill is enabled for ArcPy and GeoPandas paths alike")
    msg("    -> Road metadata source for missing-only backfill: staged AADT layer")
    log_canonical_gap_audit(
        roads_fc,
        field_specs,
        "Road canonical audit before AADT backfill",
    )

    source_map = {
        "LinkID_Norm": resolve_source_field(aadt_fc, "link_id", prefer_existing_canonical=True),
        "RouteID_Norm": resolve_source_field(aadt_fc, "route_id", prefer_existing_canonical=True),
        "RouteNm_Norm": resolve_source_field(aadt_fc, "route_name", prefer_existing_canonical=True),
        "DirCode_Norm": resolve_source_field(aadt_fc, "dir_code", prefer_existing_canonical=True),
        "AADT": resolve_source_field(aadt_fc, "aadt", prefer_existing_canonical=True),
    }
    audit_canonical_mapping(aadt_fc, source_map, "AADT backfill source")

    subset_where = _subset_where_missing_expr(roads_fc, include_link=True, include_aadt=True, include_route=False, include_dir=False)
    fill_missing_fields_from_source_by_spatial_join(
        roads_fc,
        aadt_fc,
        subset_where,
        [
            (source_map["LinkID_Norm"], "LinkID_Norm", normalize_linkid_value),
            (source_map["RouteID_Norm"], "RouteID_Norm", lambda v: _normalize_text_value(v)),
            (source_map["DirCode_Norm"], "DirCode_Norm", lambda v: _normalize_text_value(v)),
            (source_map["AADT"], "AADT", _normalize_long_value),
        ],
        label="Road metadata backfill",
        search_radius=AADT_TRANSFER_SEARCH_RADIUS,
        match_option="INTERSECT",
    )
    log_missing_counts(
        "Road canonical field status after backfill",
        roads_fc,
        field_specs,
    )
    log_canonical_gap_audit(
        roads_fc,
        field_specs,
        "Road canonical audit after AADT backfill",
    )
    calculate_link_missing_flag(roads_fc)



def enrich_roads_from_aadt(roads_fc, aadt_fc, strict=False, fail_on_missing_required=None, **kwargs):
    """
    Deterministic road metadata enrichment from the staged AADT layer.

    Strategy:
      1) Attribute-key matching first, using the validated shared route-code family
         Travelway.RTE_NM <-> AADT.MASTER_RTE_NM.
      2) For same-route buckets with multiple AADT candidates, use conservative
         measure-based ranking and only accept unique, high-confidence winners.
      3) Spatial join only for residual unmatched roads.

    This preserves correctness by only auto-filling when there is a single route
    candidate or a unique best interval match that passes configured thresholds.
    """
    if fail_on_missing_required is not None:
        strict = bool(fail_on_missing_required)

    field_specs = [("LinkID_Norm", "TEXT"), ("AADT", "LONG"), ("RouteID_Norm", "TEXT"), ("RouteNm_Norm", "TEXT"), ("DirCode_Norm", "TEXT")]
    ensure_field(roads_fc, "LinkID_Norm", "TEXT", 80)
    ensure_field(roads_fc, "AADT", "LONG")
    ensure_field(roads_fc, "RouteID_Norm", "TEXT", 80)
    ensure_field(roads_fc, "RouteNm_Norm", "TEXT", 120)
    ensure_field(roads_fc, "DirCode_Norm", "TEXT", 40)

    msg("    -> Road metadata enrichment from AADT is enabled")
    msg("    -> Road metadata enrichment source: staged AADT layer")

    source_map = {
        "LinkID_Norm": resolve_source_field(aadt_fc, "link_id", prefer_existing_canonical=True),
        "RouteID_Norm": resolve_source_field(aadt_fc, "route_id", prefer_existing_canonical=True),
        "RouteNm_Norm": resolve_source_field(aadt_fc, "route_name", prefer_existing_canonical=True),
        "DirCode_Norm": resolve_source_field(aadt_fc, "dir_code", prefer_existing_canonical=True),
        "AADT": resolve_source_field(aadt_fc, "aadt", prefer_existing_canonical=True),
    }
    audit_canonical_mapping(aadt_fc, source_map, "AADT enrichment source")
    log_canonical_gap_audit(roads_fc, field_specs, "Road canonical audit before AADT enrichment")

    def _canon_route(v):
        v = _normalize_text_value(v)
        if field_is_blank(v):
            return None
        v = str(v).upper().strip()
        v = re.sub(r"\s+", "", v)
        v = re.sub(r"[^A-Z0-9]", "", v)
        return v or None

    def _safe_float(v):
        if v in (None, "", " "):
            return None
        try:
            return float(v)
        except Exception:
            return None

    def _interval_stats(a1, a2, b1, b2):
        if None in (a1, a2, b1, b2):
            return None
        lo_a, hi_a = min(a1, a2), max(a1, a2)
        lo_b, hi_b = min(b1, b2), max(b1, b2)
        len_a = hi_a - lo_a
        len_b = hi_b - lo_b
        overlap = max(0.0, min(hi_a, hi_b) - max(lo_a, lo_b))
        gap = 0.0
        if hi_a < lo_b:
            gap = lo_b - hi_a
        elif hi_b < lo_a:
            gap = lo_a - hi_b
        overlap_ratio_a = overlap / len_a if len_a > 0 else 0.0
        start_diff = abs(lo_a - lo_b)
        end_diff = abs(hi_a - hi_b)
        length_diff = abs(len_a - len_b)
        return {
            "overlap": overlap,
            "gap": gap,
            "overlap_ratio_a": overlap_ratio_a,
            "start_diff": start_diff,
            "end_diff": end_diff,
            "length_diff": length_diff,
        }

    def _confidence_pass(stats_obj):
        if not stats_obj:
            return False
        if stats_obj["overlap"] < ROAD_AADT_ATTRIBUTE_MIN_ABSOLUTE_OVERLAP:
            return False
        if stats_obj["overlap_ratio_a"] < ROAD_AADT_ATTRIBUTE_MIN_OVERLAP_RATIO:
            return False
        if (stats_obj["start_diff"] + stats_obj["end_diff"]) > ROAD_AADT_ATTRIBUTE_MAX_ENDPOINT_SUM_DIFF:
            return False
        return True

    if FORCE_ROADS_AADT_SPATIAL_ONLY:
        msg("    -> Road metadata enrichment attribute tier skipped by debug flag; using spatial-only backfill")
    else:
        msg("    -> Road metadata enrichment attribute tier enabled")

    # Use the validated shared route-code family, not RouteID_Norm / RTE_COMMON.
    aadt_route_key_field = pick_field(aadt_fc, ["MASTER_RTE_NM", "RTE_NM"], required=False)
    aadt_from_measure_field = pick_field(aadt_fc, ["TRANSPORT_EDGE_FROM_MSR", "FROM_MEASURE"], required=False)
    aadt_to_measure_field = pick_field(aadt_fc, ["TRANSPORT_EDGE_TO_MSR", "TO_MEASURE"], required=False)

    road_route_key_field = pick_field(roads_fc, ["RTE_NM", "RouteNm_Norm", "RouteID_Norm"], required=False)
    road_from_measure_field = pick_field(roads_fc, ["RTE_FROM_M", "FROM_MEASURE"], required=False)
    road_to_measure_field = pick_field(roads_fc, ["RTE_TO_MSR", "TO_MEASURE"], required=False)

    t_attr = time.time()
    aadt_by_route = {}
    aadt_samples = []
    aadt_key_rows = 0

    if (not FORCE_ROADS_AADT_SPATIAL_ONLY) and source_map["LinkID_Norm"] and source_map["AADT"] and aadt_route_key_field:
        read_fields = [aadt_route_key_field, aadt_from_measure_field, aadt_to_measure_field, source_map["LinkID_Norm"], source_map["AADT"], source_map["RouteID_Norm"], source_map["RouteNm_Norm"], source_map["DirCode_Norm"]]
        with arcpy.da.SearchCursor(aadt_fc, read_fields) as cur:
            for route_val, from_m, to_m, link_val, aadt_val, route_id_val, route_name_val, dir_val in cur:
                aadt_key_rows += 1
                route_key = _canon_route(route_val)
                if not route_key:
                    continue
                payload = {
                    "LinkID_Norm": normalize_linkid_value(link_val) if not field_is_blank(link_val) else None,
                    "AADT": _normalize_long_value(aadt_val) if not numeric_field_is_missing(aadt_val) else None,
                    "RouteID_Norm": _normalize_text_value(route_id_val),
                    "RouteNm_Norm": _normalize_text_value(route_name_val),
                    "DirCode_Norm": _normalize_text_value(dir_val),
                    "from_m": _safe_float(from_m),
                    "to_m": _safe_float(to_m),
                }
                aadt_by_route.setdefault(route_key, []).append(payload)
                if len(aadt_samples) < 5:
                    aadt_samples.append(f"route={route_key}|from={payload['from_m']}|to={payload['to_m']}")

    unique_route_keys = len(aadt_by_route)
    single_route_keys = sum(1 for vals in aadt_by_route.values() if len(vals) == 1)
    multi_route_keys = unique_route_keys - single_route_keys
    msg(f"    -> Road metadata enrichment attribute tier built {aadt_key_rows:,} AADT records | unique route keys={unique_route_keys:,} | single-candidate route keys={single_route_keys:,} | multi-candidate route keys={multi_route_keys:,}")
    if aadt_samples:
        msg("    -> AADT attribute tier sample route buckets: " + ", ".join(aadt_samples))

    roads_oid = arcpy.Describe(roads_fc).OIDFieldName
    road_link_field = pick_field(roads_fc, ["LinkID_Norm"], required=False)
    road_aadt_field = pick_field(roads_fc, ["AADT"], required=False)
    road_dir_field = pick_field(roads_fc, ["DirCode_Norm"], required=False)

    single_candidate_matches = 0
    unique_measure_matches = 0
    rejected_low_confidence = 0
    tied_measure_matches = 0
    missing_key = 0
    no_match = 0
    road_samples = []

    if (not FORCE_ROADS_AADT_SPATIAL_ONLY) and all([road_link_field, road_aadt_field, road_route_key_field]):
        read_fields = [roads_oid, road_route_key_field, road_from_measure_field, road_to_measure_field, road_dir_field, road_link_field, road_aadt_field]
        with arcpy.da.UpdateCursor(roads_fc, read_fields) as cur:
            for row in cur:
                oid_val, route_val, road_from_m, road_to_m, dir_val, link_val, aadt_val = row
                if not (field_is_blank(link_val) or numeric_field_is_missing(aadt_val)):
                    continue

                route_key = _canon_route(route_val)
                if len(road_samples) < 5:
                    road_samples.append(f"OID {oid_val}: route={route_key or '<none>'}|from={_safe_float(road_from_m)}|to={_safe_float(road_to_m)}")
                if not route_key:
                    missing_key += 1
                    continue

                candidates = aadt_by_route.get(route_key, [])
                if not candidates:
                    no_match += 1
                    continue

                chosen = None
                accepted = False
                if len(candidates) == 1 and ROAD_AADT_ATTRIBUTE_ACCEPT_SINGLE_ROUTE_CANDIDATE:
                    chosen = candidates[0]
                    accepted = True
                    single_candidate_matches += 1
                elif ROAD_AADT_ATTRIBUTE_USE_ROUTE_MEASURES:
                    tw_from = _safe_float(road_from_m)
                    tw_to = _safe_float(road_to_m)
                    scored = []
                    if tw_from is not None and tw_to is not None:
                        for cand in candidates:
                            st = _interval_stats(tw_from, tw_to, cand.get("from_m"), cand.get("to_m"))
                            if st is None:
                                continue
                            score = (
                                -st["overlap_ratio_a"],
                                st["gap"],
                                st["start_diff"] + st["end_diff"],
                                st["length_diff"],
                            )
                            scored.append((score, st, cand))
                    if scored:
                        scored.sort(key=lambda x: x[0])
                        best_score = scored[0][0]
                        best = [x for x in scored if x[0] == best_score]
                        if len(best) == 1:
                            st, cand = best[0][1], best[0][2]
                            if _confidence_pass(st):
                                chosen = cand
                                accepted = True
                                unique_measure_matches += 1
                            else:
                                rejected_low_confidence += 1
                        else:
                            tied_measure_matches += 1
                    else:
                        tied_measure_matches += 1
                else:
                    tied_measure_matches += 1

                if not accepted or not chosen:
                    continue

                changed = False
                if field_is_blank(link_val) and not field_is_blank(chosen.get("LinkID_Norm")):
                    row[5] = chosen.get("LinkID_Norm")
                    changed = True
                if numeric_field_is_missing(aadt_val) and not numeric_field_is_missing(chosen.get("AADT")):
                    row[6] = chosen.get("AADT")
                    changed = True
                if road_dir_field and field_is_blank(dir_val) and not field_is_blank(chosen.get("DirCode_Norm")):
                    row[4] = chosen.get("DirCode_Norm")
                    changed = True
                if changed:
                    cur.updateRow(row)
                else:
                    # Do not count accepted candidates that produced no actual field fill.
                    if len(candidates) == 1 and ROAD_AADT_ATTRIBUTE_ACCEPT_SINGLE_ROUTE_CANDIDATE:
                        single_candidate_matches -= 1
                    elif accepted:
                        unique_measure_matches -= 1

    if road_samples:
        msg("    -> Road attribute tier sample lookup buckets: " + ", ".join(road_samples))
    msg(
        f"    -> Road metadata enrichment - attribute tier completed: {single_candidate_matches + unique_measure_matches:,} roads updated "
        f"({single_candidate_matches:,} single-route candidates, {unique_measure_matches:,} unique route+measure matches)"
    )
    msg(
        f"    -> Road metadata enrichment - attribute tier misses: no-key={missing_key:,} | no-match={no_match:,} | "
        f"tied route+measure={tied_measure_matches:,} | rejected low-confidence={rejected_low_confidence:,}"
    )
    log_phase_time("Road metadata enrichment - attribute tier", t_attr)

    subset_where = _subset_where_missing_expr(roads_fc, include_link=True, include_aadt=True, include_route=False, include_dir=False)
    lyr = safe_make_layer(roads_fc, subset_where)
    try:
        remaining = int(arcpy.management.GetCount(lyr)[0])
    finally:
        delete_if_exists(lyr)

    msg(f"    -> Road metadata enrichment: {remaining:,} records still require spatial backfill after attribute tier")
    if remaining > 0:
        fill_missing_fields_from_source_by_spatial_join(
            roads_fc,
            aadt_fc,
            subset_where,
            [
                (source_map["LinkID_Norm"], "LinkID_Norm", normalize_linkid_value),
                (source_map["AADT"], "AADT", _normalize_long_value),
                (source_map["RouteID_Norm"], "RouteID_Norm", lambda v: _normalize_text_value(v)),
                (source_map["RouteNm_Norm"], "RouteNm_Norm", lambda v: _normalize_text_value(v)),
                (source_map["DirCode_Norm"], "DirCode_Norm", lambda v: _normalize_text_value(v)),
            ],
            label="Road metadata enrichment",
            search_radius=AADT_TRANSFER_SEARCH_RADIUS,
            match_option="INTERSECT",
        )
    else:
        msg("    -> Road metadata enrichment - spatial tier skipped; attribute tier satisfied all missing roads")

    log_missing_counts("Road canonical field status after AADT enrichment", roads_fc, field_specs)
    log_canonical_gap_audit(roads_fc, field_specs, "Road canonical audit after AADT enrichment")
    calculate_link_missing_flag(roads_fc)

    if strict:
        counts_after, total = summarize_missing_counts(roads_fc, field_specs)
        hard_fail = {k: v for k, v in counts_after.items() if k in ("LinkID_Norm", "AADT") and v > 0}
        if hard_fail:
            detail = ", ".join(f"{k}={v:,}" for k, v in hard_fail.items())
            raise RuntimeError(f"AADT enrichment left required road metadata missing: {detail}")

def enrich_segments_from_parent_fields_if_missing(segments_fc):
    wanted = [
        ("LinkID_Norm", "TEXT", 80),
        ("AADT", "LONG", None),
        ("RouteID_Norm", "TEXT", 80),
        ("DirCode_Norm", "TEXT", 40),
        ("FromNode_Norm", "TEXT", 80),
        ("ToNode_Norm", "TEXT", 80),
    ]
    for n, t, l in wanted:
        ensure_field(segments_fc, n, t, l)

    source_map = {}
    for dest, _, _ in wanted:
        src = find_segment_inherited_field(segments_fc, dest)
        if not src or src == dest:
            if dest == "AADT":
                src = resolve_source_field(segments_fc, "aadt", prefer_existing_canonical=False)
            elif dest == "LinkID_Norm":
                src = resolve_source_field(segments_fc, "link_id", prefer_existing_canonical=False)
            elif dest == "RouteID_Norm":
                src = resolve_source_field(segments_fc, "route_id", prefer_existing_canonical=False)
            elif dest == "DirCode_Norm":
                src = resolve_source_field(segments_fc, "dir_code", prefer_existing_canonical=False)
            elif dest == "FromNode_Norm":
                src = resolve_source_field(segments_fc, "from_node", prefer_existing_canonical=False)
            elif dest == "ToNode_Norm":
                src = resolve_source_field(segments_fc, "to_node", prefer_existing_canonical=False)
        if src == dest:
            src = None
        source_map[dest] = src
        msg(f"    -> Segment inheritance source for {dest}: {src if src else '<none>'}")

    cursor_fields = []
    for src in source_map.values():
        if src and src not in cursor_fields:
            cursor_fields.append(src)
    for dest in source_map.keys():
        if dest not in cursor_fields:
            cursor_fields.append(dest)
    idx = {f: i for i, f in enumerate(cursor_fields)}
    updates = 0
    with arcpy.da.UpdateCursor(segments_fc, cursor_fields) as cur:
        for row in cur:
            changed = False
            for dest, src in source_map.items():
                if not src:
                    continue
                src_val = row[idx[src]]
                if dest == "AADT":
                    if numeric_field_is_missing(row[idx[dest]]) and not numeric_field_is_missing(src_val):
                        row[idx[dest]] = _normalize_long_value(src_val)
                        changed = True
                else:
                    if field_is_blank(row[idx[dest]]) and not field_is_blank(src_val):
                        row[idx[dest]] = _normalize_text_value(src_val)
                        changed = True
            if changed:
                cur.updateRow(row)
                updates += 1
    msg(f"    -> Segment inheritance from parent/claim fields updated {updates:,} segment records")
    calculate_link_missing_flag(segments_fc)
    log_missing_counts(
        "Segment canonical field status after direct inheritance",
        segments_fc,
        [("LinkID_Norm", "TEXT"), ("RouteID_Norm", "TEXT"), ("DirCode_Norm", "TEXT"), ("FromNode_Norm", "TEXT"), ("ToNode_Norm", "TEXT"), ("AADT", "LONG")]
    )
    log_canonical_gap_audit(
        segments_fc,
        [("LinkID_Norm", "TEXT"), ("RouteID_Norm", "TEXT"), ("DirCode_Norm", "TEXT"), ("FromNode_Norm", "TEXT"), ("ToNode_Norm", "TEXT"), ("AADT", "LONG")],
        "Segment canonical audit after direct inheritance",
        expected_missing_override={"FromNode_Norm", "ToNode_Norm"},
    )

def backfill_segment_aadt_fields_only_if_missing(segments_fc, aadt_fc, roads_fc=None):
    enrich_segments_from_parent_fields_if_missing(segments_fc)
    field_specs = [("LinkID_Norm", "TEXT"), ("RouteID_Norm", "TEXT"), ("DirCode_Norm", "TEXT"), ("AADT", "LONG")]
    counts_before, total = summarize_missing_counts(segments_fc, field_specs)
    subset_where = _subset_where_missing_expr(segments_fc, include_link=True, include_aadt=True, include_route=True, include_dir=True)
    if not subset_where:
        return

    lyr = safe_make_layer(segments_fc, subset_where)
    try:
        need_cnt = int(arcpy.management.GetCount(lyr)[0])
    finally:
        delete_if_exists(lyr)

    if need_cnt == 0:
        msg("    -> Segment fallback skipped; direct inheritance already populated canonical fields")
        return

    severity = (float(need_cnt) / float(total)) if total else 0.0
    log_canonical_gap_audit(
        segments_fc,
        field_specs,
        "Segment canonical audit before fallback",
    )

    if severity >= 0.25:
        msg(f"    ! Segment fallback is systemic ({need_cnt:,} of {total:,}); upstream metadata propagation is still being repaired")
    else:
        msg(f"    -> Segment fallback is exceptional ({need_cnt:,} of {total:,})")

    if roads_fc and arcpy.Exists(roads_fc):
        msg("    -> First fallback tier uses study roads canonical metadata, not AADT, for missing segment identity fields")
        fill_missing_fields_from_source_by_spatial_join(
            segments_fc,
            roads_fc,
            subset_where,
            [
                (pick_field(roads_fc, ["LinkID_Norm"], required=False), "LinkID_Norm", normalize_linkid_value),
                (pick_field(roads_fc, ["RouteID_Norm"], required=False), "RouteID_Norm", lambda v: _normalize_text_value(v)),
                (pick_field(roads_fc, ["DirCode_Norm"], required=False), "DirCode_Norm", lambda v: _normalize_text_value(v)),
                (pick_field(roads_fc, ["FromNode_Norm"], required=False), "FromNode_Norm", lambda v: _normalize_text_value(v)),
                (pick_field(roads_fc, ["ToNode_Norm"], required=False), "ToNode_Norm", lambda v: _normalize_text_value(v)),
                (pick_field(roads_fc, ["AADT"], required=False), "AADT", _normalize_long_value),
            ],
            label="Segment fallback tier 1 from roads",
            search_radius="5 Feet",
            match_option="INTERSECT",
        )

        if pick_field(roads_fc, ["FromNode_Norm"], required=False) or pick_field(roads_fc, ["ToNode_Norm"], required=False):
            names_upper = field_map_upper(segments_fc)
            node_parts = []
            for fld_name in ["FromNode_Norm", "ToNode_Norm"]:
                real_name = names_upper.get(fld_name.upper())
                if real_name:
                    fld = arcpy.AddFieldDelimiters(segments_fc, real_name)
                    node_parts.append(f"({fld} IS NULL OR {fld} = '' OR {fld} = ' ')")
            subset_nodes = " OR ".join(node_parts) if node_parts else None
            if subset_nodes:
                msg("    -> Dedicated node-field backfill from study roads for segments still missing From/To nodes")
                fill_missing_fields_from_source_by_spatial_join(
                    segments_fc,
                    roads_fc,
                    subset_nodes,
                    [
                        (pick_field(roads_fc, ["FromNode_Norm"], required=False), "FromNode_Norm", lambda v: _normalize_text_value(v)),
                        (pick_field(roads_fc, ["ToNode_Norm"], required=False), "ToNode_Norm", lambda v: _normalize_text_value(v)),
                    ],
                    label="Segment node backfill from roads",
                    search_radius="5 Feet",
                    match_option="INTERSECT",
                )

    subset_where2 = _subset_where_missing_expr(segments_fc, include_link=True, include_aadt=True, include_route=True, include_dir=True)
    if subset_where2:
        msg("    -> Second fallback tier uses AADT only for records still missing canonical metadata")
        fill_missing_fields_from_source_by_spatial_join(
            segments_fc,
            aadt_fc,
            subset_where2,
            [
                (resolve_source_field(aadt_fc, "link_id", prefer_existing_canonical=True), "LinkID_Norm", normalize_linkid_value),
                (resolve_source_field(aadt_fc, "route_id", prefer_existing_canonical=True), "RouteID_Norm", lambda v: _normalize_text_value(v)),
                (resolve_source_field(aadt_fc, "dir_code", prefer_existing_canonical=True), "DirCode_Norm", lambda v: _normalize_text_value(v)),
                (resolve_source_field(aadt_fc, "aadt", prefer_existing_canonical=True), "AADT", _normalize_long_value),
            ],
            label="Segment fallback tier 2 from AADT",
            search_radius=AADT_TRANSFER_SEARCH_RADIUS,
            match_option="INTERSECT",
        )

    log_missing_counts(
        "Segment canonical field status after fallback",
        segments_fc,
        field_specs,
    )
    log_canonical_gap_audit(
        segments_fc,
        field_specs,
        "Segment canonical audit after fallback",
    )
    calculate_link_missing_flag(segments_fc)
