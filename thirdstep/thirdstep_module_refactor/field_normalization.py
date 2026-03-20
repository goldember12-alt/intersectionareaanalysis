# -*- coding: utf-8 -*-
"""
Canonical field normalization for thirdstep.

Redesigned to be schema-role driven instead of feature-class-name driven.
The main goal is to make roadway canonicalization deterministic for Travelway-
derived study roads and to stop accidentally treating staged canonical fields as
source fields.
"""

import re
import time

import config as cfg
from config import *
from logging_utils import msg, log_phase_time
from arcpy_utils import (
    ensure_field, field_names, field_map_upper, pick_field,
    invalidate_field_cache, safe_make_layer, delete_if_exists, make_unique_name,
    _make_backfill_fieldmap, safe_field_name
)


CANONICAL_FIELD_TO_LOGICAL_KEY = {
    "LinkID_Norm": "link_id",
    "RouteID_Norm": "route_id",
    "RouteNm_Norm": "route_name",
    "DirCode_Norm": "dir_code",
    "FromNode_Norm": "from_node",
    "ToNode_Norm": "to_node",
    "AADT": "aadt",
}


# Explicit, role-based source mappings. These are keyed by the semantic role of
# the dataset in the pipeline, not by the temporary feature class name.
ROLE_BASED_SOURCE_FIELDS = {
    "TRAVELWAY": {
        "RouteID_Norm": ["RTE_ID"],
        "RouteNm_Norm": ["RTE_COMMON", "RTE_NM"],
        "DirCode_Norm": ["LOC_COMP_D"],
        "LinkID_Norm": [],
        "FromNode_Norm": [],
        "ToNode_Norm": [],
        "AADT": [],
    },
    "NEW_AADT": {
        "LinkID_Norm": ["LINKID"],
        "RouteID_Norm": ["MASTER_RTE_NM", "RTE_NM"],
        "RouteNm_Norm": ["MASTER_RTE_NM", "RTE_NM"],
        "DirCode_Norm": ["DIRECTIONALITY"],
        "FromNode_Norm": [],
        "ToNode_Norm": [],
        "AADT": ["AADT"],
    },
}


REQUIRED_FIELDS_BY_ROLE = {
    # What we expect to be fully populated immediately after direct
    # normalization from that source role.
    "TRAVELWAY": ["ParentRoadOID", "RouteID_Norm", "RouteNm_Norm", "DirCode_Norm"],
    "NEW_AADT": ["LinkID_Norm", "RouteID_Norm", "DirCode_Norm", "AADT"],
}


OPTIONAL_FIELDS_BY_ROLE = {
    "TRAVELWAY": ["LinkID_Norm", "FromNode_Norm", "ToNode_Norm", "AADT"],
    "NEW_AADT": ["FromNode_Norm", "ToNode_Norm"],
}


TEXT_CANONICAL_FIELDS = [
    "LinkID_Norm", "RouteID_Norm", "RouteNm_Norm",
    "DirCode_Norm", "FromNode_Norm", "ToNode_Norm"
]

NUMERIC_CANONICAL_FIELDS = ["AADT"]


def normalize_linkid_value(v):
    if v in (None, "", " "):
        return ""
    return str(v).strip()


def field_is_blank(val):
    return val in (None, "", " ")


def numeric_field_is_missing(val):
    return val in (None, "", " ", 0)


def calculate_link_missing_flag(fc, link_field="LinkID_Norm", qc_field="QC_LinkMissing"):
    names_upper = field_map_upper(fc)
    if link_field.upper() not in names_upper:
        return
    ensure_field(fc, qc_field, "SHORT")
    expr = f"0 if !{link_field}! not in (None, '', ' ') else 1"
    arcpy.management.CalculateField(fc, qc_field, expr, "PYTHON3")


def _normalize_text_value(v):
    if v in (None, "", " "):
        return ""
    return str(v).strip()


def _normalize_long_value(v):
    if v in (None, "", " "):
        return None
    try:
        return int(round(float(v)))
    except Exception:
        return None


def _field_profiles(fc):
    profiles = []
    for f in arcpy.ListFields(fc):
        profiles.append({
            "name": f.name,
            "alias": getattr(f, "aliasName", "") or "",
            "type": getattr(f, "type", "") or "",
        })
    return profiles


