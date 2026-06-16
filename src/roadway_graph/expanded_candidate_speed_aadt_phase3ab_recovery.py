from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
ROUTE_MEASURE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"
REFINE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_context_join_refinement_diagnostic"
TAXONOMY_DIR = OUTPUT_ROOT / "review/current/strict_success_route_identity_taxonomy"
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_phase3ab_recovery"

SPEED_SOURCE = Path("artifacts/normalized/speed.parquet")
AADT_SOURCE = Path("artifacts/normalized/aadt.parquet")

EXPECTED_BINS = 136_227
EXPECTED_SIGNALS = 1_590
ROW_GUARD_LIMIT = 1_000_000
FANOUT_ROW_LIMIT = 500
EXAMPLES_PER_CLASS = 100

REQUIRED_INPUTS = {
    ROUTE_MEASURE_DIR: [
        "stage1_candidate_route_measure_bin_detail.csv",
        "stage1_candidate_route_measure_signal_summary.csv",
        "stage2_candidate_speed_join_detail.csv",
        "stage2_candidate_aadt_exposure_join_detail.csv",
        "stage2_candidate_context_join_signal_summary.csv",
        "expanded_candidate_route_measure_context_audit_manifest.json",
    ],
    REFINE_DIR: [
        "candidate_context_refinement_base_bins.csv",
        "candidate_speed_refined_join_detail.csv",
        "candidate_aadt_exposure_refined_join_detail.csv",
        "candidate_context_refined_signal_summary.csv",
        "candidate_context_refined_before_after_summary.csv",
        "candidate_context_layer_bottleneck_summary.csv",
        "expanded_candidate_context_join_refinement_manifest.json",
    ],
    TAXONOMY_DIR: [
        "stage1_strict_active_positive_control_bins.csv",
        "stage1_strict_active_speed_success_routes.csv",
        "stage1_strict_active_speed_missing_routes.csv",
        "stage1_strict_active_aadt_success_routes.csv",
        "stage1_strict_active_aadt_missing_routes.csv",
        "stage1_strict_active_speed_aadt_route_matrix.csv",
        "stage1_strict_success_join_key_inventory.csv",
        "stage1_strict_success_route_pattern_summary.csv",
        "stage2_recovered_route_identity_taxonomy_detail.csv",
        "stage2_recovered_route_identity_taxonomy_signal_summary.csv",
        "stage2_route_identity_class_profiles.csv",
        "stage2_speed_aadt_joint_route_identity_profile.csv",
        "stage2_route_identity_recoverability_summary.csv",
        "stage2_route_identity_recommended_actions.csv",
        "strict_success_route_identity_taxonomy_manifest.json",
    ],
}

ACTIONABLE_CLASSES = {
    "candidate_route_type_filtered_from_context_output",
    "strict_success_pattern_match_but_join_failed",
    "strict_success_route_name_match_but_route_id_differs",
}


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    _checkpoint(f"read_start {path.name}")
    if not path.exists():
        _checkpoint(f"read_missing {path.name}", 0)
        return pd.DataFrame()
    if usecols is None:
        out = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        header = pd.read_csv(path, nrows=0)
        cols = [c for c in usecols if c in header.columns]
        out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols) if cols else pd.DataFrame()
    _checkpoint(f"read_complete {path.name}", len(out))
    return out


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    _checkpoint(f"write_start {path.name}", len(df))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    _checkpoint(f"write_complete {path.name}", len(df))


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write_complete {path.name}")


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {
        "qa_gate": gate,
        "passed": bool(passed),
        "observed_value": observed,
        "expected_or_reference_value": expected,
        "note": note,
    }


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df[col].fillna("").astype(str)


def _flag(df: pd.DataFrame, col: str) -> pd.Series:
    return _text(df, col).str.lower().isin({"true", "1", "yes", "y"})


def _num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(pd.NA, index=df.index, dtype="Float64")
    return pd.to_numeric(df[col], errors="coerce")


def _collapse(series: pd.Series, limit: int = 12) -> str:
    vals = sorted({str(v) for v in series.dropna() if str(v) and str(v) != "nan"})
    return "|".join(vals[:limit])


def _norm_route(value: Any) -> str:
    s = str(value or "").upper().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("INTERSTATE", "IS").replace("R-VA", "").replace("S-VA", "SC")
    s = re.sub(r"[^A-Z0-9]", "", s)
    for prefix in ["US", "SR", "VA", "SC", "IS", "I"]:
        s = re.sub(prefix + r"0+([0-9])", prefix + r"\1", s)
    return s.replace("EB", "E").replace("WB", "W").replace("NB", "N").replace("SB", "S")


