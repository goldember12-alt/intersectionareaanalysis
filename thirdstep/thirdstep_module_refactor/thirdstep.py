# -*- coding: utf-8 -*-
"""
PROJECT: VDOT INTERSECTION SAFETY & ACCESS MANAGEMENT ANALYSIS
MODULE:  PHASE 3 - FUNCTIONAL AREA SEGMENTATION + DIRECTIONAL LABELING
VERSION: 2026.3 (MODULARIZED)

Thin orchestration entry point for the thirdstep pipeline.
"""

import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import config as cfg
from config import *
from logging_utils import msg, log_counts, log_phase_time
from arcpy_utils import (
    make_unique_name, field_names,
    field_map_upper, pick_field, geopandas_pipeline_enabled, ensure_effective_geopandas_flag, delete_if_exists, copy_or_project, check_required_fields, calculate_length_ft,
    get_crash_sql, join_fields_back, safe_make_layer, )
from field_normalization import (
    preserve_road_identity_fields,
)
try:
    from backfill import (
        transfer_aadt_fields_missing_only, enrich_roads_from_aadt,
        backfill_segment_aadt_fields_only_if_missing,
    )
except ImportError:
    from backfill import (
        transfer_aadt_fields_missing_only,
        backfill_segment_aadt_fields_only_if_missing,
    )
    def enrich_roads_from_aadt(roads_fc, aadt_fc, fail_on_missing_required=False):
        """Compatibility fallback when the refactor-folder backfill.py has not been updated."""
        msg("    -> enrich_roads_from_aadt not found in backfill.py; falling back to legacy missing-only transfer")
        transfer_aadt_fields_missing_only(roads_fc, aadt_fc)
from geometry_pipeline import (
    assign_speed_to_signals, build_functional_zones, apply_neighbor_trim_to_zones, resolve_signal_claims_by_roads,
    segment_roads_from_clean_claims,
)
from assignments import assign_access_initial, assign_crashes_initial
from geopandas_oracle import (
    export_working_layers,
    run_geopandas_directional_pipeline, join_csv_back_to_fgdb,
    validate_oracle_runtime_contract, log_oracle_preflight,
)
from writeback_qc import (
    calculate_final_density_metrics, add_final_schema_defaults, consolidate_final_qc_flags, build_qc_layers, summarize_qc_counts,
    write_directional_summary_back, log_final_oracle_validation,
)


def _phase_enabled(phase_num):
    return int(PHASE_START) <= int(phase_num) <= int(PHASE_STOP)


def _resolve_existing_fc(preferred_fc, fallback_fc=None):
    for fc in (preferred_fc, fallback_fc):
        try:
            if fc and arcpy.Exists(fc):
                return fc
        except Exception:
            pass
    return None




def _segment_linkids_for_oracle_preflight():
    if not arcpy.Exists(STAGED.get("seg_clean")):
        return set()
    names_upper = field_map_upper(STAGED["seg_clean"])
    link_field = names_upper.get("LINKID_NORM")
    if not link_field:
        return set()
    vals = set()
    with arcpy.da.SearchCursor(STAGED["seg_clean"], [link_field]) as cur:
        for (value,) in cur:
            if value not in (None, "", " "):
                vals.add(value)
    return vals

def _refresh_direct_source_handles():
    """Re-bind staged direct-source handles for paths that may not be physically staged."""
    if not geopandas_pipeline_enabled():
        STAGED["crashes_proj"] = INPUTS["crashes"]
        STAGED["access_proj"] = INPUTS["access"]
        STAGED["aadt_proj"] = INPUTS["aadt"]
        STAGED["speed_proj"] = INPUTS["speed"]