def _norm_key(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _tokenize_key(s):
    return [t for t in re.split(r"[^A-Z0-9]+", str(s or "").upper()) if t]


def _canonical_field_exists(fc, fld_name):
    return fld_name.upper() in field_map_upper(fc)


def _ensure_canonical_road_fields(fc):
    ensure_field(fc, "ParentRoadOID", "LONG")
    ensure_field(fc, "LinkID_Norm", "TEXT", 80)
    ensure_field(fc, "RouteID_Norm", "TEXT", 80)
    ensure_field(fc, "RouteNm_Norm", "TEXT", 120)
    ensure_field(fc, "DirCode_Norm", "TEXT", 40)
    ensure_field(fc, "FromNode_Norm", "TEXT", 80)
    ensure_field(fc, "ToNode_Norm", "TEXT", 80)
    ensure_field(fc, "AADT", "LONG")
    invalidate_field_cache(fc)


def get_role_source_map(role):
    return dict(ROLE_BASED_SOURCE_FIELDS.get((role or "").upper(), {}))


def get_required_fields_for_role(role):
    return list(REQUIRED_FIELDS_BY_ROLE.get((role or "").upper(), []))


def get_optional_fields_for_role(role):
    return list(OPTIONAL_FIELDS_BY_ROLE.get((role or "").upper(), []))


def get_explicit_layer_field_map(fc=None, role=None):
    if role:
        role_map = get_role_source_map(role)
        return {
            CANONICAL_FIELD_TO_LOGICAL_KEY[k]: list(v)
            for k, v in role_map.items()
            if k in CANONICAL_FIELD_TO_LOGICAL_KEY
        }

    # Backward-compatible fallback for callers that still expect config-driven
    # layer maps. This is intentionally secondary to the role-based registry.
    raw = getattr(cfg, "EXPLICIT_NORMALIZATION_SOURCE_FIELDS", {})
    if not fc:
        return {}
    variants = set()
    try:
        desc = arcpy.Describe(fc)
        for attr in ("baseName", "name", "catalogPath"):
            v = str(getattr(desc, attr, "") or "").strip()
            if v:
                variants.add(v.upper())
    except Exception:
        pass
    try:
        variants.add(str(fc).strip().upper())
    except Exception:
        pass
    for name in variants:
        if name in raw:
            return dict(raw.get(name, {}))
    return {}


def get_expected_missing_canonical_fields(fc=None, role=None):
    if role:
        return set(get_optional_fields_for_role(role))

    raw = getattr(cfg, "EXPECTED_MISSING_CANONICAL_FIELDS", {})
    if not fc:
        return set()
    variants = set()
    try:
        desc = arcpy.Describe(fc)
        for attr in ("baseName", "name", "catalogPath"):
            v = str(getattr(desc, attr, "") or "").strip()
            if v:
                variants.add(v.upper())
    except Exception:
        pass
    try:
        variants.add(str(fc).strip().upper())
    except Exception:
        pass
    for name in variants:
        if name in raw:
            return set(raw.get(name, set()))
    return set()

def resolve_source_field(fc, logical_key, prefer_existing_canonical=True, role=None):
    role = (role or "").upper()
    if role:
        role_map = get_role_source_map(role)
        canonical_field = next((k for k, v in CANONICAL_FIELD_TO_LOGICAL_KEY.items() if v == logical_key), None)
        if canonical_field in role_map:
            candidates = list(role_map.get(canonical_field, []))
            chosen = pick_field(fc, candidates, required=False) if candidates else None
            if chosen:
                return chosen

    explicit_map = get_explicit_layer_field_map(fc)
    explicit_candidates = list(explicit_map.get(logical_key, [])) if explicit_map else []
    if explicit_candidates:
        chosen = pick_field(fc, explicit_candidates, required=False)
        if chosen:
            return chosen
    return detect_best_source_field(fc, logical_key, prefer_existing_canonical=prefer_existing_canonical)

def audit_canonical_mapping(fc, source_map, label, role=None, required_fields=None):
    expected_missing = set(get_expected_missing_canonical_fields(fc, role=role))
    required_fields = set(required_fields or [])
    msg(f"    -> {label} field-mapping audit")
    for dest, src in source_map.items():
        if src:
            status = "direct-source"
        elif dest in expected_missing:
            status = "expected-missing"
        elif required_fields and dest not in required_fields:
            status = "informational-only"
        else:
            status = "unexpected-missing"
        msg(f"       {dest}: {src if src else '<none>'} [{status}]")


def summarize_missing_counts(fc, field_specs):
    counts = {dest: 0 for dest, _ in field_specs}
    total = 0
    fields = [dest for dest, _ in field_specs if pick_field(fc, [dest], required=False)]
    if not fields:
        return counts, total
    with arcpy.da.SearchCursor(fc, fields) as cur:
        for row in cur:
            total += 1
            for idx, dest in enumerate(fields):
                val = row[idx]
                if dest == "AADT":
                    if numeric_field_is_missing(val):
                        counts[dest] += 1
                else:
                    if field_is_blank(val):
                        counts[dest] += 1
    return counts, total


def log_missing_counts(prefix, fc, field_specs):
    counts, total = summarize_missing_counts(fc, field_specs)
    detail = ", ".join([f"{k} missing={counts.get(k, 0):,}" for k, _ in field_specs])
    msg(f"    -> {prefix}: total={total:,} | {detail}")
    return counts, total


def log_canonical_gap_audit(fc, field_specs, label, role=None, expected_missing_override=None):
    counts, total = summarize_missing_counts(fc, field_specs)
    expected_missing = set(get_expected_missing_canonical_fields(fc, role=role))
    if expected_missing_override:
        expected_missing |= set(expected_missing_override)
    expected_total = 0
    unexpected_total = 0
    informational_total = 0
    parts = []
    for dest, _ in field_specs:
        miss = counts.get(dest, 0)
        if miss == 0:
            informational_total += 1
            bucket = "informational-zero"
        else:
            bucket = "expected" if dest in expected_missing else "unexpected"
            if bucket == "expected":
                expected_total += miss
            else:
                unexpected_total += miss
        parts.append(f"{dest}={miss:,} ({bucket})")
    msg(f"    -> {label}: total={total:,} | expected-missing={expected_total:,} | unexpected-missing={unexpected_total:,} | informational-fields={informational_total:,}")
    msg("       Detail: " + ", ".join(parts))
    return counts, total


def detect_best_source_field(fc, logical_key, prefer_existing_canonical=True):
    profiles = _field_profiles(fc)
    available = {p["name"].upper(): p["name"] for p in profiles}

    exact_candidates = list(CANDIDATE_FIELDS.get(logical_key, [])) + list(ROAD_FIELD_EXTRA_CANDIDATES.get(logical_key, []))
    canonical_name = {
        "link_id": "LinkID_Norm",
        "route_id": "RouteID_Norm",
        "route_name": "RouteNm_Norm",
        "dir_code": "DirCode_Norm",
        "from_node": "FromNode_Norm",
        "to_node": "ToNode_Norm",
        "aadt": "AADT",
    }.get(logical_key)

    # The redesign defaults away from using already-created canonical fields as
    # sources, because that caused self-referential null propagation on staged
    # feature classes. Existing canonical fields are only considered when the
    # caller explicitly asks for them.
    if prefer_existing_canonical and canonical_name:
        exact_candidates = [canonical_name] + exact_candidates

    exact_norm = [_norm_key(x) for x in exact_candidates if x]
    token_hints = ROAD_FIELD_TOKEN_HINTS.get(logical_key, [])
    exclude = set(ROAD_FIELD_EXCLUDE_TOKENS.get(logical_key, set()))

    if not prefer_existing_canonical and canonical_name:
        exclude = set(exclude) | set(_tokenize_key(canonical_name)) | {canonical_name.upper()}

    scored = []
    for prof in profiles:
        if prof["type"] in ("OID", "Geometry", "Blob", "Raster"):
            continue
        name = prof["name"]
        alias = prof["alias"]
        name_norm = _norm_key(name)
        alias_norm = _norm_key(alias)
        tokens = set(_tokenize_key(name) + _tokenize_key(alias))

        if tokens & exclude:
            continue
        if not prefer_existing_canonical and canonical_name and name.upper() == canonical_name.upper():
            continue

        score = 0
        if name_norm in exact_norm:
            score += 500
        if alias_norm in exact_norm:
            score += 450
        for cand in exact_norm:
            if cand and cand in name_norm:
                score += 120
            if cand and cand in alias_norm:
                score += 90
        for hint in token_hints:
            if all(tok in tokens or tok in name_norm or tok in alias_norm for tok in hint):
                score += 80 + (10 * len(hint))
        if name.upper().endswith("_NORM"):
            score += 30
        if re.search(r"_[0-9]+$", name):
            score -= 25
        if "JOIN" in tokens or "TARGET" in tokens:
            score -= 25
        if logical_key == "route_name" and ("NAME" in tokens or "STREET" in tokens or "ROAD" in tokens):
            score += 30
        if logical_key == "route_id" and ("RTE" in tokens or "ROUTE" in tokens):
            score += 20
        if score > 0:
            scored.append((score, name, alias))

    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], len(x[1]), x[1]))
    return scored[0][1]