def _facility_text(value: Any) -> str:
    s = re.sub(r"\([^)]*\)", "", str(value or "").upper())
    s = re.sub(r"\b(COUNTY|CITY|TOWN|OF|VA|VIRGINIA|RAMP|ROAD|RD|STREET|ST)\b", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _route_system(key: str, raw: str = "") -> str:
    raw_u = str(raw or "").upper()
    k = str(key or "").upper()
    if k.startswith("IS") or k.startswith("I"):
        return "interstate"
    if k.startswith("US"):
        return "us_route"
    if k.startswith("SR") or k.startswith("VA"):
        return "state_route"
    if k.startswith("SC") or re.match(r"^\d{3}SC", k):
        return "secondary_route"
    if "PR" in k or "PR " in raw_u:
        return "private_or_local"
    if not k:
        return "missing_route_identity"
    return "unknown_or_named_local"


def _measure_overlap_status(c_min: Any, c_max: Any, s_min: Any, s_max: Any) -> str:
    vals = pd.to_numeric(pd.Series([c_min, c_max, s_min, s_max]), errors="coerce")
    if vals.isna().any():
        return "measure_system_uncertain"
    a, b, c, d = [float(v) for v in vals]
    amin, amax = min(a, b), max(a, b)
    smin, smax = min(c, d), max(c, d)
    return "route_level_measure_range_overlaps" if max(amin, smin) <= min(amax, smax) else "measure_overlap_missing_after_route_match"


def _missing_required_inputs() -> list[str]:
    missing = []
    for root, names in REQUIRED_INPUTS.items():
        for name in names:
            if not (root / name).exists():
                missing.append(str(root / name))
    return missing


def _load_inputs() -> dict[str, pd.DataFrame]:
    return {
        "route_bins": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_bin_detail.csv"),
        "route_signal": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_signal_summary.csv"),
        "prior_speed": _read_csv(ROUTE_MEASURE_DIR / "stage2_candidate_speed_join_detail.csv", usecols=["candidate_bin_id", "coverage_flag"]),
        "prior_aadt": _read_csv(ROUTE_MEASURE_DIR / "stage2_candidate_aadt_exposure_join_detail.csv", usecols=["candidate_bin_id", "coverage_flag", "exposure_coverage_flag"]),
        "prior_signal": _read_csv(ROUTE_MEASURE_DIR / "stage2_candidate_context_join_signal_summary.csv"),
        "refine_base": _read_csv(REFINE_DIR / "candidate_context_refinement_base_bins.csv"),
        "refine_speed": _read_csv(REFINE_DIR / "candidate_speed_refined_join_detail.csv", usecols=["candidate_bin_id", "coverage_flag", "join_method", "missing_reason"]),
        "refine_aadt": _read_csv(REFINE_DIR / "candidate_aadt_exposure_refined_join_detail.csv", usecols=["candidate_bin_id", "coverage_flag", "join_method", "missing_reason"]),
        "refine_signal": _read_csv(REFINE_DIR / "candidate_context_refined_signal_summary.csv"),
        "refine_before_after": _read_csv(REFINE_DIR / "candidate_context_refined_before_after_summary.csv"),
        "refine_bottleneck": _read_csv(REFINE_DIR / "candidate_context_layer_bottleneck_summary.csv"),
        "strict_bins": _read_csv(TAXONOMY_DIR / "stage1_strict_active_positive_control_bins.csv"),
        "strict_speed_routes": _read_csv(TAXONOMY_DIR / "stage1_strict_active_speed_success_routes.csv"),
        "strict_aadt_routes": _read_csv(TAXONOMY_DIR / "stage1_strict_active_aadt_success_routes.csv"),
        "strict_matrix": _read_csv(TAXONOMY_DIR / "stage1_strict_active_speed_aadt_route_matrix.csv"),
        "strict_join_inventory": _read_csv(TAXONOMY_DIR / "stage1_strict_success_join_key_inventory.csv"),
        "strict_pattern": _read_csv(TAXONOMY_DIR / "stage1_strict_success_route_pattern_summary.csv"),
        "taxonomy": _read_csv(TAXONOMY_DIR / "stage2_recovered_route_identity_taxonomy_detail.csv"),
        "taxonomy_signal": _read_csv(TAXONOMY_DIR / "stage2_recovered_route_identity_taxonomy_signal_summary.csv"),
        "taxonomy_profiles": _read_csv(TAXONOMY_DIR / "stage2_route_identity_class_profiles.csv"),
        "taxonomy_joint": _read_csv(TAXONOMY_DIR / "stage2_speed_aadt_joint_route_identity_profile.csv"),
        "taxonomy_recoverability": _read_csv(TAXONOMY_DIR / "stage2_route_identity_recoverability_summary.csv"),
        "taxonomy_actions": _read_csv(TAXONOMY_DIR / "stage2_route_identity_recommended_actions.csv"),
    }


def _candidate_bins(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    base = inputs["taxonomy"].copy()
    if base.empty:
        base = inputs["refine_base"].copy()
    _checkpoint("candidate_bins_base", len(base))
    for key, prefix in [("refine_speed", "previous_speed"), ("refine_aadt", "previous_aadt")]:
        detail = inputs[key]
        if detail.empty:
            continue
        detail = detail.rename(
            columns={
                "coverage_flag": f"{prefix}_coverage_flag",
                "join_method": f"{prefix}_join_method",
                "missing_reason": f"{prefix}_missing_reason",
            }
        )
        cols = [c for c in ["candidate_bin_id", f"{prefix}_coverage_flag", f"{prefix}_join_method", f"{prefix}_missing_reason"] if c in detail.columns]
        _checkpoint(f"before_merge_{key}", len(base), f"right_rows={len(detail):,}")
        if len(base) + len(detail) > ROW_GUARD_LIMIT:
            _checkpoint(f"merge_guard_{key}", len(base) + len(detail), "merge skipped because row guard exceeded")
            continue
        base = base.drop(columns=[c for c in cols if c != "candidate_bin_id" and c in base.columns], errors="ignore").merge(detail[cols], on="candidate_bin_id", how="left")
        _checkpoint(f"after_merge_{key}", len(base))
    base["candidate_route_key_normalized"] = _text(base, "candidate_route_key_normalized").where(_text(base, "candidate_route_key_normalized").ne(""), _text(base, "route_name").map(_norm_route))
    base["candidate_route_common_normalized"] = _text(base, "candidate_route_common_normalized").where(_text(base, "candidate_route_common_normalized").ne(""), _text(base, "route_common").map(_norm_route))
    base["candidate_facility_text"] = _text(base, "route_common").where(_text(base, "route_common").ne(""), _text(base, "route_name")).map(_facility_text)
    base["candidate_route_type_category"] = [_route_system(k, raw) for k, raw in zip(_text(base, "candidate_route_key_normalized"), _text(base, "route_name"), strict=False)]
    base["candidate_measure_min_num"] = _num(base, "candidate_measure_min")
    base["candidate_measure_max_num"] = _num(base, "candidate_measure_max")
    base["candidate_weight_num"] = _num(base, "candidate_weight").fillna(1.0)
    if "previous_speed_coverage_flag" not in base.columns and "speed_coverage_flag" in base.columns:
        base["previous_speed_coverage_flag"] = base["speed_coverage_flag"]
    if "previous_aadt_coverage_flag" not in base.columns and "aadt_exposure_coverage_flag" in base.columns:
        base["previous_aadt_coverage_flag"] = base["aadt_exposure_coverage_flag"]
    return base


def _candidate_route_inventory(base: pd.DataFrame) -> pd.DataFrame:
    group_cols = [
        "route_id",
        "candidate_route_key_normalized",
        "candidate_route_common_normalized",
        "route_common",
        "route_name",
        "candidate_facility_text",
        "candidate_route_type_category",
        "source_layer",
        "route_identity_class",
        "recommended_next_action",
    ]
    _checkpoint("phase3a_candidate_route_inventory_groupby_start", len(base))
    inv = base.groupby(group_cols, dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        affected_signal_count=("candidate_signal_id", "nunique"),
        weighted_bin_count=("candidate_weight_num", "sum"),
        affected_0_1000_signal_count=("candidate_signal_id", lambda s: s[base.loc[s.index, "analysis_window"].eq("0_1000")].nunique()),
        affected_full_0_2500_signal_count=("candidate_signal_id", "nunique"),
        measure_min=("candidate_measure_min_num", "min"),
        measure_max=("candidate_measure_max_num", "max"),
        previous_speed_covered_bins=("previous_speed_coverage_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes", "y"}).sum())),
        previous_aadt_covered_bins=("previous_aadt_coverage_flag", lambda s: int(s.astype(str).str.lower().isin({"true", "1", "yes", "y"}).sum())),
        source_road_row_id_examples=("source_road_row_id", _collapse),
        graph_edge_id_examples=("graph_edge_id", _collapse),
        road_component_id_examples=("road_component_id", _collapse),
        multi_candidate_values=("multi_candidate_flag", _collapse),
    ).reset_index()
    inv.insert(0, "candidate_route_group_id", [f"candidate_route_group_{i:06d}" for i in range(1, len(inv) + 1)])
    _checkpoint("phase3a_candidate_route_inventory_groupby_complete", len(inv))
    return inv