def _hydrate_resume_state():
    """
    Rehydrate staged handles needed by partial/resume runs.

    This only rewires stage references to datasets that already exist; it does not
    synthesize missing intermediate outputs. If required upstream artifacts are
    absent, later phases will still fail naturally with a clearer missing-dataset
    error.
    """
    _refresh_direct_source_handles()

    if REUSE_STAGED_OUTPUTS and arcpy.Exists(ROADS_STUDY_AADT_CACHE):
        STAGED["roads_study"] = ROADS_STUDY_AADT_CACHE

    reuse_candidates = [
        "roads_proj", "signals_proj", "crashes_proj", "access_proj", "aadt_proj", "speed_proj",
        "roads_study", "signals_study", "signals_speed", "zones_zone1", "zones_zone2full",
        "zones_zone2", "zones_all", "zones_claims", "zones_claims_clean", "seg_raw",
        "seg_clean", "parent_roads", "crash_assigned", "access_assigned",
    ]
    for key in reuse_candidates:
        fc = STAGED.get(key)
        if fc and not arcpy.Exists(fc):
            if key == "roads_study" and REUSE_STAGED_OUTPUTS and arcpy.Exists(ROADS_STUDY_AADT_CACHE):
                STAGED[key] = ROADS_STUDY_AADT_CACHE

    resume_requirements = {
        2: ["roads_study", "signals_study"],
        3: ["zones_all", "signals_speed", "roads_study"],
        4: ["zones_claims_clean"],
        5: ["seg_clean", "roads_study"],
        6: ["seg_clean", "signals_speed", "roads_study", "crash_assigned"],
        7: [],
        8: ["seg_clean"],
        9: ["crash_assigned"],
        10: [],
    }
    missing = [name for name in resume_requirements.get(PHASE_START, []) if not arcpy.Exists(STAGED.get(name))]
    if missing:
        msg(f"    -> Resume preflight: missing staged prerequisites for phase {PHASE_START}: {', '.join(missing)}")
    else:
        msg(f"    -> Resume preflight: staged prerequisites present for phase {PHASE_START}")