def _required_missing_where(fc, required_fields):
    names_upper = field_map_upper(fc)
    clauses = []
    for fld in required_fields:
        actual = names_upper.get(fld.upper())
        if not actual:
            continue
        if fld == "AADT":
            clauses.append(f'"{actual}" IS NULL OR "{actual}" = 0')
        else:
            clauses.append(f"\"{actual}\" IS NULL OR \"{actual}\" = '' OR \"{actual}\" = ' '")
    return " OR ".join(f"({c})" for c in clauses) if clauses else None


def assert_required_canonical_fields_populated(fc, role, fail_if_any_missing=False, tolerance_count=0):
    role = (role or "").upper()
    required = [f for f in get_required_fields_for_role(role) if f != "ParentRoadOID"]
    field_specs = [(f, "LONG" if f == "AADT" else "TEXT") for f in required]
    counts, total = summarize_missing_counts(fc, field_specs)
    missing_total = sum(counts.values())
    if missing_total <= tolerance_count:
        msg(f"    -> Required canonical field audit for {role}: no missing required values detected")
        return counts, total

    detail = ", ".join([f"{k}={v:,}" for k, v in counts.items() if v])
    msg(f"    -> Required canonical field audit for {role}: missing required values detected | {detail}")
    if fail_if_any_missing:
        raise RuntimeError(
            f"Required canonical fields for role {role} were not fully populated: {detail}"
        )
    return counts, total