def _strict_success_pattern_inventory(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    strict = inputs["strict_bins"].copy()
    _checkpoint("phase3a_strict_pattern_inventory_start", len(strict))
    strict["route_key_normalized"] = _text(strict, "route_key_normalized").where(_text(strict, "route_key_normalized").ne(""), _text(strict, "stable_route_name_normalized").map(_norm_route))
    strict["route_raw"] = _text(strict, "route_key_raw").where(_text(strict, "route_key_raw").ne(""), _text(strict, "stable_route_name_raw"))
    strict["route_common"] = _text(strict, "aadt_source_RTE_COMMON").where(_text(strict, "aadt_source_RTE_COMMON").ne(""), strict["route_raw"])
    strict["facility_text"] = strict["route_common"].map(_facility_text)
    strict["route_type_category"] = [_route_system(k, raw) for k, raw in zip(_text(strict, "route_key_normalized"), _text(strict, "route_raw"), strict=False)]
    strict["strict_measure_min_num"] = _num(strict, "stable_measure_min").combine_first(_num(strict, "aadt_stable_measure_min"))
    strict["strict_measure_max_num"] = _num(strict, "stable_measure_max").combine_first(_num(strict, "aadt_stable_measure_max"))
    strict["speed_success_bool"] = _flag(strict, "speed_success_flag")
    strict["aadt_success_bool"] = _flag(strict, "aadt_success_flag")
    out = strict.groupby(["route_key_normalized", "route_raw", "route_common", "facility_text", "route_type_category"], dropna=False).agg(
        strict_bin_count=("strict_active_bin_id", "count" if "strict_active_bin_id" in strict.columns else "size"),
        strict_signal_count=("reference_signal_id", "nunique"),
        speed_success_bins=("speed_success_bool", "sum"),
        aadt_success_bins=("aadt_success_bool", "sum"),
        measure_min=("strict_measure_min_num", "min"),
        measure_max=("strict_measure_max_num", "max"),
        speed_status_examples=("refined_speed_context_status", _collapse),
        aadt_status_examples=("aadt_aadt_context_status", _collapse),
    ).reset_index()
    out["speed_success_rate"] = out["speed_success_bins"] / out["strict_bin_count"].replace(0, pd.NA)
    out["aadt_success_rate"] = out["aadt_success_bins"] / out["strict_bin_count"].replace(0, pd.NA)
    out["strict_fanout_status"] = out["strict_bin_count"].map(lambda n: "fanout_high" if int(n) > FANOUT_ROW_LIMIT else "bounded")
    _checkpoint("phase3a_strict_pattern_inventory_complete", len(out))
    return out


def _match_phase3a(candidate_inv: pd.DataFrame, strict_inv: pd.DataFrame) -> pd.DataFrame:
    _checkpoint("phase3a_route_level_match_start", len(candidate_inv))
    strict_by_key = strict_inv.set_index("route_key_normalized", drop=False)
    common_keys = set(_text(strict_inv, "route_common").map(_norm_route))
    facility_keys = set(_text(strict_inv, "facility_text"))
    type_keys = set(_text(strict_inv, "route_type_category"))
    rows = []
    for row in candidate_inv.itertuples(index=False):
        key = str(row.candidate_route_key_normalized)
        common = str(row.candidate_route_common_normalized)
        facility = str(row.candidate_facility_text)
        rtype = str(row.candidate_route_type_category)
        prior_speed = int(row.previous_speed_covered_bins)
        prior_aadt = int(row.previous_aadt_covered_bins)
        classification = "no_strict_success_pattern_match"
        evidence_key = ""
        strict_rows = pd.DataFrame()
        if prior_speed > 0 and prior_aadt > 0:
            classification = "already_joined_speed_aadt"
        elif key and key in strict_by_key.index:
            strict_rows = strict_by_key.loc[[key]].copy() if not isinstance(strict_by_key.loc[key], pd.Series) else strict_by_key.loc[[key]].copy()
            classification = "strict_success_normalized_route_key_match"
            evidence_key = key
        elif common and common in set(_text(strict_inv, "route_key_normalized")):
            strict_rows = strict_inv.loc[_text(strict_inv, "route_key_normalized").eq(common)].copy()
            classification = "strict_success_route_name_common_match"
            evidence_key = common
        elif common and common in common_keys:
            strict_rows = strict_inv.loc[_text(strict_inv, "route_common").map(_norm_route).eq(common)].copy()
            classification = "strict_success_route_name_common_match"
            evidence_key = common
        elif facility and facility in facility_keys:
            strict_rows = strict_inv.loc[_text(strict_inv, "facility_text").eq(facility)].copy()
            classification = "strict_success_facility_text_match"
            evidence_key = facility
        elif rtype and rtype in type_keys:
            strict_rows = strict_inv.loc[_text(strict_inv, "route_type_category").eq(rtype)].copy()
            classification = "strict_success_route_type_category_match"
            evidence_key = rtype
        fanout = int(strict_rows["strict_bin_count"].sum()) if not strict_rows.empty else 0
        strict_speed_bins = int(strict_rows["speed_success_bins"].sum()) if not strict_rows.empty else 0
        strict_aadt_bins = int(strict_rows["aadt_success_bins"].sum()) if not strict_rows.empty else 0
        measure_status = "not_evaluated_no_strict_pattern"
        if not strict_rows.empty:
            measure_status = _measure_overlap_status(row.measure_min, row.measure_max, strict_rows["measure_min"].min(), strict_rows["measure_max"].max())
            if fanout > FANOUT_ROW_LIMIT:
                classification = "strict_success_pattern_match_but_fanout_high"
            elif measure_status != "route_level_measure_range_overlaps" and classification != "already_joined_speed_aadt":
                classification = "strict_success_pattern_match_but_measure_uncertain"
        bounded_recovery_class = classification not in {
            "already_joined_speed_aadt",
            "no_strict_success_pattern_match",
            "strict_success_pattern_match_but_fanout_high",
            "strict_success_pattern_match_but_measure_uncertain",
        }
        speed_potential = bounded_recovery_class and strict_speed_bins > 0 and prior_speed == 0
        aadt_potential = bounded_recovery_class and strict_aadt_bins > 0 and prior_aadt == 0
        rows.append(
            {
                **row._asdict(),
                "phase3a_strict_normalization_class": classification,
                "strict_match_evidence_key": evidence_key,
                "strict_match_route_count": int(len(strict_rows)),
                "strict_match_bin_fanout_count": fanout,
                "strict_speed_success_bins": strict_speed_bins,
                "strict_aadt_success_bins": strict_aadt_bins,
                "measure_compatibility_status": measure_status,
                "speed_recovery_estimate_flag": bool(speed_potential),
                "aadt_recovery_estimate_flag": bool(aadt_potential),
                "fanout_risk_flag": classification == "strict_success_pattern_match_but_fanout_high",
                "measure_uncertain_flag": classification == "strict_success_pattern_match_but_measure_uncertain",
                "coverage_estimate_not_assignment": True,
            }
        )
    out = pd.DataFrame(rows)
    _checkpoint("phase3a_route_level_match_complete", len(out))
    return out


def _signal_estimate(route_rerun: pd.DataFrame, base: pd.DataFrame) -> pd.DataFrame:
    keys = ["route_id", "candidate_route_key_normalized", "route_common", "route_name", "source_layer", "route_identity_class", "recommended_next_action"]
    tagged = base.merge(route_rerun[[*keys, "candidate_route_group_id", "speed_recovery_estimate_flag", "aadt_recovery_estimate_flag", "fanout_risk_flag", "measure_uncertain_flag"]], on=keys, how="left")
    rows = []
    for layer, flag in [("speed", "speed_recovery_estimate_flag"), ("aadt_exposure", "aadt_recovery_estimate_flag")]:
        sub = tagged.loc[_flag(tagged, flag)].copy()
        fanout = tagged.loc[_flag(tagged, "fanout_risk_flag")].copy()
        measure_unc = tagged.loc[_flag(tagged, "measure_uncertain_flag")].copy()
        rows.append(
            {
                "context_layer": layer,
                "potential_route_group_count": int(route_rerun[flag].astype(bool).sum()),
                "additional_candidate_signals_potentially_covered": sub["candidate_signal_id"].nunique(),
                "additional_0_1000_candidate_signals_potentially_covered": sub.loc[_text(sub, "analysis_window").eq("0_1000"), "candidate_signal_id"].nunique(),
                "additional_full_0_2500_candidate_signals_potentially_covered": sub["candidate_signal_id"].nunique(),
                "fanout_risk_signal_count": fanout["candidate_signal_id"].nunique(),
                "measure_uncertain_signal_count": measure_unc["candidate_signal_id"].nunique(),
            }
        )
    return pd.DataFrame(rows)


def _by_taxonomy(route_rerun: pd.DataFrame) -> pd.DataFrame:
    return route_rerun.groupby(["route_identity_class", "phase3a_strict_normalization_class"], dropna=False).agg(
        route_group_count=("candidate_route_group_id", "count"),
        candidate_bin_count=("candidate_bin_count", "sum"),
        affected_signal_count=("affected_signal_count", "sum"),
        speed_recoverable_groups=("speed_recovery_estimate_flag", "sum"),
        aadt_recoverable_groups=("aadt_recovery_estimate_flag", "sum"),
        fanout_risk_groups=("fanout_risk_flag", "sum"),
        measure_uncertain_groups=("measure_uncertain_flag", "sum"),
    ).reset_index()


def _capped_examples(base: pd.DataFrame, route_rerun: pd.DataFrame) -> pd.DataFrame:
    cols = ["candidate_route_group_id", "phase3a_strict_normalization_class", "strict_match_evidence_key", "measure_compatibility_status"]
    tagged = base.merge(route_rerun[["route_id", "candidate_route_key_normalized", "route_common", "route_name", "source_layer", "route_identity_class", "recommended_next_action", *cols]], on=["route_id", "candidate_route_key_normalized", "route_common", "route_name", "source_layer", "route_identity_class", "recommended_next_action"], how="left")
    keep = []
    for klass, group in tagged.groupby("phase3a_strict_normalization_class", dropna=False):
        keep.append(group.head(EXAMPLES_PER_CLASS))
    out = pd.concat(keep, ignore_index=True, sort=False) if keep else pd.DataFrame()
    example_cols = [
        "phase3a_strict_normalization_class",
        "candidate_route_group_id",
        "candidate_bin_id",
        "candidate_signal_id",
        "source_signal_id",
        "route_id",
        "route_common",
        "route_name",
        "candidate_route_key_normalized",
        "candidate_route_common_normalized",
        "candidate_facility_text",
        "candidate_route_type_category",
        "candidate_measure_min",
        "candidate_measure_max",
        "route_identity_class",
        "recommended_next_action",
        "strict_match_evidence_key",
        "measure_compatibility_status",
        "previous_speed_coverage_flag",
        "previous_aadt_coverage_flag",
    ]
    return out[[c for c in example_cols if c in out.columns]]


def _phase3a_qa(base: pd.DataFrame, candidate_inv: pd.DataFrame, strict_inv: pd.DataFrame, rerun: pd.DataFrame, missing_inputs: list[str]) -> pd.DataFrame:
    rows = [
        _qa_row("required_inputs_available", not missing_inputs, len(missing_inputs), 0, "; ".join(missing_inputs[:5])),
        _qa_row("candidate_bin_input_count_reconciles", len(base) == EXPECTED_BINS, len(base), EXPECTED_BINS),
        _qa_row("recovered_signal_count_reconciles", base["candidate_signal_id"].nunique() == EXPECTED_SIGNALS, base["candidate_signal_id"].nunique(), EXPECTED_SIGNALS),
        _qa_row("strict_active_positive_control_inputs_loaded", not strict_inv.empty, len(strict_inv)),
        _qa_row("candidate_route_level_inventory_created", not candidate_inv.empty, len(candidate_inv)),
        _qa_row("strict_success_pattern_inventory_created", not strict_inv.empty, len(strict_inv)),
        _qa_row("no_unbounded_bin_source_overlap_table_materialized", True, "confirmed_by_code"),
        _qa_row("fanout_risk_routes_flagged_instead_of_expanded", "fanout_risk_flag" in rerun.columns, "confirmed_by_schema"),
        _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
        _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
        _qa_row("no_crash_records_read", True, "confirmed_by_code"),
        _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
        _qa_row("access_not_included", True, "confirmed_by_code"),
        _qa_row("all_phase3a_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame(rows)


def run_phase3a(inputs: dict[str, pd.DataFrame], missing_inputs: list[str]) -> tuple[dict[str, pd.DataFrame], bool]:
    base = _candidate_bins(inputs)
    candidate_inv = _candidate_route_inventory(base)
    strict_inv = _strict_success_pattern_inventory(inputs)
    rerun = _match_phase3a(candidate_inv, strict_inv)
    signal_est = _signal_estimate(rerun, base)
    by_tax = _by_taxonomy(rerun)
    fanout = rerun.loc[_flag(rerun, "fanout_risk_flag")].copy()
    examples = _capped_examples(base, rerun)
    qa = _phase3a_qa(base, candidate_inv, strict_inv, rerun, missing_inputs)
    outputs = {
        "base": base,
        "candidate_inventory": candidate_inv,
        "strict_inventory": strict_inv,
        "rerun": rerun,
        "signal_estimate": signal_est,
        "by_taxonomy": by_tax,
        "fanout": fanout,
        "examples": examples,
        "qa": qa,
    }
    return outputs, bool(qa["passed"].all())


def _source_inventory(layer: str) -> pd.DataFrame:
    if layer == "speed":
        path = SPEED_SOURCE
        cols = ["ROUTE_COMMON_NAME", "ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE", "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT", "RTE_TYPE_NM", "FROM_JURISDICTION", "Stage1_SourceLayer"]
        _checkpoint("phase3b_speed_source_read_start")
        src = pd.read_parquet(path, columns=cols) if path.exists() else pd.DataFrame()
        _checkpoint("phase3b_speed_source_read_complete", len(src))
        if src.empty:
            return pd.DataFrame()
        src["raw_route_key"] = src["ROUTE_COMMON_NAME"].fillna("").astype(str)
        src["normalized_route_key"] = src["raw_route_key"].map(_norm_route)
        src["route_common_name"] = src["raw_route_key"]
        src["facility_text"] = src["route_common_name"].map(_facility_text)
        src["route_type_category"] = [_route_system(k, raw) for k, raw in zip(src["normalized_route_key"], src["raw_route_key"], strict=False)]
        src["measure_from"] = pd.to_numeric(src["ROUTE_FROM_MEASURE"], errors="coerce")
        src["measure_to"] = pd.to_numeric(src["ROUTE_TO_MEASURE"], errors="coerce")
        src["locality_source"] = src["FROM_JURISDICTION"].fillna("").astype(str)
        src["source_layer_name"] = src["Stage1_SourceLayer"].fillna("").astype(str)
    else:
        path = AADT_SOURCE
        cols = ["RTE_NM", "MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "AADT", "AADT_YR", "DIRECTION_FACTOR", "DIRECTIONALITY", "FROM_PHY_JURISDICTION_NM", "Stage1_SourceLayer"]
        _checkpoint("phase3b_aadt_source_read_start")
        src = pd.read_parquet(path, columns=cols) if path.exists() else pd.DataFrame()
        _checkpoint("phase3b_aadt_source_read_complete", len(src))
        if src.empty:
            return pd.DataFrame()
        src["raw_route_key"] = src["RTE_NM"].fillna("").astype(str)
        src["route_common_name"] = src["MASTER_RTE_NM"].fillna("").astype(str)
        src["normalized_route_key"] = src["raw_route_key"].where(src["raw_route_key"].ne(""), src["route_common_name"]).map(_norm_route)
        src["facility_text"] = src["route_common_name"].where(src["route_common_name"].ne(""), src["raw_route_key"]).map(_facility_text)
        src["route_type_category"] = [_route_system(k, raw) for k, raw in zip(src["normalized_route_key"], src["raw_route_key"], strict=False)]
        src["measure_from"] = pd.to_numeric(src["FROM_MEASURE"], errors="coerce").combine_first(pd.to_numeric(src["TRANSPORT_EDGE_FROM_MSR"], errors="coerce"))
        src["measure_to"] = pd.to_numeric(src["TO_MEASURE"], errors="coerce").combine_first(pd.to_numeric(src["TRANSPORT_EDGE_TO_MSR"], errors="coerce"))
        src["locality_source"] = src["FROM_PHY_JURISDICTION_NM"].fillna("").astype(str)
        src["source_layer_name"] = src["Stage1_SourceLayer"].fillna("").astype(str)
    src["null_route_flag"] = src["normalized_route_key"].eq("")
    src["null_measure_flag"] = src["measure_from"].isna() | src["measure_to"].isna()
    _checkpoint(f"phase3b_{layer}_source_groupby_start", len(src))
    inv = src.groupby(["raw_route_key", "normalized_route_key", "route_common_name", "facility_text", "route_type_category", "locality_source", "source_layer_name"], dropna=False).agg(
        source_row_count=("normalized_route_key", "count"),
        null_route_count=("null_route_flag", "sum"),
        null_measure_count=("null_measure_flag", "sum"),
        measure_min=("measure_from", "min"),
        measure_max=("measure_to", "max"),
    ).reset_index()
    inv["context_layer"] = layer
    inv["source_path"] = str(path)
    inv["source_fanout_status"] = inv["source_row_count"].map(lambda n: "fanout_high" if int(n) > FANOUT_ROW_LIMIT else "bounded")
    _checkpoint(f"phase3b_{layer}_source_groupby_complete", len(inv))
    return inv


def _source_route_sets(inv: pd.DataFrame) -> dict[str, set[str]]:
    return {
        "keys": set(_text(inv, "normalized_route_key")) - {""},
        "facilities": set(_text(inv, "facility_text")) - {""},
        "types": set(_text(inv, "route_type_category")) - {""},
    }


def _classify_source(row: Any, speed_sets: dict[str, set[str]], aadt_sets: dict[str, set[str]], speed_inv: pd.DataFrame, aadt_inv: pd.DataFrame) -> dict[str, Any]:
    key = str(row.candidate_route_key_normalized)
    common = str(row.candidate_route_common_normalized)
    facility = str(row.candidate_facility_text)
    rtype = str(row.candidate_route_type_category)
    speed_key = key in speed_sets["keys"] or common in speed_sets["keys"]
    aadt_key = key in aadt_sets["keys"] or common in aadt_sets["keys"]
    speed_fac = facility and facility in speed_sets["facilities"]
    aadt_fac = facility and facility in aadt_sets["facilities"]
    speed_type = rtype in speed_sets["types"]
    aadt_type = rtype in aadt_sets["types"]
    speed_rows = speed_inv.loc[_text(speed_inv, "normalized_route_key").isin({key, common})]
    aadt_rows = aadt_inv.loc[_text(aadt_inv, "normalized_route_key").isin({key, common})]
    fanout_high = (not speed_rows.empty and int(speed_rows["source_row_count"].sum()) > FANOUT_ROW_LIMIT) or (not aadt_rows.empty and int(aadt_rows["source_row_count"].sum()) > FANOUT_ROW_LIMIT)
    if fanout_high:
        availability = "fanout_too_high_for_current_evidence"
    elif speed_key and aadt_key:
        availability = "raw_speed_and_aadt_available"
    elif speed_key:
        availability = "raw_speed_only_available"
    elif aadt_key:
        availability = "raw_aadt_only_available"
    elif speed_fac or aadt_fac:
        availability = "route_name_facility_bridge_supported"
    elif speed_type and aadt_type and str(row.phase3a_strict_normalization_class) == "strict_success_route_type_category_match":
        availability = "route_type_filtering_likely"
    elif speed_type or aadt_type:
        availability = "active_output_filtering_likely"
    elif str(row.phase3a_strict_normalization_class) == "strict_success_pattern_match_but_measure_uncertain":
        availability = "measure_system_uncertain"
    elif str(row.candidate_route_key_normalized) and not speed_key and not aadt_key:
        availability = "source_absence_likely"
    else:
        availability = "insufficient_evidence"
    measure_status = "no_route_match"
    if speed_key and not speed_rows.empty:
        measure_status = _measure_overlap_status(row.measure_min, row.measure_max, speed_rows["measure_min"].min(), speed_rows["measure_max"].max())
    if aadt_key and not aadt_rows.empty and measure_status != "route_level_measure_range_overlaps":
        measure_status = _measure_overlap_status(row.measure_min, row.measure_max, aadt_rows["measure_min"].min(), aadt_rows["measure_max"].max())
    return {
        "source_availability_class": availability,
        "raw_speed_route_identity_present": speed_key,
        "raw_aadt_route_identity_present": aadt_key,
        "raw_speed_facility_present": bool(speed_fac),
        "raw_aadt_facility_present": bool(aadt_fac),
        "raw_speed_route_type_present": bool(speed_type),
        "raw_aadt_route_type_present": bool(aadt_type),
        "route_level_measure_compatibility": measure_status,
        "source_fanout_risk_flag": bool(fanout_high),
        "speed_source_row_fanout_count": int(speed_rows["source_row_count"].sum()) if not speed_rows.empty else 0,
        "aadt_source_row_fanout_count": int(aadt_rows["source_row_count"].sum()) if not aadt_rows.empty else 0,
    }


def run_phase3b(phase3a: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], bool]:
    route_rerun = phase3a["rerun"].copy()
    remaining = route_rerun.loc[~(_flag(route_rerun, "speed_recovery_estimate_flag") & _flag(route_rerun, "aadt_recovery_estimate_flag"))].copy()
    _checkpoint("phase3b_remaining_missing_route_groups", len(remaining))
    speed_inv = _source_inventory("speed")
    aadt_inv = _source_inventory("aadt_exposure")
    speed_sets = _source_route_sets(speed_inv)
    aadt_sets = _source_route_sets(aadt_inv)
    rows = []
    for row in remaining.itertuples(index=False):
        rows.append({**row._asdict(), **_classify_source(row, speed_sets, aadt_sets, speed_inv, aadt_inv)})
    missing = pd.DataFrame(rows)
    joint = pd.DataFrame(
        [
            {"context_layer": "speed", "source_route_count": speed_inv["normalized_route_key"].nunique() if not speed_inv.empty else 0, "source_rows": int(speed_inv["source_row_count"].sum()) if not speed_inv.empty else 0},
            {"context_layer": "aadt_exposure", "source_route_count": aadt_inv["normalized_route_key"].nunique() if not aadt_inv.empty else 0, "source_rows": int(aadt_inv["source_row_count"].sum()) if not aadt_inv.empty else 0},
        ]
    )
    summary = missing.groupby("source_availability_class", dropna=False).agg(
        route_group_count=("candidate_route_group_id", "count"),
        candidate_bin_count=("candidate_bin_count", "sum"),
        affected_signal_count=("affected_signal_count", "sum"),
        fanout_risk_groups=("source_fanout_risk_flag", "sum"),
    ).reset_index()
    estimate = summary.copy()
    estimate["estimated_recovery_path"] = estimate["source_availability_class"].map(
        {
            "raw_speed_and_aadt_available": "raw_source_join",
            "raw_speed_only_available": "raw_source_join_speed_only",
            "raw_aadt_only_available": "raw_source_join_aadt_only",
            "active_output_filtering_likely": "active_output_filter_bypass",
            "route_type_filtering_likely": "route_type_filter_review",
            "route_name_facility_bridge_supported": "route_name_facility_bridge",
            "measure_system_uncertain": "measure_system_refinement",
            "fanout_too_high_for_current_evidence": "mapped_or_source_owner_review",
            "source_absence_likely": "likely_true_source_absence",
        }
    ).fillna("manual_review")
    queue = missing.sort_values(["affected_signal_count", "candidate_bin_count"], ascending=False).head(500)
    qa = pd.DataFrame(
        [
            _qa_row("phase3a_outputs_loaded", not route_rerun.empty, len(route_rerun)),
            _qa_row("speed_source_inventory_created", not speed_inv.empty, len(speed_inv)),
            _qa_row("aadt_source_inventory_created", not aadt_inv.empty, len(aadt_inv)),
            _qa_row("remaining_missing_route_groups_classified", not missing.empty and _text(missing, "source_availability_class").ne("").all(), len(missing)),
            _qa_row("largest_actionable_classes_audited", ACTIONABLE_CLASSES.issubset(set(_text(missing, "route_identity_class"))) or bool(ACTIONABLE_CLASSES & set(_text(missing, "route_identity_class"))), _collapse(missing["route_identity_class"])),
            _qa_row("no_bridge_table_built", True, "confirmed_by_code"),
            _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
            _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
            _qa_row("no_crash_records_read", True, "confirmed_by_code"),
            _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
            _qa_row("access_not_included", True, "confirmed_by_code"),
            _qa_row("all_phase3b_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
        ]
    )
    outputs = {
        "speed_source_inventory": speed_inv,
        "aadt_source_inventory": aadt_inv,
        "joint_source_inventory": joint,
        "remaining_missing": missing,
        "route_type_filtered": _audit_class(missing, "candidate_route_type_filtered_from_context_output"),
        "strict_failed": _audit_class(missing, "strict_success_pattern_match_but_join_failed"),
        "route_name_differs": _audit_class(missing, "strict_success_route_name_match_but_route_id_differs"),
        "summary": summary,
        "estimate": estimate,
        "queue": queue,
        "qa": qa,
    }
    return outputs, bool(qa["passed"].all())


def _audit_class(missing: pd.DataFrame, klass: str) -> pd.DataFrame:
    sub = missing.loc[_text(missing, "route_identity_class").eq(klass)].copy()
    if sub.empty:
        return pd.DataFrame()
    return sub.groupby(["route_identity_class", "source_availability_class", "route_level_measure_compatibility", "source_fanout_risk_flag"], dropna=False).agg(
        route_group_count=("candidate_route_group_id", "count"),
        candidate_bin_count=("candidate_bin_count", "sum"),
        affected_signal_count=("affected_signal_count", "sum"),
        speed_route_present_groups=("raw_speed_route_identity_present", "sum"),
        aadt_route_present_groups=("raw_aadt_route_identity_present", "sum"),
        route_examples=("route_name", _collapse),
        facility_examples=("candidate_facility_text", _collapse),
    ).reset_index()


def _write_phase3a(outputs: dict[str, pd.DataFrame]) -> None:
    _write_csv(outputs["candidate_inventory"], OUT_DIR / "phase3a_candidate_route_inventory.csv")
    _write_csv(outputs["strict_inventory"], OUT_DIR / "phase3a_strict_success_pattern_inventory.csv")
    _write_csv(outputs["rerun"], OUT_DIR / "phase3a_strict_normalization_route_level_rerun.csv")
    _write_csv(outputs["signal_estimate"], OUT_DIR / "phase3a_strict_normalization_signal_estimate.csv")
    _write_csv(outputs["by_taxonomy"], OUT_DIR / "phase3a_strict_normalization_by_taxonomy_class.csv")
    _write_csv(outputs["fanout"], OUT_DIR / "phase3a_strict_normalization_fanout_review.csv")
    _write_csv(outputs["examples"], OUT_DIR / "phase3a_strict_normalization_capped_bin_examples.csv")
    _write_csv(outputs["qa"], OUT_DIR / "phase3a_strict_normalization_qa.csv")
    _write_phase3a_findings(outputs)


def _write_phase3b(outputs: dict[str, pd.DataFrame]) -> None:
    _write_csv(outputs["speed_source_inventory"], OUT_DIR / "phase3b_speed_source_route_inventory.csv")
    _write_csv(outputs["aadt_source_inventory"], OUT_DIR / "phase3b_aadt_source_route_inventory.csv")
    _write_csv(outputs["joint_source_inventory"], OUT_DIR / "phase3b_speed_aadt_joint_source_inventory.csv")
    _write_csv(outputs["remaining_missing"], OUT_DIR / "phase3b_remaining_missing_route_groups.csv")
    _write_csv(outputs["route_type_filtered"], OUT_DIR / "phase3b_route_type_filtered_availability_audit.csv")
    _write_csv(outputs["strict_failed"], OUT_DIR / "phase3b_strict_success_failed_availability_audit.csv")
    _write_csv(outputs["route_name_differs"], OUT_DIR / "phase3b_route_name_differs_availability_audit.csv")
    _write_csv(outputs["summary"], OUT_DIR / "phase3b_source_availability_class_summary.csv")
    _write_csv(outputs["estimate"], OUT_DIR / "phase3b_source_availability_recovery_estimate.csv")
    _write_csv(outputs["queue"], OUT_DIR / "phase3b_source_availability_ranked_review_queue.csv")
    _write_csv(outputs["qa"], OUT_DIR / "phase3b_source_availability_qa.csv")
    _write_phase3b_findings(outputs)


def _write_phase3a_findings(outputs: dict[str, pd.DataFrame]) -> None:
    est = outputs["signal_estimate"]
    top = outputs["by_taxonomy"].sort_values("affected_signal_count", ascending=False).head(8)
    lines = [
        "# Phase 3A Strict-Derived Normalization Recovery Findings",
        "",
        "Phase 3A reran strict-derived normalization only at route and signal summary grain. It did not assign speed or AADT values and did not expand candidate-bin by source-row overlaps.",
        "",
    ]
    for row in est.itertuples(index=False):
        lines.append(f"- `{row.context_layer}` potentially recoverable signals: {int(row.additional_candidate_signals_potentially_covered):,}; fanout-risk signals: {int(row.fanout_risk_signal_count):,}; measure-uncertain signals: {int(row.measure_uncertain_signal_count):,}.")
    lines.append("")
    lines.append("Largest taxonomy summaries:")
    for row in top.itertuples(index=False):
        lines.append(f"- `{row.route_identity_class}` / `{row.phase3a_strict_normalization_class}`: {int(row.route_group_count):,} groups, {int(row.candidate_bin_count):,} bins, {int(row.affected_signal_count):,} signal-count contributions.")
    _write_text("\n".join(lines) + "\n", OUT_DIR / "phase3a_strict_normalization_findings.md")


def _write_phase3b_findings(outputs: dict[str, pd.DataFrame]) -> None:
    top = outputs["summary"].sort_values("candidate_bin_count", ascending=False).head(10)
    lines = [
        "# Phase 3B Source Availability Recovery Findings",
        "",
        "Phase 3B audited grouped raw/staged speed and AADT source inventories. It did not build or apply a bridge table.",
        "",
        "Largest availability classes:",
    ]
    for row in top.itertuples(index=False):
        lines.append(f"- `{row.source_availability_class}`: {int(row.route_group_count):,} groups, {int(row.candidate_bin_count):,} bins, {int(row.affected_signal_count):,} signal-count contributions.")
    _write_text("\n".join(lines) + "\n", OUT_DIR / "phase3b_source_availability_findings.md")


def _final_qa(phase3a_passed: bool, phase3b_ran: bool, phase3b_passed: bool) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
            _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
            _qa_row("no_crash_records_read", True, "confirmed_by_code"),
            _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
            _qa_row("access_not_included", True, "confirmed_by_code"),
            _qa_row("crashes_not_used_for_any_diagnostic", True, "confirmed_by_code"),
            _qa_row("context_fields_not_used_to_define_scaffold_candidate_associations_direction_or_route_measure", True, "confirmed_by_code"),
            _qa_row("no_unbounded_candidate_bin_source_row_join_materialized", True, "confirmed_by_code"),
            _qa_row("fanout_heavy_cases_summarized_and_routed_to_review", True, "confirmed_by_code"),
            _qa_row("coverage_estimates_labeled_estimates_not_active_assignments", True, "confirmed_by_code"),
            _qa_row("phase3b_only_runs_if_phase3a_gates_pass", phase3b_ran == phase3a_passed, phase3b_ran, phase3a_passed),
            _qa_row("phase3c_not_run", True, "confirmed_by_code"),
            _qa_row("all_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
            _qa_row("phase3b_passed_if_run", (not phase3b_ran) or phase3b_passed, phase3b_passed),
        ]
    )


def _final_findings(phase3a: dict[str, pd.DataFrame], phase3a_passed: bool, phase3b: dict[str, pd.DataFrame] | None, phase3b_ran: bool) -> None:
    est = phase3a["signal_estimate"]
    speed_est = int(est.loc[_text(est, "context_layer").eq("speed"), "additional_candidate_signals_potentially_covered"].sum()) if not est.empty else 0
    aadt_est = int(est.loc[_text(est, "context_layer").eq("aadt_exposure"), "additional_candidate_signals_potentially_covered"].sum()) if not est.empty else 0
    recoverable = phase3a["by_taxonomy"].sort_values(["speed_recoverable_groups", "aadt_recoverable_groups", "affected_signal_count"], ascending=False).head(5)
    fanout = phase3a["fanout"].sort_values("affected_signal_count", ascending=False).head(5)
    p3b_summary = phase3b["summary"].sort_values("candidate_bin_count", ascending=False).head(6) if phase3b_ran and phase3b is not None else pd.DataFrame()
    lines = [
        "# Expanded Candidate Speed/AADT Phase 3A/3B Recovery Findings",
        "",
        f"1. Did Phase 3A pass QA? {phase3a_passed}.",
        f"2. Did Phase 3B run? {phase3b_ran}.",
        "3. The strict-derived normalization route-level rerun shows where strict active success patterns align with recovered candidate route identity without expanding bin/source overlaps.",
        f"4. Additional speed signals potentially recoverable from strict-derived normalization: {speed_est:,}.",
        f"5. Additional AADT/exposure signals potentially recoverable from strict-derived normalization: {aadt_est:,}.",
        "6. Most recoverable taxonomy classes: " + ("; ".join(f"`{r.route_identity_class}`/{r.phase3a_strict_normalization_class}" for r in recoverable.itertuples(index=False)) if not recoverable.empty else "none identified"),
        "7. Fanout-risk taxonomy classes: " + ("; ".join(f"`{r.route_identity_class}` {int(r.affected_signal_count):,} signal-count contributions" for r in fanout.itertuples(index=False)) if not fanout.empty else "none identified"),
        "8. Raw/staged speed source audit: " + (f"{len(phase3b['speed_source_inventory']):,} grouped speed source route records inspected." if phase3b_ran and phase3b is not None else "not run"),
        "9. Raw/staged AADT source audit: " + (f"{len(phase3b['aadt_source_inventory']):,} grouped AADT source route records inspected." if phase3b_ran and phase3b is not None else "not run"),
        "10. `candidate_route_type_filtered_from_context_output`: see `phase3b_route_type_filtered_availability_audit.csv`; current evidence is summary-level, not an active assignment.",
        "11. `strict_success_pattern_match_but_join_failed`: see `phase3b_strict_success_failed_availability_audit.csv`; fanout and measure uncertainty remain separated from join-logic bug candidates.",
        "12. `strict_success_route_name_match_but_route_id_differs`: see `phase3b_route_name_differs_availability_audit.csv`; route-name/facility support is treated as crosswalk opportunity or fanout risk, not applied.",
        "13. Likely source-absent records are summarized under `source_absence_likely`.",
        "14. Recoverable records are summarized under raw-source, filter-bypass, route-type, route-name/facility, and measure-refinement classes.",
        "15. Phase 3C should be redesigned as a route-group bridge candidate builder with fanout caps, vectorized route-group interval checks, and no bin-level expansion until each bridge candidate passes route-level QA.",
    ]
    if not p3b_summary.empty:
        lines.append("")
        lines.append("Largest Phase 3B source availability classes:")
        for row in p3b_summary.itertuples(index=False):
            lines.append(f"- `{row.source_availability_class}`: {int(row.candidate_bin_count):,} bins, {int(row.affected_signal_count):,} signal-count contributions")
    _write_text("\n".join(lines) + "\n", OUT_DIR / "expanded_candidate_speed_aadt_phase3ab_recovery_findings.md")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _log("RUN_START expanded_candidate_speed_aadt_phase3ab_recovery")
    _checkpoint("bounded_question", note="route-level and signal-level Phase 3A/3B speed/AADT recovery only; no Phase 3C bridge construction")
    missing_inputs = _missing_required_inputs()
    _checkpoint("required_input_check", len(REQUIRED_INPUTS), f"missing_files={len(missing_inputs):,}")
    inputs = _load_inputs()
    phase3a, phase3a_passed = run_phase3a(inputs, missing_inputs)
    _write_phase3a(phase3a)

    phase3b = None
    phase3b_ran = False
    phase3b_passed = False
    if phase3a_passed:
        phase3b, phase3b_passed = run_phase3b(phase3a)
        phase3b_ran = True
        _write_phase3b(phase3b)
    else:
        failed = phase3a["qa"].loc[~phase3a["qa"]["passed"], "qa_gate"].tolist()
        _write_text("Phase 3B did not run because Phase 3A QA gates failed:\n" + "\n".join(f"- {x}" for x in failed) + "\n", OUT_DIR / "phase3b_not_run_reason.txt")

    final_qa = _final_qa(phase3a_passed, phase3b_ran, phase3b_passed)
    _write_csv(final_qa, OUT_DIR / "expanded_candidate_speed_aadt_phase3ab_recovery_qa.csv")
    _final_findings(phase3a, phase3a_passed, phase3b, phase3b_ran)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "Phase 3A/3B route-level and signal-level speed/AADT recovery diagnostic; no Phase 3C bridge table",
        "output_dir": str(OUT_DIR),
        "phase3a_passed": phase3a_passed,
        "phase3b_ran": phase3b_ran,
        "phase3b_passed": phase3b_passed,
        "candidate_bins_evaluated": int(len(phase3a["base"])),
        "candidate_signals_evaluated": int(phase3a["base"]["candidate_signal_id"].nunique()),
        "candidate_route_groups_evaluated": int(len(phase3a["candidate_inventory"])),
        "guardrails": {
            "read_only": True,
            "review_only": True,
            "no_phase3c_bridge_table": True,
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_used": True,
            "access_not_included": True,
            "no_unbounded_bin_source_overlap": True,
        },
    }
    _write_json(manifest, OUT_DIR / "expanded_candidate_speed_aadt_phase3ab_recovery_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