def phase_i_input_staging():
    msg("[1/10] PHASE I - INPUT STAGING")
    t0 = time.time()

    if REUSE_STAGED_OUTPUTS and arcpy.Exists(ROADS_STUDY_AADT_CACHE) and arcpy.Exists(STAGED["signals_study"]):
        _refresh_direct_source_handles()
        STAGED["roads_study"] = ROADS_STUDY_AADT_CACHE
        msg(f"    -> Reusing cached roads study dataset after AADT enrichment: {ROADS_STUDY_AADT_CACHE}")
        log_counts("Study roads", STAGED["roads_study"])
        log_counts("Study signals", STAGED["signals_study"])
        log_phase_time("Stage I input staging", t0)
        return

    t = time.time()
    for k, fc in INPUTS.items():
        if not arcpy.Exists(fc):
            raise FileNotFoundError(f"Missing required input: {fc}")
    log_phase_time("Stage I - input existence check", t)

    t = time.time()
    copy_or_project(INPUTS["roads"], STAGED["roads_proj"], TARGET_SR, CACHE_PROJECTED_INPUTS)
    copy_or_project(INPUTS["signals"], STAGED["signals_proj"], TARGET_SR, CACHE_PROJECTED_INPUTS)
    if geopandas_pipeline_enabled():
        copy_or_project(INPUTS["crashes"], STAGED["crashes_proj"], TARGET_SR, CACHE_PROJECTED_INPUTS)
        copy_or_project(INPUTS["access"], STAGED["access_proj"], TARGET_SR, CACHE_PROJECTED_INPUTS)
        copy_or_project(INPUTS["aadt"], STAGED["aadt_proj"], TARGET_SR, CACHE_PROJECTED_INPUTS)
        copy_or_project(INPUTS["speed"], STAGED["speed_proj"], TARGET_SR, CACHE_PROJECTED_INPUTS)
        msg("    -> Full staged-input path retained because GeoPandas runtime is available")
    else:
        STAGED["crashes_proj"] = INPUTS["crashes"]
        STAGED["access_proj"] = INPUTS["access"]
        STAGED["aadt_proj"] = INPUTS["aadt"]
        STAGED["speed_proj"] = INPUTS["speed"]
        msg("    -> ArcPy fast path active; using source layers directly for crashes/access/AADT/speed")
    log_phase_time("Stage I - project/copy inputs", t)

    t = time.time()
    roads_lyr = safe_make_layer(STAGED["roads_proj"])
    sql_roads = "(RIM_FACILI LIKE '%2%' OR RIM_FACILI LIKE '%4%') AND RIM_MEDIAN NOT LIKE '1-%'"
    arcpy.management.SelectLayerByAttribute(roads_lyr, "NEW_SELECTION", sql_roads)
    delete_if_exists(STAGED["roads_study"])
    arcpy.management.CopyFeatures(roads_lyr, STAGED["roads_study"])
    delete_if_exists(roads_lyr)
    log_phase_time("Stage I - road filtering/copy", t)

    t = time.time()
    preserve_road_identity_fields(
        STAGED["roads_study"],
        road_role=cfg.ROAD_ROLE_FOR_NORMALIZATION,
        fail_on_required_missing=cfg.REQUIRE_ROAD_ROLE_FIELDS,
    )
    log_phase_time("Stage I - preserve road identity", t)

    t = time.time()
    if cfg.ENABLE_ROAD_AADT_ENRICHMENT:
        enrich_roads_from_aadt(
            STAGED["roads_study"],
            STAGED["aadt_proj"],
            fail_on_missing_required=cfg.STRICT_ROAD_AADT_ENRICHMENT,
        )
    else:
        msg("    -> Road metadata enrichment from AADT is disabled by config")
    log_phase_time("Stage I - enrich road metadata from AADT", t)

    if CACHE_ROADS_STUDY_AFTER_AADT:
        t_cache = time.time()
        delete_if_exists(ROADS_STUDY_AADT_CACHE)
        arcpy.management.CopyFeatures(STAGED["roads_study"], ROADS_STUDY_AADT_CACHE)
        msg(f"    -> Cached roads study dataset after AADT enrichment: {ROADS_STUDY_AADT_CACHE}")
        log_phase_time("Stage I - cache roads after AADT enrichment", t_cache)

    t = time.time()
    sig_lyr = safe_make_layer(STAGED["signals_proj"])
    arcpy.management.SelectLayerByLocation(sig_lyr, "INTERSECT", STAGED["roads_study"], SIGNAL_TO_ROAD_FILTER)
    delete_if_exists(STAGED["signals_study"])
    arcpy.management.CopyFeatures(sig_lyr, STAGED["signals_study"])
    delete_if_exists(sig_lyr)
    log_phase_time("Stage I - signal study-area filter", t)

    t = time.time()
    tmp_sig_join = os.path.join(arcpy.env.scratchGDB, make_unique_name("sig_road_join"))
    delete_if_exists(tmp_sig_join)
    arcpy.analysis.SpatialJoin(
        target_features=STAGED["signals_study"],
        join_features=STAGED["roads_study"],
        out_feature_class=tmp_sig_join,
        join_operation="JOIN_ONE_TO_ONE",
        join_type="KEEP_ALL",
        match_option="CLOSEST",
        search_radius="100 Feet"
    )
    delete_if_exists(STAGED["signals_study"])
    arcpy.management.CopyFeatures(tmp_sig_join, STAGED["signals_study"])
    delete_if_exists(tmp_sig_join)
    log_phase_time("Stage I - signal/road join", t)

    log_counts("Study roads", STAGED["roads_study"])
    log_counts("Study signals", STAGED["signals_study"])
    log_phase_time("Stage I input staging", t0)