def fill_missing_fields_from_source_by_spatial_join(target_fc, source_fc, subset_where, source_to_dest, label, search_radius=AADT_TRANSFER_SEARCH_RADIUS, match_option="INTERSECT"):
    usable = [(src, dest, conv) for src, dest, conv in source_to_dest if src and dest]
    if not usable:
        msg(f"    -> {label}: no usable source fields were detected")
        return 0
    subset_lyr = safe_make_layer(target_fc, subset_where) if subset_where else safe_make_layer(target_fc)
    join_fc = os.path.join(arcpy.env.scratchGDB, make_unique_name(f"{safe_field_name(label)}_sj"))
    delete_if_exists(join_fc)
    updates = 0
    target_oid = arcpy.Describe(target_fc).OIDFieldName
    try:
        subset_count = int(arcpy.management.GetCount(subset_lyr)[0])
        if subset_count == 0:
            msg(f"    -> {label}: no eligible records require backfill")
            return 0
        msg(f"    -> {label}: {subset_count:,} records require targeted backfill")
        fmap = _make_backfill_fieldmap(subset_lyr, target_oid, source_fc, [src for src, _, _ in usable])
        t = time.time()
        arcpy.analysis.SpatialJoin(
            target_features=subset_lyr,
            join_features=source_fc,
            out_feature_class=join_fc,
            join_operation="JOIN_ONE_TO_ONE",
            join_type="KEEP_ALL",
            field_mapping=fmap,
            match_option=match_option,
            search_radius=search_radius,
        )
        log_phase_time(f"{label} - spatial join creation", t)

        names_upper = field_map_upper(join_fc, cached=False)
        target_oid_join = pick_field(join_fc, ["TARGET_OID"], required=True, names_upper=names_upper)
        join_field_lookup = {}
        for src, _, _ in usable:
            safe = re.sub(r"[^A-Za-z0-9_]", "_", str(src)).upper()
            join_field_lookup[src] = pick_field(join_fc, [f"SJ_{safe}"], required=False, names_upper=names_upper)

        source_by_oid = {}
        read_fields = [target_oid_join]
        src_positions = {}
        for src, _, _ in usable:
            jf = join_field_lookup.get(src)
            if jf:
                src_positions[src] = len(read_fields)
                read_fields.append(jf)
        with arcpy.da.SearchCursor(join_fc, read_fields) as cur:
            for row in cur:
                oid_val = row[0]
                if oid_val is None:
                    continue
                payload = source_by_oid.setdefault(int(oid_val), {})
                for src, pos in src_positions.items():
                    payload[src] = row[pos]

        update_fields = [target_oid] + [dest for _, dest, _ in usable]
        t = time.time()
        with arcpy.da.UpdateCursor(target_fc, update_fields, subset_where) as cur:
            for row in cur:
                oid_val = int(row[0])
                payload = source_by_oid.get(oid_val)
                if not payload:
                    continue
                changed = False
                for idx, (src, dest, conv) in enumerate(usable, start=1):
                    src_val = payload.get(src)
                    if src_val in (None, "", " "):
                        continue
                    cur_val = row[idx]
                    missing = numeric_field_is_missing(cur_val) if dest == "AADT" else field_is_blank(cur_val)
                    if not missing:
                        continue
                    try:
                        row[idx] = conv(src_val) if conv else src_val
                        changed = True
                    except Exception:
                        pass
                if changed:
                    cur.updateRow(row)
                    updates += 1
        log_phase_time(f"{label} - targeted update fill", t)
        return updates
    finally:
        delete_if_exists(subset_lyr)
        delete_if_exists(join_fc)


