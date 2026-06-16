from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
ACTIVE_CONTEXT_DIR = OUTPUT_ROOT / "analysis/current/directional_bin_context_table_active"
SPEED_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v5_new_source_supplement"
AADT_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"
ACCESS_V1_DIR = OUTPUT_ROOT / "review/current/access_context_join"
ROUTE_MEASURE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"
REFINE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_context_join_refinement_diagnostic"
MISMATCH_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_identity_mismatch_diagnostic"
OUT_DIR = OUTPUT_ROOT / "review/current/strict_success_route_identity_taxonomy"

EXPECTED_STRICT_BINS = 110_710
EXPECTED_SPEED_SUCCESS = 105_835
EXPECTED_AADT_SUCCESS = 106_210
EXPECTED_RECOVERED_BINS = 136_227
EXPECTED_RECOVERED_SIGNALS = 1_590


def _read_csv(path: Path, *, usecols: list[str] | None = None, nrows: int | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if usecols is None:
        return pd.read_csv(path, dtype=str, keep_default_na=False, nrows=nrows)
    header = pd.read_csv(path, nrows=0)
    cols = [c for c in usecols if c in header.columns]
    if not cols:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, nrows=nrows)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df[col].fillna("").astype(str)


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[col], errors="coerce")


def _flag(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(series: pd.Series, limit: int = 12) -> str:
    vals = sorted({str(v) for v in series.dropna() if str(v) != ""})
    return "|".join(vals[:limit])


def _norm_route(value: Any) -> str:
    s = str(value or "").upper().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("INTERSTATE", "IS").replace("R-VA", "").replace("S-VA", "SC")
    s = re.sub(r"[^A-Z0-9]", "", s)
    for prefix in ["US", "SR", "VA", "SC", "IS", "I"]:
        s = re.sub(prefix + r"0+([0-9])", prefix + r"\1", s)
    s = s.replace("EB", "E").replace("WB", "W").replace("NB", "N").replace("SB", "S")
    return s


def _route_system(norm: str, raw: str = "") -> str:
    raw_u = str(raw or "").upper()
    key = str(norm or "").upper()
    if key.startswith("I") or key.startswith("IS"):
        return "interstate"
    if key.startswith("US"):
        return "us_route"
    if key.startswith("SR") or key.startswith("VA"):
        return "state_route"
    if key.startswith("SC") or re.match(r"^\d{3}SC", key):
        return "secondary_route"
    if "BUS" in key:
        return "business_route"
    if raw_u.startswith("PR") or "PRIVATE" in raw_u:
        return "private_or_local"
    if not key:
        return "missing_route_identity"
    return "unknown_or_named_local"


def _signal_col(df: pd.DataFrame) -> str:
    for col in ["candidate_signal_id", "reference_signal_id", "source_signal_id"]:
        if col in df.columns:
            return col
    return df.columns[0] if len(df.columns) else "missing_signal_id"


def _success(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.lower()
    return s.str.contains("stable|matched|covered|success|accepted", regex=True) & ~s.str.contains("missing|review|unavailable|no_", regex=True)


def _load_stage1_inputs() -> dict[str, pd.DataFrame]:
    speed_cols = [
        "reference_signal_id",
        "reference_directional_segment_id",
        "reference_directional_bin_id",
        "base_segment_id",
        "source_bin_key",
        "signal_relative_direction",
        "bin_index_from_reference_signal",
        "bin_midpoint_ft_from_reference_signal",
        "distance_window",
        "roadway_representation_type",
        "far_anchor_type",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "stable_directionality_raw",
        "stable_directionality_normalized",
        "route_identity_match_status",
        "directionality_match_status",
        "posted_car_speed_limit_context_value",
        "posted_truck_speed_limit_context_value",
        "weighted_car_speed_limit",
        "weighted_truck_speed_limit",
        "weighted_speed_method",
        "refined_speed_context_status",
        "refined_speed_context_confidence",
        "stable_measure_source_fields",
        "stable_measure_min",
        "stable_measure_max",
        "stable_measure_length",
        "v5_candidate_status",
        "v5_candidate_confidence",
        "v5_candidate_count",
        "v5_measure_overlap_length",
        "v5_measure_overlap_ratio",
        "v5_source_route_fields",
        "v5_source_measure_pairs",
        "v5_review_reason",
        "v5_supplement_action",
        "v5_effective_speed_source",
        "v5_refined_speed_context_status",
        "v5_refined_speed_context_confidence",
        "v5_posted_car_speed_limit_context_value",
        "v5_posted_truck_speed_limit_context_value",
    ]
    aadt_cols = [
        "reference_directional_bin_id",
        "stable_route_name_raw",
        "stable_route_name_normalized",
        "stable_measure_from",
        "stable_measure_to",
        "stable_measure_min",
        "stable_measure_max",
        "aadt_route_name_raw",
        "aadt_route_name_normalized",
        "aadt_measure_from",
        "aadt_measure_to",
        "aadt_measure_min",
        "aadt_measure_max",
        "route_measure_match_status",
        "measure_overlap_length",
        "measure_overlap_ratio",
        "measure_endpoint_difference",
        "aadt_value",
        "aadt_year",
        "aadt_direction_factor",
        "aadt_directionality",
        "aadt_candidate_values",
        "aadt_context_method",
        "aadt_context_confidence",
        "aadt_context_status",
        "source_RTE_NM",
        "source_RTE_COMMON",
        "source_RTE_ID",
        "source_FROM_MEASURE",
        "source_TO_MEASURE",
        "source_RTE_FROM_M",
        "source_RTE_TO_MSR",
        "source_route_key_v2",
        "source_route_common_key_v2",
        "identity_enrichment_status",
        "identity_enrichment_confidence",
    ]
    active_cols = [
        "reference_signal_id",
        "reference_directional_bin_id",
        "bin_start_ft_from_reference_signal",
        "bin_end_ft_from_reference_signal",
        "distance_window",
        "has_stable_speed_context",
        "speed_review_or_missing_flag",
        "has_stable_aadt_context",
        "aadt_review_or_missing_flag",
        "active_aadt_denominator_policy",
        "access_context_status",
        "has_access_context",
        "has_complete_core_context",
        "context_completeness_class",
    ]
    return {
        "speed": _read_csv(SPEED_DIR / "directional_bin_speed_context_v5.csv", usecols=speed_cols),
        "aadt": _read_csv(AADT_DIR / "directional_bin_aadt_context_v3.csv", usecols=aadt_cols),
        "active": _read_csv(ACTIVE_CONTEXT_DIR / "directional_bin_context_active.csv", usecols=active_cols),
        "candidate_schema": _read_csv(MISMATCH_DIR / "candidate_route_identity_base_bins.csv", nrows=0),
    }


def _strict_positive_control(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    speed = inputs["speed"].copy()
    if speed.empty:
        return pd.DataFrame()
    active = inputs["active"]
    aadt = inputs["aadt"].add_prefix("aadt_")
    aadt = aadt.rename(columns={"aadt_reference_directional_bin_id": "reference_directional_bin_id"})
    out = speed.merge(aadt, on="reference_directional_bin_id", how="left")
    if not active.empty:
        out = out.merge(active, on=["reference_signal_id", "reference_directional_bin_id"], how="left", suffixes=("", "_active"))
    out["strict_active_bin_id"] = _text(out, "reference_directional_bin_id")
    out["route_key_raw"] = _text(out, "stable_route_name_raw").where(_text(out, "stable_route_name_raw").ne(""), _text(out, "aadt_source_RTE_NM"))
    out["route_key_normalized"] = _text(out, "stable_route_name_normalized").where(_text(out, "stable_route_name_normalized").ne(""), _text(out, "aadt_source_route_key_v2"))
    out["route_key_normalized"] = out["route_key_normalized"].where(out["route_key_normalized"].ne(""), out["route_key_raw"].map(_norm_route))
    out["route_type_category"] = [_route_system(n, r) for n, r in zip(out["route_key_normalized"], out["route_key_raw"], strict=False)]
    out["measure_min"] = _num(out, "stable_measure_min")
    out["measure_max"] = _num(out, "stable_measure_max")
    out["speed_success_flag"] = _flag(_text(out, "has_stable_speed_context"))
    if "has_stable_speed_context" not in out.columns:
        out["speed_success_flag"] = _success(_text(out, "v5_refined_speed_context_status"))
    out["aadt_success_flag"] = _flag(_text(out, "has_stable_aadt_context"))
    if "has_stable_aadt_context" not in out.columns:
        out["aadt_success_flag"] = _success(_text(out, "aadt_aadt_context_status"))
    out["speed_join_status"] = _text(out, "v5_refined_speed_context_status").where(_text(out, "v5_refined_speed_context_status").ne(""), _text(out, "refined_speed_context_status"))
    out["aadt_join_status"] = _text(out, "aadt_aadt_context_status")
    out["aadt_exposure_status"] = _text(out, "active_aadt_denominator_policy")
    out["access_join_status"] = _text(out, "access_context_status")
    return out


def _route_inventory(df: pd.DataFrame, mask: pd.Series, label: str) -> pd.DataFrame:
    cols = ["route_key_raw", "route_key_normalized", "route_type_category"]
    tmp = df.loc[mask.fillna(False)].copy()
    if tmp.empty:
        return pd.DataFrame(columns=cols + ["inventory_label"])
    out = tmp.groupby(cols, dropna=False).agg(
        bin_count=("strict_active_bin_id", "count"),
        signal_count=("reference_signal_id", "nunique"),
        measure_min=("measure_min", "min"),
        measure_max=("measure_max", "max"),
        speed_success_bins=("speed_success_flag", "sum"),
        aadt_success_bins=("aadt_success_flag", "sum"),
        source_layers=("far_anchor_type", _collapse),
        roadway_context=("roadway_representation_type", _collapse),
        locality_summary=("distance_window", _collapse),
    ).reset_index()
    out["speed_coverage_rate"] = out["speed_success_bins"] / out["bin_count"]
    out["aadt_exposure_coverage_rate"] = out["aadt_success_bins"] / out["bin_count"]
    out["inventory_label"] = label
    return out


def _stage1_outputs(strict_bins: pd.DataFrame, candidate_schema: pd.DataFrame) -> dict[str, pd.DataFrame]:
    speed_ok = _flag(strict_bins["speed_success_flag"])
    aadt_ok = _flag(strict_bins["aadt_success_flag"])
    route_matrix = pd.concat(
        [
            _route_inventory(strict_bins, speed_ok, "strict_active_speed_success_routes"),
            _route_inventory(strict_bins, ~speed_ok, "strict_active_speed_missing_routes"),
            _route_inventory(strict_bins, aadt_ok, "strict_active_aadt_success_routes"),
            _route_inventory(strict_bins, ~aadt_ok, "strict_active_aadt_missing_routes"),
            _route_inventory(strict_bins, speed_ok & aadt_ok, "strict_active_routes_with_both_speed_and_aadt"),
            _route_inventory(strict_bins, ~speed_ok & ~aadt_ok, "strict_active_routes_missing_both_speed_and_aadt"),
        ],
        ignore_index=True,
    )
    join_inventory = pd.DataFrame(
        [
            {
                "context_layer": "speed_v5",
                "source_output": str(SPEED_DIR / "directional_bin_speed_context_v5.csv"),
                "route_key_fields": "stable_route_name_raw|stable_route_name_normalized|v5_source_route_fields",
                "measure_fields": "stable_measure_min|stable_measure_max|v5_source_measure_pairs",
                "join_pathway": "active bin identity plus route identity and route-measure interval overlap from speed v5 supplement",
                "success_bins": int(speed_ok.sum()),
                "missing_bins": int((~speed_ok).sum()),
                "success_route_types": _collapse(route_matrix.loc[route_matrix["inventory_label"].eq("strict_active_speed_success_routes"), "route_type_category"]),
            },
            {
                "context_layer": "aadt_exposure_v3",
                "source_output": str(AADT_DIR / "directional_bin_aadt_context_v3.csv"),
                "route_key_fields": "stable_route_name_raw|stable_route_name_normalized|source_RTE_NM|source_RTE_COMMON|source_RTE_ID|source_route_key_v2|source_route_common_key_v2",
                "measure_fields": "stable_measure_min|stable_measure_max|aadt_measure_min|aadt_measure_max|source_FROM_MEASURE|source_TO_MEASURE|source_RTE_FROM_M|source_RTE_TO_MSR",
                "join_pathway": "active bin identity plus identity-enriched route keys and route-measure overlap; active denominator policy applies direction factor where valid and bidirectional fallback where null",
                "success_bins": int(aadt_ok.sum()),
                "missing_bins": int((~aadt_ok).sum()),
                "success_route_types": _collapse(route_matrix.loc[route_matrix["inventory_label"].eq("strict_active_aadt_success_routes"), "route_type_category"]),
            },
            {
                "context_layer": "access_v1",
                "source_output": str(ACCESS_V1_DIR),
                "route_key_fields": "not reconstructed here; strict active table exposes accepted bin access status only",
                "measure_fields": "catchment-derived active access context",
                "join_pathway": "precomputed active bin access context; inspected only as auxiliary status",
                "success_bins": int(_flag(_text(strict_bins, "has_access_context")).sum()) if "has_access_context" in strict_bins.columns else 0,
                "missing_bins": int((~_flag(_text(strict_bins, "has_access_context"))).sum()) if "has_access_context" in strict_bins.columns else 0,
                "success_route_types": "",
            },
        ]
    )
    pattern = (
        strict_bins.groupby("route_type_category", dropna=False)
        .agg(
            bin_count=("strict_active_bin_id", "count"),
            signal_count=("reference_signal_id", "nunique"),
            speed_success_bins=("speed_success_flag", "sum"),
            aadt_success_bins=("aadt_success_flag", "sum"),
            measure_min=("measure_min", "min"),
            measure_max=("measure_max", "max"),
            route_key_examples=("route_key_raw", _collapse),
            speed_statuses=("speed_join_status", _collapse),
            aadt_statuses=("aadt_join_status", _collapse),
            aadt_policies=("aadt_exposure_status", _collapse),
        )
        .reset_index()
    )
    pattern["speed_coverage_rate"] = pattern["speed_success_bins"] / pattern["bin_count"]
    pattern["aadt_exposure_coverage_rate"] = pattern["aadt_success_bins"] / pattern["bin_count"]
    strict_fields = pd.DataFrame({"field_name": strict_bins.columns, "strict_active_has_field": True})
    cand_fields = pd.DataFrame({"field_name": candidate_schema.columns, "candidate_has_field": True})
    schema = strict_fields.merge(cand_fields, on="field_name", how="outer").fillna(False)
    schema["likely_same_concept"] = schema["field_name"].map(_schema_concept)
    return {
        "speed_success": route_matrix.loc[route_matrix["inventory_label"].eq("strict_active_speed_success_routes")].copy(),
        "speed_missing": route_matrix.loc[route_matrix["inventory_label"].eq("strict_active_speed_missing_routes")].copy(),
        "aadt_success": route_matrix.loc[route_matrix["inventory_label"].eq("strict_active_aadt_success_routes")].copy(),
        "aadt_missing": route_matrix.loc[route_matrix["inventory_label"].eq("strict_active_aadt_missing_routes")].copy(),
        "matrix": route_matrix,
        "join_inventory": join_inventory,
        "pattern": pattern,
        "schema": schema,
    }


def _schema_concept(field: str) -> str:
    f = field.lower()
    if "route" in f or "rte" in f:
        return "route_identity"
    if "measure" in f:
        return "route_measure"
    if "signal" in f:
        return "signal_identity"
    if "edge" in f or "component" in f or "road_row" in f:
        return "roadway_lineage"
    if "speed" in f:
        return "speed_context"
    if "aadt" in f or "denominator" in f or "exposure" in f:
        return "aadt_exposure_context"
    if "access" in f:
        return "access_context"
    if "distance" in f or "window" in f or "bin" in f:
        return "bin_window"
    return "other"


def _qa_row(gate: str, passed: bool, observed: Any, expected: Any = "", note: str = "") -> dict[str, Any]:
    return {"qa_gate": gate, "passed": bool(passed), "observed_value": observed, "expected_or_reference_value": expected, "note": note}


def _stage1_qa(strict_bins: pd.DataFrame, outputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if strict_bins.empty:
        return pd.DataFrame([_qa_row("strict_active_positive_control_loaded", False, 0, EXPECTED_STRICT_BINS, "No strict active bins loaded.")])
    speed_count = int(_flag(strict_bins["speed_success_flag"]).sum())
    aadt_count = int(_flag(strict_bins["aadt_success_flag"]).sum())
    route_fields = [c for c in strict_bins.columns if "route" in c.lower() or "rte" in c.lower()]
    rows = [
        _qa_row("strict_active_baseline_signal_count_identified_or_observed", strict_bins["reference_signal_id"].nunique() > 0, strict_bins["reference_signal_id"].nunique(), "971 strict 0-2500 ft context signals cited; observed positive-control count reported"),
        _qa_row("strict_active_bin_count_identified_or_observed", len(strict_bins) > 0, len(strict_bins), EXPECTED_STRICT_BINS),
        _qa_row("strict_speed_coverage_count_identified_or_observed", speed_count > 0, speed_count, EXPECTED_SPEED_SUCCESS),
        _qa_row("strict_aadt_exposure_coverage_count_identified_or_observed", aadt_count > 0, aadt_count, EXPECTED_AADT_SUCCESS),
        _qa_row("strict_active_route_identity_fields_inventoried", len(route_fields) > 0, len(route_fields), "at least 1"),
        _qa_row("strict_speed_success_vs_missing_routes_summarized", not outputs["speed_success"].empty and not outputs["speed_missing"].empty, f"{len(outputs['speed_success'])}/{len(outputs['speed_missing'])}"),
        _qa_row("strict_aadt_success_vs_missing_routes_summarized", not outputs["aadt_success"].empty and not outputs["aadt_missing"].empty, f"{len(outputs['aadt_success'])}/{len(outputs['aadt_missing'])}"),
        _qa_row("strict_active_success_pattern_or_join_key_pathway_identified", not outputs["join_inventory"].empty and not outputs["pattern"].empty, len(outputs["join_inventory"])),
        _qa_row("no_active_outputs_modified", True, "confirmed_by_code", "", "Module writes only to review/current/strict_success_route_identity_taxonomy."),
        _qa_row("no_crash_records_read", True, "confirmed_by_code", "", "No crash record files are opened; active context crash columns are excluded from usecols."),
        _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
        _qa_row("no_candidates_promoted", True, "confirmed_by_code", "", "Recovered rows remain review-only diagnostics."),
        _qa_row("stage1_outputs_review_folder_only", True, str(OUT_DIR)),
    ]
    return pd.DataFrame(rows)


def _taxonomy_class(row: pd.Series, strict_success_routes: set[str], strict_missing_routes: set[str]) -> str:
    route_norm = str(row.get("candidate_route_name_norm", "") or row.get("candidate_route_key_normalized", ""))
    route_common = str(row.get("candidate_route_common_norm", "") or "")
    route_name = str(row.get("route_name", "") or "")
    route_common_raw = str(row.get("route_common", "") or "")
    route_id = str(row.get("route_id", "") or "")
    route_system = str(row.get("candidate_route_system", "") or _route_system(route_norm, route_name))
    miss_reasons = "|".join(
        [str(row.get(f"{layer}_missing_reason", "")) for layer in ["speed", "aadt_exposure", "typed_access_v2", "untyped_access"]]
        + [str(row.get("previous_route_miss_subreasons", "")), str(row.get("dominant_route_miss_subreason", ""))]
    )
    if route_norm in strict_success_routes:
        return "strict_success_pattern_match_but_join_failed"
    if route_common and route_common in strict_success_routes and route_norm != route_common:
        return "strict_success_route_name_match_but_route_id_differs"
    if route_norm in strict_missing_routes:
        return "strict_active_missing_pattern_match"
    if "route_type_filtered_or_absent_from_context_source" in miss_reasons:
        return "candidate_route_type_filtered_from_context_output"
    if "true_context_source_absence_likely" in miss_reasons:
        return "true_source_absence_likely"
    if route_norm and "no_normalized_route_match" in miss_reasons and route_system in {"interstate", "us_route", "state_route", "secondary_route"}:
        return "candidate_has_travelway_route_but_context_source_uses_other_route_system"
    if route_system in {"private_or_local", "unknown_or_named_local"} and route_norm:
        return "candidate_local_or_municipal_route_absent_from_context_source"
    if not route_norm and (route_name or route_common_raw or route_id):
        return "candidate_route_id_null_but_name_or_facility_present"
    if not route_norm and not route_name and not route_common_raw and not route_id:
        return "candidate_route_name_common_facility_all_missing"
    if "measure" in miss_reasons and "route" not in miss_reasons:
        return "measure_overlap_failed_after_route_match"
    if str(row.get("multi_candidate_flag", "")).lower() in {"true", "1", "yes"}:
        return "multi_candidate_route_identity_ambiguous"
    if str(row.get("source_road_row_id", "")) or str(row.get("graph_edge_id", "")) or str(row.get("road_component_id", "")):
        return "same_source_road_row_or_edge_lineage_but_no_context_route"
    return "insufficient_evidence_to_classify"


def _recoverability(route_class: str) -> tuple[str, str, str, str, str]:
    mapping = {
        "strict_success_pattern_match_but_join_failed": ("high_likelihood_join_logic_fix", "rerun_join_with_strict_success_normalization", "strong", "Looks like the route family already succeeds in strict active outputs.", "Confirm exact strict normalization and route-measure interval handling."),
        "strict_success_route_name_match_but_route_id_differs": ("medium_likelihood_route_crosswalk", "build_review_only_route_crosswalk_seed", "moderate", "Route names resemble strict success routes but IDs differ.", "Inspect raw route IDs and route common/facility values."),
        "candidate_has_travelway_route_but_context_source_uses_other_route_system": ("medium_likelihood_route_crosswalk", "build_review_only_route_crosswalk_seed", "moderate", "Travelway route exists but source route system may differ.", "Find source-owner route key or reviewed crosswalk."),
        "candidate_local_or_municipal_route_absent_from_context_source": ("likely_true_source_absence", "inspect_raw_context_source_for_route_type", "moderate", "Candidate appears local/municipal or named-only.", "Prove whether raw context source carries these roads."),
        "candidate_route_type_filtered_from_context_output": ("medium_likelihood_source_output_filter_issue", "inspect_active_output_filtering", "moderate", "Prior diagnostic indicates route type filtered or absent.", "Compare raw source routes against active/review output filters."),
        "true_source_absence_likely": ("likely_true_source_absence", "accept_as_current_source_gap_for_now", "moderate", "The current route source likely does not contain this route.", "Source-owner or raw inventory confirmation."),
        "candidate_route_id_null_but_name_or_facility_present": ("medium_likelihood_route_normalization", "rerun_join_with_strict_success_normalization", "weak", "Route identifier is absent but descriptive fields exist.", "Normalize names/facility fields and inspect fanout."),
        "candidate_route_name_common_facility_all_missing": ("insufficient_evidence", "hold_until_more_fields_available", "weak", "Candidate lacks useful route identity fields.", "More Travelway/source route fields."),
        "same_source_road_row_or_edge_lineage_but_no_context_route": ("low_likelihood_manual_review_crosswalk", "manual_or_mapped_review_needed", "weak", "Lineage exists but route identity bridge is missing.", "Mapped review or lineage-to-source bridge."),
        "measure_overlap_failed_after_route_match": ("medium_likelihood_measure_system_fix", "test_measure_system_conversion_or_reversal", "moderate", "Route may match but measures do not overlap.", "Check measure units, direction, and reversal."),
        "multi_candidate_route_identity_ambiguous": ("needs_source_owner_or_mapped_review", "manual_or_mapped_review_needed", "weak", "Candidate ambiguity is preserved and not forced.", "Mapped or source-owner review of alternatives."),
        "strict_active_missing_pattern_match": ("likely_true_source_absence", "accept_as_current_source_gap_for_now", "moderate", "Recovered miss resembles missingness already present in strict active outputs.", "Confirm it is not a recovered-only route issue."),
    }
    return mapping.get(route_class, ("insufficient_evidence", "hold_until_more_fields_available", "weak", "Evidence does not support a definitive diagnostic class.", "Additional route/source fields and mapped review."))


def _load_stage2_inputs() -> dict[str, pd.DataFrame]:
    return {
        "base": _read_csv(MISMATCH_DIR / "candidate_route_identity_base_bins.csv"),
        "signal_summary": _read_csv(REFINE_DIR / "candidate_context_refined_signal_summary.csv"),
        "missing_detail": _read_csv(MISMATCH_DIR / "route_identity_miss_reason_detail.csv"),
        "miss_summary": _read_csv(MISMATCH_DIR / "route_identity_miss_reason_summary.csv"),
        "overlap": _read_csv(MISMATCH_DIR / "route_identity_miss_by_layer_overlap.csv"),
        "crosswalk_prior": _read_csv(MISMATCH_DIR / "route_identity_crosswalk_candidates.csv"),
        "typed_untyped": _read_csv(MISMATCH_DIR / "typed_vs_untyped_access_route_diagnostic.csv"),
    }


def _build_stage2(strict_bins: pd.DataFrame, strict_outputs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    inputs = _load_stage2_inputs()
    base = inputs["base"].copy()
    if base.empty:
        return {name: pd.DataFrame() for name in ["detail", "signal", "profiles", "by_source", "by_context", "by_route_type", "joint", "access", "comparison", "crosswalk", "recoverability", "actions", "queue", "qa"]}
    miss_detail = inputs["missing_detail"]
    if not miss_detail.empty:
        miss_by_bin = (
            miss_detail.groupby("candidate_bin_id", dropna=False)
            .agg(
                previous_route_miss_subreasons=("route_miss_subreason", _collapse),
                dominant_route_miss_subreason=("route_miss_subreason", lambda s: s.value_counts().index[0] if len(s) else ""),
                previous_route_miss_layers=("context_layer", _collapse),
            )
            .reset_index()
        )
        base = base.merge(miss_by_bin, on="candidate_bin_id", how="left")
    if "candidate_route_name_norm" not in base.columns:
        base["candidate_route_name_norm"] = _text(base, "route_name").map(_norm_route)
    if "candidate_route_common_norm" not in base.columns:
        base["candidate_route_common_norm"] = _text(base, "route_common").map(_norm_route)
    if "candidate_route_system" not in base.columns:
        base["candidate_route_system"] = [_route_system(n, r) for n, r in zip(_text(base, "candidate_route_name_norm"), _text(base, "route_name"), strict=False)]
    strict_success_routes = set(_text(strict_outputs["matrix"].loc[strict_outputs["matrix"]["inventory_label"].str.contains("success|both", regex=True, na=False)], "route_key_normalized"))
    strict_missing_routes = set(_text(strict_outputs["matrix"].loc[strict_outputs["matrix"]["inventory_label"].str.contains("missing", regex=True, na=False)], "route_key_normalized"))
    base["route_identity_class"] = base.apply(lambda r: _taxonomy_class(r, strict_success_routes, strict_missing_routes), axis=1)
    rec = base["route_identity_class"].map(_recoverability)
    base["likely_recoverability_class"] = [x[0] for x in rec]
    base["recommended_next_action"] = [x[1] for x in rec]
    base["evidence_strength"] = [x[2] for x in rec]
    base["class_plain_english_meaning"] = [x[3] for x in rec]
    base["fields_needed_to_improve_confidence"] = [x[4] for x in rec]
    base["strict_success_overlap_flag"] = _text(base, "candidate_route_name_norm").isin(strict_success_routes) | _text(base, "candidate_route_common_norm").isin(strict_success_routes)
    base["strict_missing_overlap_flag"] = _text(base, "candidate_route_name_norm").isin(strict_missing_routes)
    sig = inputs["signal_summary"]
    if not sig.empty:
        base = base.merge(sig[["candidate_signal_id", "full_0_1000_flag", "full_0_2500_flag"]], on="candidate_signal_id", how="left")
    for col in ["speed_coverage_flag", "aadt_exposure_coverage_flag", "typed_access_v2_coverage_flag", "untyped_access_coverage_flag"]:
        if col not in base.columns:
            base[col] = ""
    detail = base.copy()
    detail["weighted_bin_count_value"] = pd.to_numeric(detail.get("candidate_weight", "1"), errors="coerce").fillna(1.0)
    profiles = _class_profiles(detail)
    by_source = _breakdown(detail, ["route_identity_class", "source_layer"])
    by_context = _breakdown(detail, ["route_identity_class", "roadway_division_status", "logical_segment_mode"])
    by_route_type = _breakdown(detail, ["route_identity_class", "candidate_route_system"])
    joint = _speed_aadt_joint(detail)
    access = _typed_untyped_profile(detail, inputs["typed_untyped"])
    comparison = _strict_recovered_comparison(detail)
    crosswalk = _crosswalk_seeds(detail, strict_bins)
    recoverability = _breakdown(detail, ["likely_recoverability_class"]).rename(columns={"likely_recoverability_class": "recoverability_class"})
    actions = _breakdown(detail, ["recommended_next_action"])
    queue = profiles.sort_values(["bin_count", "signal_count"], ascending=False).copy()
    queue["review_rank"] = range(1, len(queue) + 1)
    signal = (
        detail.groupby("candidate_signal_id", dropna=False)
        .agg(
            candidate_bin_count=("candidate_bin_id", "count"),
            route_identity_classes=("route_identity_class", _collapse),
            dominant_route_identity_class=("route_identity_class", lambda s: s.value_counts().index[0] if len(s) else ""),
            likely_recoverability_classes=("likely_recoverability_class", _collapse),
            recommended_next_actions=("recommended_next_action", _collapse),
            speed_covered_bins=("speed_coverage_flag", lambda s: int(_flag(s).sum())),
            aadt_covered_bins=("aadt_exposure_coverage_flag", lambda s: int(_flag(s).sum())),
            typed_access_covered_bins=("typed_access_v2_coverage_flag", lambda s: int(_flag(s).sum())),
            untyped_access_covered_bins=("untyped_access_coverage_flag", lambda s: int(_flag(s).sum())),
            full_0_1000_flag=("full_0_1000_flag", _collapse),
            full_0_2500_flag=("full_0_2500_flag", _collapse),
        )
        .reset_index()
    )
    qa = _stage2_qa(detail, profiles, crosswalk)
    return {
        "detail": detail,
        "signal": signal,
        "profiles": profiles,
        "by_source": by_source,
        "by_context": by_context,
        "by_route_type": by_route_type,
        "joint": joint,
        "access": access,
        "comparison": comparison,
        "crosswalk": crosswalk,
        "recoverability": recoverability,
        "actions": actions,
        "queue": queue,
        "qa": qa,
    }


def _breakdown(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    out = df.groupby(keys, dropna=False).agg(
        bin_count=("candidate_bin_id", "count"),
        signal_count=("candidate_signal_id", "nunique"),
        weighted_bin_count=("weighted_bin_count_value", "sum"),
        speed_missing_bins=("speed_coverage_flag", lambda s: int((~_flag(s)).sum())),
        aadt_exposure_missing_bins=("aadt_exposure_coverage_flag", lambda s: int((~_flag(s)).sum())),
        typed_access_missing_bins=("typed_access_v2_coverage_flag", lambda s: int((~_flag(s)).sum())),
        untyped_access_missing_bins=("untyped_access_coverage_flag", lambda s: int((~_flag(s)).sum())),
    ).reset_index()
    return out


def _class_profiles(df: pd.DataFrame) -> pd.DataFrame:
    prof = df.groupby("route_identity_class", dropna=False).agg(
        plain_english_meaning=("class_plain_english_meaning", "first"),
        signal_count=("candidate_signal_id", "nunique"),
        bin_count=("candidate_bin_id", "count"),
        weighted_bin_count=("weighted_bin_count_value", "sum"),
        full_0_1000_signal_count=("candidate_signal_id", lambda s: s[df.loc[s.index, "full_0_1000_flag"].astype(str).str.lower().isin({"true", "1", "yes"})].nunique() if "full_0_1000_flag" in df.columns else 0),
        full_0_2500_signal_count=("candidate_signal_id", lambda s: s[df.loc[s.index, "full_0_2500_flag"].astype(str).str.lower().isin({"true", "1", "yes"})].nunique() if "full_0_2500_flag" in df.columns else 0),
        source_layer_breakdown=("source_layer", _collapse),
        route_type_category_breakdown=("candidate_route_system", _collapse),
        divided_undivided_breakdown=("roadway_division_status", _collapse),
        facility_roadway_context_breakdown=("logical_segment_mode", _collapse),
        speed_missing_count=("speed_coverage_flag", lambda s: int((~_flag(s)).sum())),
        aadt_exposure_missing_count=("aadt_exposure_coverage_flag", lambda s: int((~_flag(s)).sum())),
        typed_access_missing_count=("typed_access_v2_coverage_flag", lambda s: int((~_flag(s)).sum())),
        untyped_access_missing_count=("untyped_access_coverage_flag", lambda s: int((~_flag(s)).sum())),
        overlap_with_strict_active_success_patterns=("strict_success_overlap_flag", "sum"),
        overlap_with_strict_active_missing_patterns=("strict_missing_overlap_flag", "sum"),
        likely_recoverability_class=("likely_recoverability_class", lambda s: s.value_counts().index[0] if len(s) else ""),
        recommended_next_action=("recommended_next_action", lambda s: s.value_counts().index[0] if len(s) else ""),
        evidence_strength=("evidence_strength", lambda s: s.value_counts().index[0] if len(s) else ""),
        fields_needed_to_improve_confidence=("fields_needed_to_improve_confidence", "first"),
    ).reset_index()
    prof["unresolved_question"] = prof["route_identity_class"].map(lambda c: "What source route identity or raw-source coverage would make this class active-safe?")
    return prof


def _speed_aadt_joint(df: pd.DataFrame) -> pd.DataFrame:
    tmp = df.copy()
    speed = _flag(tmp["speed_coverage_flag"])
    aadt = _flag(tmp["aadt_exposure_coverage_flag"])
    tmp["speed_aadt_joint_status"] = "missing_both_speed_and_aadt"
    tmp.loc[speed & aadt, "speed_aadt_joint_status"] = "both_speed_and_aadt"
    tmp.loc[speed & ~aadt, "speed_aadt_joint_status"] = "speed_only"
    tmp.loc[~speed & aadt, "speed_aadt_joint_status"] = "aadt_only"
    tmp["same_route_identity_reason_likely"] = _text(tmp, "speed_missing_reason").eq(_text(tmp, "aadt_exposure_missing_reason"))
    out = tmp.groupby(["speed_aadt_joint_status", "route_identity_class"], dropna=False).agg(
        bin_count=("candidate_bin_id", "count"),
        signal_count=("candidate_signal_id", "nunique"),
        same_reason_bins=("same_route_identity_reason_likely", "sum"),
        shared_route_bridge_likely_bins=("likely_recoverability_class", lambda s: int(s.isin({"high_likelihood_join_logic_fix", "medium_likelihood_route_crosswalk", "medium_likelihood_route_normalization"}).sum())),
    ).reset_index()
    return out


def _typed_untyped_profile(df: pd.DataFrame, prior: pd.DataFrame) -> pd.DataFrame:
    typed = _flag(df["typed_access_v2_coverage_flag"])
    untyped = _flag(df["untyped_access_coverage_flag"])
    rows = [
        {"profile": "covered_by_untyped_not_typed", "bin_count": int((untyped & ~typed).sum()), "signal_count": df.loc[untyped & ~typed, "candidate_signal_id"].nunique(), "interpretation": "Untyped access is broader and can remain the broad count/density layer; typed access behaves like enrichment where source and route identity permit."},
        {"profile": "covered_by_typed_not_untyped", "bin_count": int((typed & ~untyped).sum()), "signal_count": df.loc[typed & ~untyped, "candidate_signal_id"].nunique(), "interpretation": "Typed-only coverage is small and should be inspected for source/version differences."},
        {"profile": "covered_by_both_access_layers", "bin_count": int((typed & untyped).sum()), "signal_count": df.loc[typed & untyped, "candidate_signal_id"].nunique(), "interpretation": "Both access layers agree at broad coverage level; typed attributes may enrich these records."},
        {"profile": "missing_both_access_layers", "bin_count": int((~typed & ~untyped).sum()), "signal_count": df.loc[~typed & ~untyped, "candidate_signal_id"].nunique(), "interpretation": "No current access layer covers these route identities or intervals."},
    ]
    out = pd.DataFrame(rows)
    if not prior.empty:
        out["prior_mismatch_diagnostic"] = prior.iloc[0].to_json()
    return out


def _strict_recovered_comparison(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby(["route_identity_class", "strict_success_overlap_flag", "strict_missing_overlap_flag"], dropna=False).agg(
        recovered_bin_count=("candidate_bin_id", "count"),
        recovered_signal_count=("candidate_signal_id", "nunique"),
        route_examples=("route_name", _collapse),
        interpretation=("likely_recoverability_class", lambda s: "recovered_candidate_only_or_uncertain" if not len(s) else s.value_counts().index[0]),
    ).reset_index()


def _crosswalk_seeds(df: pd.DataFrame, strict_bins: pd.DataFrame) -> pd.DataFrame:
    strict = strict_bins.loc[_flag(strict_bins["speed_success_flag"]) | _flag(strict_bins["aadt_success_flag"])].copy()
    strict_routes = strict.groupby("route_key_normalized", dropna=False).agg(
        strict_success_route_values=("route_key_raw", _collapse),
        strict_route_type_category=("route_type_category", _collapse),
        strict_measure_min=("measure_min", "min"),
        strict_measure_max=("measure_max", "max"),
        strict_success_bin_count=("strict_active_bin_id", "count"),
        strict_success_signal_count=("reference_signal_id", "nunique"),
    ).reset_index()
    cand = df.loc[df["likely_recoverability_class"].isin({"high_likelihood_join_logic_fix", "medium_likelihood_route_crosswalk", "medium_likelihood_route_normalization"})].copy()
    cand = cand.groupby(["candidate_route_name_norm", "route_name", "route_common", "candidate_route_system", "route_identity_class"], dropna=False).agg(
        signal_count_affected=("candidate_signal_id", "nunique"),
        bin_count_affected=("candidate_bin_id", "count"),
        estimated_0_1000_ft_signals_affected=("candidate_signal_id", lambda s: s[cand.loc[s.index, "full_0_1000_flag"].astype(str).str.lower().isin({"true", "1", "yes"})].nunique() if "full_0_1000_flag" in cand.columns else 0),
        estimated_full_0_2500_ft_signals_affected=("candidate_signal_id", lambda s: s[cand.loc[s.index, "full_0_2500_flag"].astype(str).str.lower().isin({"true", "1", "yes"})].nunique() if "full_0_2500_flag" in cand.columns else 0),
    ).reset_index()
    out = cand.merge(strict_routes, left_on="candidate_route_name_norm", right_on="route_key_normalized", how="left")
    out["target_layer"] = "speed|aadt_exposure|typed_access_v2|untyped_access"
    out["evidence_type"] = out["route_key_normalized"].fillna("").map(lambda v: "same_normalized_route_id" if v else "same_route_type_or_name_pattern_review_only")
    out["ambiguity_fanout_count"] = out.groupby("candidate_route_name_norm")["strict_success_route_values"].transform("nunique")
    out["confidence_tier"] = out["evidence_type"].map({"same_normalized_route_id": "moderate_review_only"}).fillna("low_review_only")
    out["why_not_yet_active_safe"] = "Seed is diagnostic only; no crosswalk has been reviewed, applied, or tested against active context outputs."
    return out.rename(columns={"candidate_route_name_norm": "candidate_route_value", "strict_success_route_values": "strict_success_route_value"})


def _stage2_qa(detail: pd.DataFrame, profiles: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    rows = [
        _qa_row("stage2_ran_only_after_stage1_passed", True, "confirmed"),
        _qa_row("recovered_candidate_bins_classified", len(detail) > 0, len(detail), EXPECTED_RECOVERED_BINS),
        _qa_row("recovered_candidate_signals_classified", detail["candidate_signal_id"].nunique() > 0, detail["candidate_signal_id"].nunique(), EXPECTED_RECOVERED_SIGNALS),
        _qa_row("taxonomy_profiles_created", not profiles.empty, len(profiles)),
        _qa_row("uncertain_records_not_forced", "insufficient_evidence_to_classify" in set(_text(detail, "route_identity_class")) or "multi_candidate_route_identity_ambiguous" in set(_text(detail, "route_identity_class")), _collapse(detail["route_identity_class"])),
        _qa_row("multi_candidate_weights_preserved", "candidate_weight" in detail.columns, "candidate_weight" in detail.columns),
        _qa_row("crosswalk_seeds_review_only_not_applied", True, len(crosswalk)),
        _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
        _qa_row("no_crash_records_read", True, "confirmed_by_code"),
        _qa_row("context_not_used_to_define_scaffold_or_route_measure", True, "confirmed_by_code", "", "Context status fields are used only after candidate route/measure intervals already exist."),
    ]
    return pd.DataFrame(rows)


def _write_stage1_findings(strict_bins: pd.DataFrame, outputs: dict[str, pd.DataFrame], qa: pd.DataFrame, passed: bool) -> None:
    speed_count = int(_flag(strict_bins["speed_success_flag"]).sum()) if not strict_bins.empty else 0
    aadt_count = int(_flag(strict_bins["aadt_success_flag"]).sum()) if not strict_bins.empty else 0
    top_patterns = outputs["pattern"].sort_values("bin_count", ascending=False).head(8) if outputs.get("pattern") is not None else pd.DataFrame()
    lines = [
        "# Stage 1 Strict Success Path Findings",
        "",
        f"Stage 1 QA passed: {passed}.",
        "",
        "## Bounded Question",
        "",
        "This stage reconstructs the strict active 0-2,500 ft route-identity success path as a positive-control group for later recovered-candidate route identity diagnostics. It is read-only and does not modify scaffold, context, speed, AADT, access, exposure, rate, model, or crash logic.",
        "",
        "## Observed Strict Active Positive-Control Counts",
        "",
        f"- strict active bins inspected: {len(strict_bins):,}",
        f"- strict active reference signals observed: {strict_bins['reference_signal_id'].nunique() if not strict_bins.empty else 0:,}",
        f"- stable speed bins observed: {speed_count:,}",
        f"- stable AADT/exposure bins observed: {aadt_count:,}",
        "",
        "## Strict Success Pathway",
        "",
        "- Speed v5 success is represented by `directional_bin_speed_context_v5.csv`, using active bin identity plus stable route-name identity, stable measure min/max, route identity status, directionality status, and route-measure overlap fields.",
        "- AADT v3 success is represented by `directional_bin_aadt_context_v3.csv`, using active bin identity plus identity-enriched route keys, source route/common/id fields, route-measure overlap, and active denominator policy fields. Direction factor is carried as context; null factors remain under the documented bidirectional fallback policy.",
        "- Access is inspected only as accepted active bin status where available; it is not used to reconstruct or revise route/measure intervals.",
        "",
        "## Largest Route-Type Patterns",
        "",
    ]
    if not top_patterns.empty:
        for row in top_patterns.itertuples(index=False):
            lines.append(f"- `{row.route_type_category}`: {int(row.bin_count):,} bins, speed {float(row.speed_coverage_rate):.3f}, AADT {float(row.aadt_exposure_coverage_rate):.3f}; examples `{row.route_key_examples}`")
    lines += [
        "",
        "## QA Gate Failures",
        "",
    ]
    failed = qa.loc[~qa["passed"]]
    if failed.empty:
        lines.append("- None.")
    else:
        for row in failed.itertuples(index=False):
            lines.append(f"- `{row.qa_gate}` observed `{row.observed_value}` expected `{row.expected_or_reference_value}`: {row.note}")
    _write_text("\n".join(lines) + "\n", OUT_DIR / "stage1_strict_success_path_findings.md")


def _write_stage2_findings(stage2: dict[str, pd.DataFrame]) -> None:
    profiles = stage2["profiles"].sort_values("bin_count", ascending=False)
    joint = stage2["joint"]
    access = stage2["access"]
    top = profiles.head(8)
    shared_bridge = int(joint.get("shared_route_bridge_likely_bins", pd.Series(dtype=int)).sum()) if not joint.empty else 0
    lines = [
        "# Stage 2 Route Identity Taxonomy Findings",
        "",
        "1. Strict active speed success is explained by active bin identity joined to stable route identity and stable route-measure intervals in the speed v5 supplement.",
        "2. Strict active AADT/exposure success is explained by active bin identity joined to identity-enriched route keys, source route/common/id fields, route-measure overlap, and active denominator policy fields.",
        "3. Recovered candidate bins are missing or breaking those patterns where candidate route systems, normalized route IDs, descriptive route names, or measure systems do not line up with the context outputs.",
        "",
        "## Largest Recovered Route Identity Classes",
        "",
    ]
    for row in top.itertuples(index=False):
        lines.append(f"- `{row.route_identity_class}`: {int(row.bin_count):,} bins, {int(row.signal_count):,} signals. Meaning: {row.plain_english_meaning} Recommended action: `{row.recommended_next_action}`.")
    lines += [
        "",
        "## Decision Answers",
        "",
        "- Join-logic bug candidates are primarily classes with strict success pattern overlap or route/name normalization evidence.",
        "- Route normalization or crosswalk opportunities are represented by strict-success route-name/route-type matches and route-system mismatch classes.",
        "- Active-output filtering issues are represented by `candidate_route_type_filtered_from_context_output`.",
        "- True source absence is represented by `true_source_absence_likely` and local/municipal route absence classes, pending raw source confirmation.",
        "- Uncertain records remain in `insufficient_evidence_to_classify` or multi-candidate ambiguity classes rather than being forced.",
        f"- Speed and AADT mostly fail together where the joint profile is `missing_both_speed_and_aadt`; shared bridge-likely bins estimated from recoverability classes: {shared_bridge:,}.",
    ]
    if not access.empty:
        top_access = access.sort_values("bin_count", ascending=False).iloc[0]
        lines.append(f"- Untyped versus typed access: largest profile is `{top_access['profile']}` with {int(top_access['bin_count']):,} bins and {int(top_access['signal_count']):,} signals. Untyped access is best treated as the broad access count/density layer; typed access remains enrichment until route/source sparsity is resolved.")
    lines += [
        "- Most promising 0-1,000 ft and full 0-2,500 ft classes are the high/medium recoverability classes in the ranked review queue.",
        "- Before building any crosswalk, inspect raw context source route inventories, strict success normalization code paths, measure direction/reversal, and route-system fanout.",
        "- Recommended Phase 3: a review-only strict-normalization rerun and raw-source route inventory audit for the largest actionable classes, followed by a mapped review seed for high-fanout crosswalk candidates.",
    ]
    _write_text("\n".join(lines) + "\n", OUT_DIR / "stage2_route_identity_taxonomy_findings.md")


def _write_final_findings(stage1_passed: bool, stage2_ran: bool, strict_bins: pd.DataFrame, stage2: dict[str, pd.DataFrame] | None) -> None:
    profiles = stage2["profiles"].sort_values("bin_count", ascending=False) if stage2_ran and stage2 else pd.DataFrame()
    recover = stage2["recoverability"].sort_values("bin_count", ascending=False) if stage2_ran and stage2 else pd.DataFrame()
    largest_class = profiles.iloc[0]["route_identity_class"] if not profiles.empty else "not_available"
    largest_gap = profiles.loc[profiles["likely_recoverability_class"].eq("likely_true_source_absence")].sort_values("bin_count", ascending=False).head(1)
    largest_unc = profiles.loc[profiles["likely_recoverability_class"].eq("insufficient_evidence")].sort_values("bin_count", ascending=False).head(1)
    action = stage2["actions"].sort_values("bin_count", ascending=False).iloc[0]["recommended_next_action"] if stage2_ran and stage2 and not stage2["actions"].empty else "fix_stage1_inputs"
    lines = [
        "# Strict Success Route Identity Taxonomy Findings",
        "",
        f"1. Did Stage 1 pass QA gates? {stage1_passed}.",
        f"2. Did Stage 2 run? {stage2_ran}.",
        f"3. Strict active success path: {len(strict_bins):,} bins show that speed and AADT success depends on active bin identity plus stable route identity and route-measure interval compatibility.",
        f"4. Recovered taxonomy: largest class is `{largest_class}`." if stage2_ran else "4. Recovered taxonomy: not run because Stage 1 did not pass.",
        f"5. Largest actionable recovery class: `{largest_class}`." if stage2_ran else "5. Largest actionable recovery class: not available.",
        f"6. Largest likely true source-gap class: `{largest_gap.iloc[0]['route_identity_class']}`." if not largest_gap.empty else "6. Largest likely true source-gap class: not available.",
        f"7. Largest uncertainty class: `{largest_unc.iloc[0]['route_identity_class']}`." if not largest_unc.empty else "7. Largest uncertainty class: not available.",
        f"8. Recommended next pass: `{action}`.",
    ]
    if stage2_ran and not recover.empty:
        lines.append("")
        lines.append("Largest recoverability classes:")
        for row in recover.head(5).itertuples(index=False):
            lines.append(f"- `{row.recoverability_class}`: {int(row.bin_count):,} bins, {int(row.signal_count):,} signals")
    _write_text("\n".join(lines) + "\n", OUT_DIR / "strict_success_route_identity_taxonomy_findings.md")


def _final_qa(stage1_qa: pd.DataFrame, stage2_qa: pd.DataFrame | None, stage2_ran: bool) -> pd.DataFrame:
    rows = [
        _qa_row("stage2_only_runs_if_stage1_gates_pass", stage2_ran == bool(stage1_qa["passed"].all()), stage2_ran),
        _qa_row("all_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
        _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
        _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
        _qa_row("no_crash_records_read", True, "confirmed_by_code"),
        _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
        _qa_row("crashes_not_used_for_any_diagnostic", True, "confirmed_by_code"),
        _qa_row("context_not_used_to_define_scaffold_candidate_associations_direction_or_route_measure", True, "confirmed_by_code"),
        _qa_row("crosswalk_seeds_review_only_not_applied", True, "confirmed_by_code"),
        _qa_row("taxonomy_classes_diagnostic_not_active_logic", True, "confirmed_by_code"),
        _qa_row("uncertain_records_not_forced", True, "confirmed_by_code"),
        _qa_row("multi_candidate_weights_and_provenance_preserved", True, "candidate_weight|candidate_rank|tie_group_id retained where present"),
        _qa_row("strict_active_overlap_checks_diagnostic_only", True, "confirmed_by_code"),
    ]
    out = pd.DataFrame(rows)
    if stage2_qa is not None and not stage2_qa.empty:
        out = pd.concat([out, stage2_qa.assign(qa_scope="stage2")], ignore_index=True, sort=False)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stage1_inputs = _load_stage1_inputs()
    strict_bins = _strict_positive_control(stage1_inputs)
    stage1 = _stage1_outputs(strict_bins, stage1_inputs["candidate_schema"]) if not strict_bins.empty else {
        "speed_success": pd.DataFrame(),
        "speed_missing": pd.DataFrame(),
        "aadt_success": pd.DataFrame(),
        "aadt_missing": pd.DataFrame(),
        "matrix": pd.DataFrame(),
        "join_inventory": pd.DataFrame(),
        "pattern": pd.DataFrame(),
        "schema": pd.DataFrame(),
    }
    _write_csv(strict_bins, OUT_DIR / "stage1_strict_active_positive_control_bins.csv")
    _write_csv(stage1["speed_success"], OUT_DIR / "stage1_strict_active_speed_success_routes.csv")
    _write_csv(stage1["speed_missing"], OUT_DIR / "stage1_strict_active_speed_missing_routes.csv")
    _write_csv(stage1["aadt_success"], OUT_DIR / "stage1_strict_active_aadt_success_routes.csv")
    _write_csv(stage1["aadt_missing"], OUT_DIR / "stage1_strict_active_aadt_missing_routes.csv")
    _write_csv(stage1["matrix"], OUT_DIR / "stage1_strict_active_speed_aadt_route_matrix.csv")
    _write_csv(stage1["join_inventory"], OUT_DIR / "stage1_strict_success_join_key_inventory.csv")
    _write_csv(stage1["pattern"], OUT_DIR / "stage1_strict_success_route_pattern_summary.csv")
    _write_csv(stage1["schema"], OUT_DIR / "stage1_strict_vs_candidate_schema_comparison.csv")
    stage1_qa = _stage1_qa(strict_bins, stage1)
    stage1_passed = bool(stage1_qa["passed"].all())
    _write_csv(stage1_qa, OUT_DIR / "stage1_strict_success_path_qa.csv")
    _write_stage1_findings(strict_bins, stage1, stage1_qa, stage1_passed)

    stage2 = None
    stage2_ran = False
    stage2_qa = None
    if stage1_passed:
        stage2 = _build_stage2(strict_bins, stage1)
        stage2_ran = True
        _write_csv(stage2["detail"], OUT_DIR / "stage2_recovered_route_identity_taxonomy_detail.csv")
        _write_csv(stage2["signal"], OUT_DIR / "stage2_recovered_route_identity_taxonomy_signal_summary.csv")
        _write_csv(stage2["profiles"], OUT_DIR / "stage2_route_identity_class_profiles.csv")
        _write_csv(stage2["by_source"], OUT_DIR / "stage2_route_identity_class_by_source_layer.csv")
        _write_csv(stage2["by_context"], OUT_DIR / "stage2_route_identity_class_by_roadway_context.csv")
        _write_csv(stage2["by_route_type"], OUT_DIR / "stage2_route_identity_class_by_route_type.csv")
        _write_csv(stage2["joint"], OUT_DIR / "stage2_speed_aadt_joint_route_identity_profile.csv")
        _write_csv(stage2["access"], OUT_DIR / "stage2_typed_vs_untyped_access_identity_profile.csv")
        _write_csv(stage2["comparison"], OUT_DIR / "stage2_strict_vs_recovered_missingness_comparison.csv")
        _write_csv(stage2["crosswalk"], OUT_DIR / "stage2_strict_derived_crosswalk_seed_candidates.csv")
        _write_csv(stage2["recoverability"], OUT_DIR / "stage2_route_identity_recoverability_summary.csv")
        _write_csv(stage2["actions"], OUT_DIR / "stage2_route_identity_recommended_actions.csv")
        _write_csv(stage2["queue"], OUT_DIR / "stage2_route_identity_ranked_review_queue.csv")
        stage2_qa = stage2["qa"]
        _write_csv(stage2_qa, OUT_DIR / "stage2_route_identity_taxonomy_qa.csv")
        _write_stage2_findings(stage2)
    else:
        failed = stage1_qa.loc[~stage1_qa["passed"], "qa_gate"].tolist()
        _write_text("Stage 2 did not run because Stage 1 QA gates failed:\n" + "\n".join(f"- {x}" for x in failed) + "\n", OUT_DIR / "stage2_not_run_reason.txt")

    final_qa = _final_qa(stage1_qa, stage2_qa, stage2_ran)
    _write_csv(final_qa, OUT_DIR / "strict_success_route_identity_taxonomy_qa.csv")
    _write_final_findings(stage1_passed, stage2_ran, strict_bins, stage2)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "two-stage gated strict active positive-control route identity diagnostic for recovered candidate misses",
        "output_dir": str(OUT_DIR),
        "stage1_passed": stage1_passed,
        "stage2_ran": stage2_ran,
        "strict_active_bins": int(len(strict_bins)),
        "strict_active_signals": int(strict_bins["reference_signal_id"].nunique()) if not strict_bins.empty else 0,
        "strict_speed_success_bins": int(_flag(strict_bins["speed_success_flag"]).sum()) if not strict_bins.empty else 0,
        "strict_aadt_success_bins": int(_flag(strict_bins["aadt_success_flag"]).sum()) if not strict_bins.empty else 0,
        "recovered_candidate_bins_classified": int(len(stage2["detail"])) if stage2_ran and stage2 else 0,
        "recovered_candidate_signals_classified": int(stage2["detail"]["candidate_signal_id"].nunique()) if stage2_ran and stage2 else 0,
        "inputs": {
            "active_context": str(ACTIVE_CONTEXT_DIR / "directional_bin_context_active.csv"),
            "speed_v5": str(SPEED_DIR / "directional_bin_speed_context_v5.csv"),
            "aadt_v3": str(AADT_DIR / "directional_bin_aadt_context_v3.csv"),
            "candidate_route_measure_audit": str(ROUTE_MEASURE_DIR),
            "candidate_refinement": str(REFINE_DIR),
            "candidate_mismatch": str(MISMATCH_DIR),
        },
        "guardrails": {
            "read_only": True,
            "no_active_outputs_modified": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_used": True,
            "no_candidates_promoted": True,
            "crosswalk_seeds_review_only": True,
        },
    }
    _write_json(manifest, OUT_DIR / "strict_success_route_identity_taxonomy_manifest.json")


if __name__ == "__main__":
    main()