def phase_ii_build_functional_areas():
    msg("[2/10] PHASE II - BUILD FUNCTIONAL AREAS")
    assign_speed_to_signals(STAGED["signals_study"], STAGED["speed_proj"], STAGED["signals_speed"])
    build_functional_zones(
        STAGED["signals_speed"],
        STAGED["zones_zone1"],
        STAGED["zones_zone2full"],
        STAGED["zones_zone2"],
        STAGED["zones_all"]
    )
    log_counts("Zones merged", STAGED["zones_all"])


def phase_iii_clean_signal_ownership():
    msg("[3/10] PHASE III - CLEAN SIGNAL OWNERSHIP")
    t0 = time.time()
    apply_neighbor_trim_to_zones(STAGED["zones_all"], STAGED["signals_speed"])
    resolve_signal_claims_by_roads(
        STAGED["zones_all"],
        STAGED["roads_study"],
        STAGED["zones_claims"],
        STAGED["zones_claims_clean"]
    )
    log_counts("Clean claims", STAGED["zones_claims_clean"])
    log_phase_time("Claim resolution", t0)


def phase_iv_segment_roads():
    msg("[4/10] PHASE IV - SEGMENT ROADS")
    segment_roads_from_clean_claims(STAGED["zones_claims_clean"], STAGED["seg_clean"])
    log_counts("Segments", STAGED["seg_clean"])


def phase_v_initial_assignments():
    msg("[5/10] PHASE V - INITIAL ARC ASSIGNMENTS")
    t0 = time.time()

    _refresh_direct_source_handles()
    crashes_fc = _resolve_existing_fc(STAGED.get("crashes_proj"), INPUTS["crashes"]) or INPUTS["crashes"]
    access_fc = _resolve_existing_fc(STAGED.get("access_proj"), INPUTS["access"]) or INPUTS["access"]
    aadt_fc = _resolve_existing_fc(STAGED.get("aadt_proj"), INPUTS["aadt"]) or INPUTS["aadt"]

    dynamic_sql = get_crash_sql(crashes_fc)
    crash_lyr = safe_make_layer(crashes_fc, dynamic_sql if dynamic_sql else None)

    crash_assigned = assign_crashes_initial(STAGED["seg_clean"], crash_lyr)
    access_assigned = assign_access_initial(STAGED["seg_clean"], access_fc)

    if SEGMENT_AADT_FALLBACK_ONLY:
        backfill_segment_aadt_fields_only_if_missing(STAGED["seg_clean"], aadt_fc, STAGED["roads_study"])
    else:
        msg("    -> Missing-only segment enrichment from AADT")
        transfer_aadt_fields_missing_only(STAGED["seg_clean"], aadt_fc, target_label="segments")

    delete_if_exists(crash_lyr)
    STAGED["crash_assigned"] = crash_assigned
    STAGED["access_assigned"] = access_assigned
    log_phase_time("Initial assignments", t0)

    return crash_assigned, access_assigned


def phase_v_export_for_geopandas(crash_assigned_fc):
    msg("[6/10] PHASE VI - PREP FOR GEOPANDAS")
    t0 = time.time()

    STAGED["crash_assigned"] = crash_assigned_fc
    export_working_layers(
        STAGED["seg_clean"],
        STAGED["signals_speed"],
        crash_assigned_fc,
        STAGED["roads_study"]
    )
    log_phase_time("GeoPandas prep", t0)


def phase_vi_geo_directional():
    msg("[7/10] PHASE VII - GEOPANDAS DIRECTIONAL LABELING")
    t0 = time.time()
    diagnostics = validate_oracle_runtime_contract(_segment_linkids_for_oracle_preflight())
    log_oracle_preflight(diagnostics)
    result = run_geopandas_directional_pipeline()
    log_phase_time("GeoPandas directional pipeline", t0)
    return result