def _build_role_source_map(fc, role, include_optional=True):
    role = (role or "").upper()
    role_map = get_role_source_map(role)
    result = {}
    for canonical_field in [
        "LinkID_Norm", "RouteID_Norm", "RouteNm_Norm",
        "DirCode_Norm", "FromNode_Norm", "ToNode_Norm", "AADT"
    ]:
        if (not include_optional) and canonical_field in get_optional_fields_for_role(role):
            continue
        candidates = list(role_map.get(canonical_field, []))
        chosen = pick_field(fc, candidates, required=False) if candidates else None
        if not chosen:
            logical_key = CANONICAL_FIELD_TO_LOGICAL_KEY.get(canonical_field)
            chosen = resolve_source_field(
                fc,
                logical_key,
                prefer_existing_canonical=False,
                role=None,
            ) if logical_key else None
        result[canonical_field] = chosen
    return result


def _apply_source_map_to_target(fc, source_map, set_parent_oid=False):
    cursor_fields = ["OID@"]
    if set_parent_oid:
        cursor_fields.append("ParentRoadOID")
    for src in source_map.values():
        if src and src not in cursor_fields:
            cursor_fields.append(src)
    for dest in source_map.keys():
        if dest not in cursor_fields:
            cursor_fields.append(dest)

    idx = {f: i for i, f in enumerate(cursor_fields)}
    updated = 0
    with arcpy.da.UpdateCursor(fc, cursor_fields) as cur:
        for row in cur:
            changed = False
            if set_parent_oid:
                parent_oid = int(row[idx["OID@"]])
                if row[idx["ParentRoadOID"]] != parent_oid:
                    row[idx["ParentRoadOID"]] = parent_oid
                    changed = True

            for dest, src in source_map.items():
                if not src:
                    continue
                raw_val = row[idx[src]]
                desired = _normalize_long_value(raw_val) if dest == "AADT" else _normalize_text_value(raw_val)
                if row[idx[dest]] != desired:
                    row[idx[dest]] = desired
                    changed = True

            if changed:
                cur.updateRow(row)
                updated += 1
    return updated


def normalize_roads_from_role(roads_fc, role="TRAVELWAY", fail_on_required_missing=False):
    role = (role or "TRAVELWAY").upper()
    msg(f"    -> Normalizing roadway canonical fields from role: {role}")
    _ensure_canonical_road_fields(roads_fc)

    source_map = _build_role_source_map(roads_fc, role, include_optional=True)
    audit_canonical_mapping(roads_fc, source_map, f"{role} canonical", role=role)

    updated = _apply_source_map_to_target(roads_fc, source_map, set_parent_oid=True)
    msg(f"    -> {role} canonicalization updated {updated:,} road records")

    field_specs = [
        ("LinkID_Norm", "TEXT"), ("RouteID_Norm", "TEXT"), ("DirCode_Norm", "TEXT"),
        ("FromNode_Norm", "TEXT"), ("ToNode_Norm", "TEXT"), ("AADT", "LONG")
    ]
    log_missing_counts(
        f"Road canonical field status after {role} normalization",
        roads_fc,
        field_specs,
    )
    log_canonical_gap_audit(
        roads_fc,
        field_specs,
        f"Road canonical audit after {role} normalization",
        role=role,
    )
    assert_required_canonical_fields_populated(roads_fc, role, fail_if_any_missing=fail_on_required_missing)
    calculate_link_missing_flag(roads_fc)
    return source_map


def preserve_road_identity_fields(roads_fc, road_role="TRAVELWAY", fail_on_required_missing=False):
    """
    Backward-compatible entry point used by the rest of the pipeline.

    The old implementation tried to auto-detect source fields from the staged
    feature class itself. The rewritten version treats the study-road layer as a
    Travelway-derived dataset unless the caller explicitly says otherwise.
    """
    return normalize_roads_from_role(
        roads_fc,
        role=road_role,
        fail_on_required_missing=fail_on_required_missing,
    )