def _join_crash_counts_from_assigned(segments_fc, crash_assigned_fc):
    if not crash_assigned_fc or not arcpy.Exists(crash_assigned_fc):
        msg("    -> Crash summary join skipped; crash assignment output not found")
        return

    seg_oid_target = pick_field(segments_fc, ["SegOID"], required=False)
    if not seg_oid_target:
        msg("    ! Crash summary join skipped; SegOID not found on segments")
        return

    names_upper = field_map_upper(crash_assigned_fc)
    seg_oid_assigned = pick_field(crash_assigned_fc, ["SegOID"], required=False, names_upper=names_upper)
    if not seg_oid_assigned:
        msg("    ! Crash summary join skipped; SegOID not found on crash-assigned output")
        return

    crash_freq = os.path.join(arcpy.env.scratchGDB, make_unique_name("crash_freq_total"))
    delete_if_exists(crash_freq)
    arcpy.analysis.Frequency(crash_assigned_fc, crash_freq, [seg_oid_assigned])
    freq_count = pick_field(crash_freq, ["FREQUENCY"], required=False, names_upper=field_map_upper(crash_freq))
    if freq_count and freq_count != "Cnt_Crash_Total":
        arcpy.management.AlterField(crash_freq, freq_count, "Cnt_Crash_Total", "Cnt_Crash_Total")
    join_fields_back(segments_fc, seg_oid_target, crash_freq, seg_oid_assigned, ["Cnt_Crash_Total"])
    delete_if_exists(crash_freq)


def phase_ix_write_final(summary_paths, access_assigned_fc, crash_assigned_fc):
    msg("[8/10] PHASE VIII - WRITE FINAL RESULTS BACK IN ARCPY")

    delete_if_exists(OUTPUT_SEGMENTS_FINAL)
    arcpy.management.CopyFeatures(STAGED["seg_clean"], OUTPUT_SEGMENTS_FINAL)
    add_final_schema_defaults(OUTPUT_SEGMENTS_FINAL)

    try:
        if arcpy.Exists(access_assigned_fc):
            access_freq = os.path.join(arcpy.env.scratchGDB, make_unique_name("access_freq"))
            delete_if_exists(access_freq)
            arcpy.analysis.Frequency(access_assigned_fc, access_freq, ["SegOID"])
            freq_count = pick_field(access_freq, ["FREQUENCY"], required=False, names_upper=field_map_upper(access_freq))
            if freq_count and freq_count != "Cnt_Access":
                arcpy.management.AlterField(access_freq, freq_count, "Cnt_Access", "Cnt_Access")
            join_fields_back(OUTPUT_SEGMENTS_FINAL, "SegOID", access_freq, "SegOID", ["Cnt_Access"])
            delete_if_exists(access_freq)
    except Exception:
        msg("    ! Access summary join failed")

    try:
        _join_crash_counts_from_assigned(OUTPUT_SEGMENTS_FINAL, crash_assigned_fc)
    except Exception:
        msg("    ! Crash summary join failed")

    if summary_paths:
        seg_tbl = None
        qc_tbl = None

        if summary_paths.get("seg_summary_csv"):
            seg_tbl = join_csv_back_to_fgdb(summary_paths["seg_summary_csv"], "SegDirSummary_Stage3")
        elif summary_paths.get("seg_summary_df") is not None and pd is not None:
            seg_csv = os.path.join(EXPORT_DIR, "_seg_summary_tmp.csv")
            summary_paths["seg_summary_df"].to_csv(seg_csv, index=False)
            seg_tbl = join_csv_back_to_fgdb(seg_csv, "SegDirSummary_Stage3")

        if summary_paths.get("qc_csv"):
            qc_tbl = join_csv_back_to_fgdb(summary_paths["qc_csv"], "QCSummary_Stage3")
        elif summary_paths.get("qc_df") is not None and pd is not None and not summary_paths["qc_df"].empty:
            qc_csv = os.path.join(EXPORT_DIR, "_qc_summary_tmp.csv")
            summary_paths["qc_df"].to_csv(qc_csv, index=False)
            qc_tbl = join_csv_back_to_fgdb(qc_csv, "QCSummary_Stage3")

        if seg_tbl:
            write_directional_summary_back(OUTPUT_SEGMENTS_FINAL, seg_tbl)

    out_fields = set(field_names(OUTPUT_SEGMENTS_FINAL))
    if {"AADT", "OracleAADT", "AADT_Source", "QC_AADTConflict"}.issubset(out_fields):
        with arcpy.da.UpdateCursor(OUTPUT_SEGMENTS_FINAL, ["AADT", "OracleAADT", "AADT_Source", "QC_AADTConflict"]) as cur:
            for row in cur:
                gis_aadt, oracle_aadt, src, conflict = row
                final_src = src if src not in (None, "") else None
                has_gis = gis_aadt not in (None, 0, "")
                has_oracle = oracle_aadt not in (None, 0, "")
                if has_gis:
                    final_src = "GIS"
                elif has_oracle and USE_ORACLE_AADT:
                    try:
                        row[0] = int(float(oracle_aadt))
                    except Exception:
                        row[0] = oracle_aadt
                    final_src = "Oracle"
                else:
                    final_src = final_src or "SpatialFallback"
                row[2] = final_src
                cur.updateRow(row)

    if "Seg_Len_Ft" not in field_names(OUTPUT_SEGMENTS_FINAL):
        calculate_length_ft(OUTPUT_SEGMENTS_FINAL, "Seg_Len_Ft")

    consolidate_final_qc_flags(OUTPUT_SEGMENTS_FINAL)
    calculate_final_density_metrics(OUTPUT_SEGMENTS_FINAL)
    log_final_oracle_validation(OUTPUT_SEGMENTS_FINAL)

    try:
        if crash_assigned_fc and arcpy.Exists(crash_assigned_fc):
            crash_total = int(arcpy.management.GetCount(crash_assigned_fc)[0])
            if crash_total > 0 and "Cnt_Crash_Total" in field_names(OUTPUT_SEGMENTS_FINAL):
                seg_sum = 0
                with arcpy.da.SearchCursor(OUTPUT_SEGMENTS_FINAL, ["Cnt_Crash_Total"]) as cur:
                    for (val,) in cur:
                        seg_sum += int(val or 0)
                if seg_sum == 0:
                    msg("    ! Crash counts are zero on final segments despite non-empty crash assignments")
    except Exception:
        msg("    ! Crash count validation skipped")

    if WRITE_OPTIONAL_OUTPUT_COPIES:
        delete_if_exists(OUTPUT_SIGNALS_FINAL)
        arcpy.management.CopyFeatures(STAGED["signals_speed"], OUTPUT_SIGNALS_FINAL)

        delete_if_exists(OUTPUT_ZONES_FINAL)
        arcpy.management.CopyFeatures(STAGED["zones_all"], OUTPUT_ZONES_FINAL)


def phase_x_qc(crash_assigned_fc):
    msg("[9/10] PHASE X - QA / DIAGNOSTICS")
    qc_csv_tbl = None
    if WRITE_DIAGNOSTIC_CSVS and os.path.exists(EXPORT_SUMMARY_QC):
        qc_csv_tbl = join_csv_back_to_fgdb(EXPORT_SUMMARY_QC, "QCSummary_Stage3")
    summarize_qc_counts(OUTPUT_SEGMENTS_FINAL, qc_csv_tbl)
    build_qc_layers(OUTPUT_SEGMENTS_FINAL, crash_assigned_fc)


def cleanup():
    if KEEP_INTERMEDIATES:
        return

    msg("[10/10] CLEANUP")
    temps = [
        STAGED["zones_zone1"],
        STAGED["zones_zone2full"],
        STAGED["zones_zone2"],
        STAGED["zones_claims"],
        STAGED["zones_claims_clean"],
    ]
    for t in temps:
        delete_if_exists(t)


def main():
    ensure_effective_geopandas_flag()
    if PHASE_START > PHASE_STOP:
        raise ValueError(f"Invalid phase range: start={PHASE_START}, stop={PHASE_STOP}")

    _hydrate_resume_state()

    msg("=" * 72)
    msg(f"INITIALIZING THIRDSTEP IN: {default_gdb}")
    msg(f"TARGET SR: {TARGET_SR.name} ({TARGET_SR.factoryCode})")
    msg(
        f"USE_GEOPANDAS={cfg.USE_GEOPANDAS} | GEOPANDAS_RUNTIME_READY={geopandas_pipeline_enabled()} | "
        f"USE_ORACLE_MATCH_RESOLUTION={USE_ORACLE_MATCH_RESOLUTION} | CACHE_PROJECTED_INPUTS={CACHE_PROJECTED_INPUTS}"
    )
    msg(
        f"ORACLE_INTEGRATION_REQUIRED={ORACLE_INTEGRATION_REQUIRED} | ORACLE_GIS_KEYS_REQUIRED={ORACLE_GIS_KEYS_REQUIRED} | "
        f"ALLOW_GIS_ONLY_DIRECTION_FALLBACK={ALLOW_GIS_ONLY_DIRECTION_FALLBACK}"
    )
    msg(
        f"PHASE_RANGE={PHASE_START}-{PHASE_STOP} | REUSE_STAGED_OUTPUTS={REUSE_STAGED_OUTPUTS} | "
        f"CACHE_ROADS_STUDY_AFTER_AADT={CACHE_ROADS_STUDY_AFTER_AADT}"
    )
    msg("=" * 72)

    check_required_fields(INPUTS["roads"], "roads", {
        "road classification": ["RIM_FACILI"],
    })
    check_required_fields(INPUTS["aadt"], "aadt", {
        "link id": ["LINKID"],
        "aadt": ["AADT"],
    })

    crash_assigned_fc = STAGED.get("crash_assigned")
    access_assigned_fc = STAGED.get("access_assigned")
    summary_paths = None

    if _phase_enabled(1):
        phase_i_input_staging()
    if _phase_enabled(2):
        phase_ii_build_functional_areas()
    if _phase_enabled(3):
        phase_iii_clean_signal_ownership()
    if _phase_enabled(4):
        phase_iv_segment_roads()
    if _phase_enabled(5):
        crash_assigned_fc, access_assigned_fc = phase_v_initial_assignments()
    if _phase_enabled(6):
        if not crash_assigned_fc:
            crash_assigned_fc = STAGED.get("crash_assigned")
        phase_v_export_for_geopandas(crash_assigned_fc)
    if _phase_enabled(7):
        summary_paths = phase_vi_geo_directional()
    if _phase_enabled(8):
        if summary_paths is None:
            summary_paths = {}
        if not access_assigned_fc:
            access_assigned_fc = STAGED.get("access_assigned")
        phase_ix_write_final(summary_paths, access_assigned_fc, crash_assigned_fc)
    if _phase_enabled(9):
        if not crash_assigned_fc:
            crash_assigned_fc = STAGED.get("crash_assigned")
        phase_x_qc(crash_assigned_fc)
    if _phase_enabled(10):
        cleanup()

    msg("-" * 72)
    if PHASE_STOP < 10:
        msg(f"PARTIAL SUCCESS. COMPLETED THROUGH PHASE {PHASE_STOP}.")
    else:
        msg(f"SUCCESS. OUTPUT SAVED TO: {OUTPUT_SEGMENTS_FINAL}")
        if WRITE_OPTIONAL_OUTPUT_COPIES:
            msg(f"SIGNALS: {OUTPUT_SIGNALS_FINAL}")
            msg(f"ZONES:   {OUTPUT_ZONES_FINAL}")
        msg(f"QC:      {OUTPUT_QC_TABLE}")
    msg("-" * 72)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        msg("!" * 72)
        msg("THIRDSTEP FAILED")
        msg(str(e))
        msg(traceback.format_exc())
        msg("!" * 72)
        raise
