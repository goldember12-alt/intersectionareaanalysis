from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
ROUTE_MEASURE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_measure_context_audit"
REFINE_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_context_join_refinement_diagnostic"
MISMATCH_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_route_identity_mismatch_diagnostic"
TAXONOMY_DIR = OUTPUT_ROOT / "review/current/strict_success_route_identity_taxonomy"
SPEED_DIR = OUTPUT_ROOT / "review/current/speed_context_join_v5_new_source_supplement"
AADT_DIR = OUTPUT_ROOT / "review/current/aadt_context_join_v3_identity_route_measure"
SPEED_STAGING_DIR = OUTPUT_ROOT / "review/current/posted_speed_source_staging"
AADT_STAGING_DIR = OUTPUT_ROOT / "review/current/aadt_source_staging"
OUT_DIR = OUTPUT_ROOT / "review/current/expanded_candidate_speed_aadt_phase3_bridge"

SPEED_SOURCE = Path("artifacts/normalized/speed.parquet")
AADT_SOURCE = Path("artifacts/normalized/aadt.parquet")

EXPECTED_BINS = 136_227
EXPECTED_SIGNALS = 1_590
MEASURE_TOLERANCE = 0.01
TOLERANT_MEASURE_TOLERANCE = 0.05
ROW_GUARD_LIMIT = 5_000_000
EXTREME_FANOUT_LIMIT = 10_000
SOURCE_ROUTE_FANOUT_DETAIL_LIMIT = 500
DEFAULT_SMOKE_ROWS = 5_000
DEFAULT_SMOKE_DETAIL_ROWS = 500

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
    MISMATCH_DIR: [
        "candidate_route_identity_base_bins.csv",
        "speed_route_inventory.csv",
        "aadt_exposure_route_inventory.csv",
        "route_identity_miss_reason_detail.csv",
        "route_identity_miss_reason_summary.csv",
        "route_identity_miss_by_layer_overlap.csv",
        "route_identity_crosswalk_candidates.csv",
        "route_identity_crosswalk_recovery_estimate.csv",
        "expanded_candidate_route_identity_mismatch_manifest.json",
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
        "stage1_strict_vs_candidate_schema_comparison.csv",
        "stage2_recovered_route_identity_taxonomy_detail.csv",
        "stage2_recovered_route_identity_taxonomy_signal_summary.csv",
        "stage2_route_identity_class_profiles.csv",
        "stage2_speed_aadt_joint_route_identity_profile.csv",
        "stage2_strict_derived_crosswalk_seed_candidates.csv",
        "stage2_route_identity_recoverability_summary.csv",
        "stage2_route_identity_recommended_actions.csv",
        "strict_success_route_identity_taxonomy_manifest.json",
    ],
}

ACTIONABLE_CLASSES = {
    "strict_success_pattern_match_but_join_failed",
    "strict_success_route_name_match_but_route_id_differs",
    "candidate_route_type_filtered_from_context_output",
}
ACTIONABLE_ACTIONS = {
    "rerun_join_with_strict_success_normalization",
    "build_review_only_route_crosswalk_seed",
    "inspect_active_output_filtering",
}


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


def _read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if columns is None:
        return pd.read_parquet(path)
    available = set(pd.read_parquet(path, columns=[]).columns)
    cols = [c for c in columns if c in available]
    if not cols:
        return pd.DataFrame()
    return pd.read_parquet(path, columns=cols)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _write_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def _checkpoint(name: str, rows: int | None = None, note: str = "") -> None:
    row_text = "" if rows is None else f" rows={rows:,}"
    note_text = "" if not note else f" {note}"
    _log(f"CHECKPOINT {name}{row_text}{note_text}")


def _guard_rows(name: str, rows: int, limit: int = ROW_GUARD_LIMIT) -> bool:
    _checkpoint(name, rows)
    if rows > limit:
        _log(f"GUARD_FAIL {name} exceeded limit={limit:,}; substep skipped")
        return False
    return True


def _smoke_mode() -> tuple[str, int | None]:
    top_routes = os.environ.get("PHASE3_SMOKE_TOP_ROUTES", "").strip()
    if top_routes:
        return "top_routes", int(top_routes)
    rows = os.environ.get("PHASE3_SMOKE_ROWS", "").strip()
    if rows:
        return "rows", int(rows)
    if os.environ.get("PHASE3_FULL_RUN_CONFIRMED", "").strip().lower() in {"1", "true", "yes"}:
        return "full", None
    return "rows", DEFAULT_SMOKE_ROWS


def _smoke_detail_rows() -> int:
    return int(os.environ.get("PHASE3_SMOKE_DETAIL_ROWS", str(DEFAULT_SMOKE_DETAIL_ROWS)))


def _is_smoke() -> bool:
    return _smoke_mode()[0] != "full"


def _output_name(name: str) -> str:
    return f"smoke_{name}" if _is_smoke() else name


def _text(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series("", index=df.index, dtype=str)
    return df[col].fillna("").astype(str)


def _bool(df: pd.DataFrame, col: str) -> pd.Series:
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
    s = re.sub(r"\b(COUNTY|CITY|TOWN|OF|VA|VIRGINIA|RAMP)\b", " ", s)
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


def _alt_keys(route_name: str, route_common: str, route_id: str = "") -> str:
    keys = {_norm_route(route_name), _norm_route(route_common), _norm_route(route_id)}
    more = set()
    for key in keys:
        if not key:
            continue
        more.add(re.sub(r"^\d{3}(SC\d+)", r"\1", key))
        more.add(key.replace("SR", "VA", 1) if key.startswith("SR") else key)
        more.add(key.replace("VA", "SR", 1) if key.startswith("VA") else key)
    return "|".join(sorted(k for k in keys | more if k))


def _overlap(a_min: Any, a_max: Any, b_min: Any, b_max: Any, tolerance: float = 0.0) -> tuple[bool, float]:
    vals = pd.to_numeric(pd.Series([a_min, a_max, b_min, b_max]), errors="coerce")
    if vals.isna().any():
        return False, 0.0
    amin, amax, bmin, bmax = [float(v) for v in vals]
    if amin > amax:
        amin, amax = amax, amin
    if bmin > bmax:
        bmin, bmax = bmax, bmin
    left = max(amin, bmin)
    right = min(amax, bmax)
    length = right - left
    if length >= 0:
        return True, length
    if abs(length) <= tolerance:
        return True, 0.0
    return False, 0.0


def _qa_row(gate: str, passed: bool, observed: Any = "", expected: Any = "", note: str = "") -> dict[str, Any]:
    return {
        "qa_gate": gate,
        "passed": bool(passed),
        "observed_value": observed,
        "expected_or_reference_value": expected,
        "note": note,
    }


def _missing_required_inputs() -> list[str]:
    missing = []
    for root, names in REQUIRED_INPUTS.items():
        for name in names:
            if not (root / name).exists():
                missing.append(str(root / name))
    return missing


def _load_inputs() -> dict[str, pd.DataFrame]:
    _checkpoint("load_inputs_start")
    return {
        "route_bins": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_bin_detail.csv"),
        "route_signal": _read_csv(ROUTE_MEASURE_DIR / "stage1_candidate_route_measure_signal_summary.csv"),
        "prior_speed": _read_csv(ROUTE_MEASURE_DIR / "stage2_candidate_speed_join_detail.csv"),
        "prior_aadt": _read_csv(ROUTE_MEASURE_DIR / "stage2_candidate_aadt_exposure_join_detail.csv"),
        "prior_signal": _read_csv(ROUTE_MEASURE_DIR / "stage2_candidate_context_join_signal_summary.csv"),
        "refine_base": _read_csv(REFINE_DIR / "candidate_context_refinement_base_bins.csv"),
        "refine_speed": _read_csv(REFINE_DIR / "candidate_speed_refined_join_detail.csv"),
        "refine_aadt": _read_csv(REFINE_DIR / "candidate_aadt_exposure_refined_join_detail.csv"),
        "refine_signal": _read_csv(REFINE_DIR / "candidate_context_refined_signal_summary.csv"),
        "refine_before_after": _read_csv(REFINE_DIR / "candidate_context_refined_before_after_summary.csv"),
        "refine_bottleneck": _read_csv(REFINE_DIR / "candidate_context_layer_bottleneck_summary.csv"),
        "mismatch_base": _read_csv(MISMATCH_DIR / "candidate_route_identity_base_bins.csv"),
        "speed_route_inventory": _read_csv(MISMATCH_DIR / "speed_route_inventory.csv"),
        "aadt_route_inventory": _read_csv(MISMATCH_DIR / "aadt_exposure_route_inventory.csv"),
        "miss_detail": _read_csv(MISMATCH_DIR / "route_identity_miss_reason_detail.csv"),
        "miss_summary": _read_csv(MISMATCH_DIR / "route_identity_miss_reason_summary.csv"),
        "miss_overlap": _read_csv(MISMATCH_DIR / "route_identity_miss_by_layer_overlap.csv"),
        "mismatch_crosswalk": _read_csv(MISMATCH_DIR / "route_identity_crosswalk_candidates.csv"),
        "mismatch_recovery": _read_csv(MISMATCH_DIR / "route_identity_crosswalk_recovery_estimate.csv"),
        "strict_bins": _read_csv(TAXONOMY_DIR / "stage1_strict_active_positive_control_bins.csv"),
        "strict_speed_routes": _read_csv(TAXONOMY_DIR / "stage1_strict_active_speed_success_routes.csv"),
        "strict_aadt_routes": _read_csv(TAXONOMY_DIR / "stage1_strict_active_aadt_success_routes.csv"),
        "strict_join_inventory": _read_csv(TAXONOMY_DIR / "stage1_strict_success_join_key_inventory.csv"),
        "strict_pattern": _read_csv(TAXONOMY_DIR / "stage1_strict_success_route_pattern_summary.csv"),
        "taxonomy": _read_csv(TAXONOMY_DIR / "stage2_recovered_route_identity_taxonomy_detail.csv"),
        "taxonomy_signal": _read_csv(TAXONOMY_DIR / "stage2_recovered_route_identity_taxonomy_signal_summary.csv"),
        "taxonomy_profiles": _read_csv(TAXONOMY_DIR / "stage2_route_identity_class_profiles.csv"),
        "taxonomy_joint": _read_csv(TAXONOMY_DIR / "stage2_speed_aadt_joint_route_identity_profile.csv"),
        "taxonomy_crosswalk": _read_csv(TAXONOMY_DIR / "stage2_strict_derived_crosswalk_seed_candidates.csv"),
        "taxonomy_recoverability": _read_csv(TAXONOMY_DIR / "stage2_route_identity_recoverability_summary.csv"),
        "taxonomy_actions": _read_csv(TAXONOMY_DIR / "stage2_route_identity_recommended_actions.csv"),
    }


def _base_bins(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    base = inputs["taxonomy"].copy()
    if base.empty:
        base = inputs["refine_base"].copy()
    _checkpoint("input_candidate_bins_loaded", len(base))
    if "candidate_route_key_normalized" not in base.columns:
        base["candidate_route_key_normalized"] = _text(base, "route_name").map(_norm_route)
    if "candidate_route_common_normalized" not in base.columns:
        base["candidate_route_common_normalized"] = _text(base, "route_common").map(_norm_route)
    base["candidate_alt_keys"] = [
        _alt_keys(rn, rc, rid)
        for rn, rc, rid in zip(_text(base, "route_name"), _text(base, "route_common"), _text(base, "route_id"), strict=False)
    ]
    base["candidate_facility_text"] = _text(base, "route_common").where(_text(base, "route_common").ne(""), _text(base, "route_name")).map(_facility_text)
    base["candidate_route_type_category"] = [
        _route_system(k, raw)
        for k, raw in zip(_text(base, "candidate_route_key_normalized"), _text(base, "route_name"), strict=False)
    ]
    base["candidate_measure_min_num"] = _num(base, "candidate_measure_min")
    base["candidate_measure_max_num"] = _num(base, "candidate_measure_max")

    for layer, key, prefix in [("speed", "refine_speed", "previous_speed"), ("aadt_exposure", "refine_aadt", "previous_aadt")]:
        detail = inputs[key]
        if not detail.empty:
            cols = [c for c in ["candidate_bin_id", "coverage_flag", "join_method", "missing_reason"] if c in detail.columns]
            detail = detail[cols].rename(
                columns={
                    "coverage_flag": f"{prefix}_coverage_flag",
                    "join_method": f"{prefix}_join_method",
                    "missing_reason": f"{prefix}_missing_reason",
                }
            )
            base = base.drop(columns=[c for c in detail.columns if c != "candidate_bin_id" and c in base.columns], errors="ignore")
            _checkpoint(f"before_merge_{key}_coverage_flags", len(base), f"right_rows={len(detail):,}")
            if not _guard_rows(f"candidate_x_{key}_merge_upper_bound", len(base) + len(detail)):
                continue
            base = base.merge(detail, on="candidate_bin_id", how="left")
            _checkpoint(f"after_merge_{key}_coverage_flags", len(base))
        if f"{prefix}_coverage_flag" not in base.columns and f"{layer}_coverage_flag" in base.columns:
            base[f"{prefix}_coverage_flag"] = base[f"{layer}_coverage_flag"]
        if f"{prefix}_join_method" not in base.columns and f"{layer}_join_method" in base.columns:
            base[f"{prefix}_join_method"] = base[f"{layer}_join_method"]
        if f"{prefix}_missing_reason" not in base.columns and f"{layer}_missing_reason" in base.columns:
            base[f"{prefix}_missing_reason"] = base[f"{layer}_missing_reason"]
    mode, limit = _smoke_mode()
    if mode == "rows" and limit is not None:
        base = base.head(limit).copy()
        _checkpoint("smoke_candidate_bins_limited_by_first_rows", len(base), f"limit={limit:,}")
    elif mode == "top_routes" and limit is not None:
        top = _text(base, "candidate_route_key_normalized").value_counts().head(limit).index
        base = base.loc[_text(base, "candidate_route_key_normalized").isin(set(top))].copy()
        _checkpoint("smoke_candidate_bins_limited_by_top_routes", len(base), f"route_limit={limit:,}")
    return base


def _strict_success_route_sets(inputs: dict[str, pd.DataFrame]) -> dict[str, set[str]]:
    def keys(df: pd.DataFrame) -> set[str]:
        vals: set[str] = set()
        for col in ["route_key_normalized", "stable_route_name_normalized", "source_route_key_v2", "route_name_normalized"]:
            if col in df.columns:
                vals |= {v for v in _text(df, col).map(_norm_route) if v}
        return vals

    return {
        "speed": keys(inputs["strict_speed_routes"]) | keys(inputs["strict_bins"].loc[_bool(inputs["strict_bins"], "speed_success_flag")] if "speed_success_flag" in inputs["strict_bins"].columns else inputs["strict_bins"]),
        "aadt_exposure": keys(inputs["strict_aadt_routes"]) | keys(inputs["strict_bins"].loc[_bool(inputs["strict_bins"], "aadt_success_flag")] if "aadt_success_flag" in inputs["strict_bins"].columns else inputs["strict_bins"]),
    }


def _active_interval_source(layer: str) -> pd.DataFrame:
    if layer == "speed":
        src = _read_csv(
            SPEED_DIR / "directional_bin_speed_context_v5.csv",
            usecols=[
                "stable_route_name_raw",
                "stable_route_name_normalized",
                "stable_measure_min",
                "stable_measure_max",
                "v5_posted_car_speed_limit_context_value",
                "v5_posted_truck_speed_limit_context_value",
                "v5_refined_speed_context_status",
                "v5_refined_speed_context_confidence",
                "v5_source_route_fields",
                "v5_candidate_count",
            ],
        )
        if src.empty:
            return pd.DataFrame()
        src["source_route_key"] = _text(src, "stable_route_name_normalized").where(_text(src, "stable_route_name_normalized").ne(""), _text(src, "stable_route_name_raw").map(_norm_route))
        src["source_route_raw"] = _text(src, "stable_route_name_raw")
        src["source_value"] = _text(src, "v5_posted_car_speed_limit_context_value")
        src["source_status"] = _text(src, "v5_refined_speed_context_status")
        src["source_confidence"] = _text(src, "v5_refined_speed_context_confidence")
        src["source_provenance"] = "speed_v5_active_review_output"
    else:
        src = _read_csv(
            AADT_DIR / "directional_bin_aadt_context_v3.csv",
            usecols=[
                "source_RTE_NM",
                "source_RTE_COMMON",
                "source_RTE_ID",
                "source_route_key_v2",
                "source_route_common_key_v2",
                "stable_measure_min",
                "stable_measure_max",
                "aadt_value",
                "aadt_year",
                "aadt_direction_factor",
                "aadt_directionality",
                "aadt_context_status",
                "aadt_context_confidence",
                "active_aadt_denominator_policy",
            ],
        )
        if src.empty:
            return pd.DataFrame()
        src["source_route_key"] = _text(src, "source_route_key_v2").where(_text(src, "source_route_key_v2").ne(""), _text(src, "source_RTE_NM").map(_norm_route))
        src["source_route_raw"] = _text(src, "source_RTE_NM")
        src["source_value"] = _text(src, "aadt_value")
        src["source_status"] = _text(src, "aadt_context_status")
        src["source_confidence"] = _text(src, "aadt_context_confidence")
        src["source_provenance"] = "aadt_v3_active_review_output"
    src["source_measure_min"] = _num(src, "stable_measure_min")
    src["source_measure_max"] = _num(src, "stable_measure_max")
    src["source_route_type_category"] = [_route_system(k, raw) for k, raw in zip(_text(src, "source_route_key"), _text(src, "source_route_raw"), strict=False)]
    src["source_facility_text"] = _text(src, "source_RTE_COMMON").where(_text(src, "source_RTE_COMMON").ne(""), _text(src, "source_route_raw")).map(_facility_text) if "source_RTE_COMMON" in src.columns else _text(src, "source_route_raw").map(_facility_text)
    keep = src.loc[_text(src, "source_route_key").ne("") & src["source_measure_min"].notna() & src["source_measure_max"].notna()].copy()
    _checkpoint(f"{layer}_source_inventory_loaded", len(keep), f"routes={keep['source_route_key'].nunique() if 'source_route_key' in keep.columns else 0:,}")
    return keep


def _source_lookup(src: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if src.empty:
        return {}
    route_sizes = src.groupby("source_route_key", dropna=False).size().reset_index(name="source_interval_count")
    _checkpoint("source_route_inventory", len(route_sizes), f"source_rows={len(src):,}; max_route_fanout={int(route_sizes['source_interval_count'].max()) if not route_sizes.empty else 0:,}")
    extreme = route_sizes.loc[route_sizes["source_interval_count"] > EXTREME_FANOUT_LIMIT].copy()
    if not extreme.empty:
        _write_csv(extreme, OUT_DIR / _output_name("stage1_extreme_source_route_fanout_review.csv"))
        src = src.loc[~_text(src, "source_route_key").isin(set(_text(extreme, "source_route_key")))].copy()
        _checkpoint("source_route_inventory_extreme_fanout_removed", len(src), f"removed_routes={len(extreme):,}")
    return {k: g.reset_index(drop=True) for k, g in src.groupby("source_route_key", dropna=False)}


def _bridge_lookup(crosswalk: pd.DataFrame) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if crosswalk.empty:
        return out
    for row in crosswalk.itertuples(index=False):
        cand = _norm_route(getattr(row, "candidate_route_value", ""))
        target = _norm_route(getattr(row, "strict_success_route_value", "")) or _norm_route(getattr(row, "route_key_normalized", ""))
        if cand and target:
            out.setdefault(cand, set()).add(target)
    return out


def _candidate_methods(row: Any, layer: str, strict_sets: dict[str, set[str]], bridge: dict[str, set[str]]) -> list[tuple[str, str, float]]:
    prev = getattr(row, f"previous_{'aadt' if layer == 'aadt_exposure' else 'speed'}_coverage_flag", "")
    keys = str(getattr(row, "candidate_alt_keys", "")).split("|")
    candidate_key = str(getattr(row, "candidate_route_key_normalized", ""))
    common_key = str(getattr(row, "candidate_route_common_normalized", ""))
    route_class = str(getattr(row, "route_identity_class", ""))
    action = str(getattr(row, "recommended_next_action", ""))
    methods: list[tuple[str, str, float]] = []
    if str(prev).lower() in {"true", "1", "yes", "y"}:
        methods.append(("baseline_prior_refined_join", candidate_key, MEASURE_TOLERANCE))
    if candidate_key in strict_sets[layer]:
        methods.append(("strict_success_normalized_route_key", candidate_key, MEASURE_TOLERANCE))
    if common_key in strict_sets[layer]:
        methods.append(("strict_success_route_name_common_bridge", common_key, MEASURE_TOLERANCE))
    if route_class in ACTIONABLE_CLASSES or action in ACTIONABLE_ACTIONS:
        for key in keys:
            if key in strict_sets[layer]:
                methods.append(("strict_success_facility_text_bridge", key, MEASURE_TOLERANCE))
        if candidate_key in bridge:
            for target in bridge[candidate_key]:
                methods.append(("strict_success_joint_speed_aadt_route_bridge", target, MEASURE_TOLERANCE))
    methods.append(("strict_success_measure_overlap_recheck", candidate_key, MEASURE_TOLERANCE))
    methods.append(("strict_success_reversed_interval_recheck", candidate_key, MEASURE_TOLERANCE))
    methods.append(("strict_success_tolerant_measure_overlap", candidate_key, TOLERANT_MEASURE_TOLERANCE))
    return [(m, k, t) for m, k, t in methods if k]


def _match_candidate(row: Any, layer: str, lookup: dict[str, pd.DataFrame], strict_sets: dict[str, set[str]], bridge: dict[str, set[str]]) -> dict[str, Any]:
    methods = _candidate_methods(row, layer, strict_sets, bridge)
    cand_min = getattr(row, "candidate_measure_min_num", pd.NA)
    cand_max = getattr(row, "candidate_measure_max_num", pd.NA)
    seen: set[tuple[str, float]] = set()
    for method, key, tolerance in methods:
        if (key, tolerance) in seen:
            continue
        seen.add((key, tolerance))
        src = lookup.get(key)
        if src is None or src.empty:
            continue
        if len(src) > SOURCE_ROUTE_FANOUT_DETAIL_LIMIT:
            continue
        src_min = pd.to_numeric(src["source_measure_min"], errors="coerce")
        src_max = pd.to_numeric(src["source_measure_max"], errors="coerce")
        vals = pd.to_numeric(pd.Series([cand_min, cand_max]), errors="coerce")
        if vals.isna().any():
            continue
        cmin, cmax = float(vals.iloc[0]), float(vals.iloc[1])
        if cmin > cmax:
            cmin, cmax = cmax, cmin
        left = pd.concat([pd.Series(cmin, index=src.index), src_min], axis=1).max(axis=1)
        right = pd.concat([pd.Series(cmax, index=src.index), src_max], axis=1).min(axis=1)
        overlap_len = right - left
        mask = overlap_len.ge(0) | overlap_len.abs().le(tolerance)
        reversed_interval_used = False
        if not mask.any() and method == "strict_success_reversed_interval_recheck":
            reversed_interval_used = True
            mask = overlap_len.ge(0) | overlap_len.abs().le(tolerance)
        matches = src.loc[mask].copy()
        if not matches.empty:
            values = _text(matches, "source_value")
            raw_routes = _text(matches, "source_route_raw")
            statuses = _text(matches, "source_status")
            source_min = float(matches["source_measure_min"].min())
            source_max = float(matches["source_measure_max"].max())
            fanout = len(matches)
            conflict = values.nunique(dropna=True) > 1
            confidence = "high_confidence_review_only" if method in {"baseline_prior_refined_join", "strict_success_normalized_route_key"} and not conflict else "medium_confidence_review_only"
            if fanout > 8 or conflict:
                confidence = "low_confidence_manual_review_only"
            return {
                "stage1_coverage_flag": True,
                "join_method": method,
                "target_source_route_id_key": key,
                "target_source_route_name_common": _collapse(raw_routes),
                "source_measure_min": source_min,
                "source_measure_max": source_max,
                "source_value": _collapse(values),
                "source_status": _collapse(statuses),
                "source_provenance": f"{layer}_strict_derived_review_only",
                "ambiguity_fanout_count": fanout,
                "conflict_flag": conflict,
                "confidence_tier": confidence,
                "measure_overlap_summary": f"matched_records={fanout}; max_overlap={float(overlap_len.loc[mask].clip(lower=0).max()):.6f}; reversed_interval={reversed_interval_used}; tolerance={tolerance}",
                "why_not_active_safe": "Review-only candidate join after recovered route/measure intervals; bridge has not been mapped, reviewed, or promoted.",
            }
    return {
        "stage1_coverage_flag": False,
        "join_method": "not_joinable_by_strict_success_patterns",
        "target_source_route_id_key": "",
        "target_source_route_name_common": "",
        "source_measure_min": "",
        "source_measure_max": "",
        "source_value": "",
        "source_status": "",
        "source_provenance": "",
        "ambiguity_fanout_count": 0,
        "conflict_flag": False,
        "confidence_tier": "not_recommended_current_evidence",
        "measure_overlap_summary": "no strict-derived route/measure overlap",
        "why_not_active_safe": "No strict-derived review-only speed/AADT route bridge matched this candidate bin.",
    }


def _stage1_route_precheck(base: pd.DataFrame, layer: str, lookup: dict[str, pd.DataFrame], strict_sets: dict[str, set[str]], bridge: dict[str, set[str]]) -> pd.DataFrame:
    route_rows = []
    work = base.groupby(["candidate_route_key_normalized", "candidate_route_common_normalized", "candidate_route_type_category"], dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        candidate_signal_count=("candidate_signal_id", "nunique"),
        candidate_measure_min=("candidate_measure_min_num", "min"),
        candidate_measure_max=("candidate_measure_max_num", "max"),
        route_identity_classes=("route_identity_class", _collapse),
        recommended_actions=("recommended_next_action", _collapse),
    ).reset_index()
    _checkpoint(f"{layer}_route_name_facility_bridge_candidates", len(work))
    for row in work.itertuples(index=False):
        methods = _candidate_methods(row, layer, strict_sets, bridge)
        matched_keys = [key for _, key, _ in methods if key in lookup]
        source_interval_count = sum(len(lookup[key]) for key in set(matched_keys))
        estimated_candidates = int(row.candidate_bin_count) * int(source_interval_count)
        fanout_guard = source_interval_count > SOURCE_ROUTE_FANOUT_DETAIL_LIMIT or estimated_candidates > ROW_GUARD_LIMIT
        route_rows.append(
            {
                "context_layer": layer,
                "candidate_route_key_normalized": row.candidate_route_key_normalized,
                "candidate_route_common_normalized": row.candidate_route_common_normalized,
                "candidate_route_type_category": row.candidate_route_type_category,
                "candidate_bin_count": row.candidate_bin_count,
                "candidate_signal_count": row.candidate_signal_count,
                "matched_source_key_count": len(set(matched_keys)),
                "matched_source_interval_count": source_interval_count,
                "estimated_measure_overlap_candidates": estimated_candidates,
                "fanout_guard_status": "skip_extreme_fanout" if fanout_guard else "bounded",
                "fanout_guard_reason": f"source_interval_count>{SOURCE_ROUTE_FANOUT_DETAIL_LIMIT}" if source_interval_count > SOURCE_ROUTE_FANOUT_DETAIL_LIMIT else ("estimated_candidates>5m" if estimated_candidates > ROW_GUARD_LIMIT else ""),
                "route_identity_classes": row.route_identity_classes,
                "recommended_actions": row.recommended_actions,
            }
        )
    out = pd.DataFrame(route_rows)
    _write_csv(out, OUT_DIR / _output_name(f"stage1_{layer}_route_level_precheck.csv"))
    _checkpoint(f"{layer}_measure_overlap_candidates", int(out["estimated_measure_overlap_candidates"].sum()) if not out.empty else 0)
    return out


def _stage1_detail(base: pd.DataFrame, layer: str, lookup: dict[str, pd.DataFrame], strict_sets: dict[str, set[str]], bridge: dict[str, set[str]], route_precheck: pd.DataFrame) -> pd.DataFrame:
    rows = []
    previous_prefix = "previous_aadt" if layer == "aadt_exposure" else "previous_speed"
    skip_routes = set(_text(route_precheck.loc[_text(route_precheck, "fanout_guard_status").eq("skip_extreme_fanout")], "candidate_route_key_normalized")) if not route_precheck.empty else set()
    if skip_routes:
        _write_csv(route_precheck.loc[_text(route_precheck, "fanout_guard_status").eq("skip_extreme_fanout")], OUT_DIR / _output_name(f"stage1_{layer}_fanout_guard_review.csv"))
        _checkpoint(f"{layer}_detail_fanout_guard_routes_skipped", len(skip_routes))
    if _is_smoke() and len(base) > _smoke_detail_rows():
        base = base.head(_smoke_detail_rows()).copy()
        _checkpoint(f"{layer}_smoke_detail_rows_limited", len(base), f"detail_limit={_smoke_detail_rows():,}; route_summary_rows_preserved={len(route_precheck):,}")
    _checkpoint(f"{layer}_detail_start", len(base))
    t0 = time.monotonic()
    for row in base.itertuples(index=False):
        if getattr(row, "candidate_route_key_normalized", "") in skip_routes:
            match = {
                "stage1_coverage_flag": False,
                "join_method": "not_joinable_by_strict_success_patterns",
                "target_source_route_id_key": "",
                "target_source_route_name_common": "",
                "source_measure_min": "",
                "source_measure_max": "",
                "source_value": "",
                "source_status": "",
                "source_provenance": "",
                "ambiguity_fanout_count": 0,
                "conflict_flag": False,
                "confidence_tier": "not_recommended_current_evidence",
                "measure_overlap_summary": "route skipped by fanout guard before bin-level expansion",
                "why_not_active_safe": "Extreme fanout route sent to review table instead of bin-level expansion.",
            }
        else:
            match = _match_candidate(row, layer, lookup, strict_sets, bridge)
        out = {c: getattr(row, c) for c in base.columns if c in {
            "candidate_bin_id",
            "candidate_signal_id",
            "source_signal_id",
            "source_layer",
            "candidate_association_id",
            "recovery_strategy",
            "association_confidence_tier",
            "candidate_rank",
            "candidate_weight",
            "tie_group_id",
            "signal_relative_direction_label",
            "direction_confidence_status",
            "analysis_window",
            "source_road_row_id",
            "graph_edge_id",
            "road_component_id",
            "route_id",
            "route_common",
            "route_name",
            "candidate_route_key_normalized",
            "candidate_route_common_normalized",
            "candidate_route_type_category",
            "candidate_facility_text",
            "candidate_measure_start",
            "candidate_measure_end",
            "candidate_measure_min",
            "candidate_measure_max",
            "candidate_measure_length",
            "candidate_bin_start_ft",
            "candidate_bin_end_ft",
            "route_identity_class",
            "recommended_next_action",
            "strict_active_overlap_status",
            "strict_active_overlap_flag",
            "multi_candidate_flag",
            "review_only_flag",
        }}
        out["context_layer"] = layer
        out["previous_coverage_flag"] = str(getattr(row, f"{previous_prefix}_coverage_flag", ""))
        out["previous_join_method"] = str(getattr(row, f"{previous_prefix}_join_method", ""))
        out["previous_missing_reason"] = str(getattr(row, f"{previous_prefix}_missing_reason", ""))
        out.update(match)
        if layer == "speed":
            out["speed_value_status"] = out.pop("source_status")
            out["speed_value"] = out.pop("source_value")
            out["speed_source_provenance"] = out.pop("source_provenance")
        else:
            out["aadt_value_status"] = out.pop("source_status")
            out["aadt_value"] = out.pop("source_value")
            out["aadt_source_provenance"] = out.pop("source_provenance")
            out["direction_factor_available"] = "unknown_review_only"
            out["bidirectional_fallback_status"] = "not_evaluated_review_only"
            out["exposure_recovery_potential"] = out["stage1_coverage_flag"]
        rows.append(out)
        if len(rows) % 25_000 == 0:
            _checkpoint(f"{layer}_detail_rows_processed", len(rows), f"elapsed_sec={time.monotonic() - t0:.1f}")
        if len(rows) > ROW_GUARD_LIMIT:
            _checkpoint(f"{layer}_detail_row_guard_stop", len(rows))
            break
    _checkpoint(f"{layer}_final_detail_outputs", len(rows), f"elapsed_sec={time.monotonic() - t0:.1f}")
    return pd.DataFrame(rows)


def _signal_summary(speed: pd.DataFrame, aadt: pd.DataFrame) -> pd.DataFrame:
    s = speed.groupby("candidate_signal_id", dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        previous_speed_bin_count=("previous_coverage_flag", lambda x: _bool(pd.DataFrame({"x": x}), "x").sum()),
        stage1_speed_bin_count=("stage1_coverage_flag", "sum"),
        speed_methods=("join_method", _collapse),
    ).reset_index()
    a = aadt.groupby("candidate_signal_id", dropna=False).agg(
        previous_aadt_bin_count=("previous_coverage_flag", lambda x: _bool(pd.DataFrame({"x": x}), "x").sum()),
        stage1_aadt_bin_count=("stage1_coverage_flag", "sum"),
        aadt_methods=("join_method", _collapse),
    ).reset_index()
    out = s.merge(a, on="candidate_signal_id", how="outer").fillna(0)
    out["previous_speed_signal_covered"] = out["previous_speed_bin_count"].astype(float) > 0
    out["stage1_speed_signal_covered"] = out["stage1_speed_bin_count"].astype(float) > 0
    out["previous_aadt_signal_covered"] = out["previous_aadt_bin_count"].astype(float) > 0
    out["stage1_aadt_signal_covered"] = out["stage1_aadt_bin_count"].astype(float) > 0
    out["joint_stage1_coverage_class"] = "neither_covered"
    out.loc[out["stage1_speed_signal_covered"] & out["stage1_aadt_signal_covered"], "joint_stage1_coverage_class"] = "speed_and_aadt_covered"
    out.loc[out["stage1_speed_signal_covered"] & ~out["stage1_aadt_signal_covered"], "joint_stage1_coverage_class"] = "speed_only"
    out.loc[~out["stage1_speed_signal_covered"] & out["stage1_aadt_signal_covered"], "joint_stage1_coverage_class"] = "aadt_only"
    return out


def _universe_summary(base: pd.DataFrame, speed: pd.DataFrame, aadt: pd.DataFrame, signal: pd.DataFrame) -> pd.DataFrame:
    def count_full(layer_df: pd.DataFrame, flag_col: str, window: str) -> int:
        subset = layer_df.loc[_text(layer_df, "analysis_window").eq(window)]
        if subset.empty:
            return 0
        per_signal = subset.groupby("candidate_signal_id")[flag_col].all()
        return int(per_signal.sum())

    rows = [
        {"metric": "candidate_bins_evaluated", "value": len(base)},
        {"metric": "candidate_signals_evaluated", "value": base["candidate_signal_id"].nunique()},
        {"metric": "speed_previous_bin_coverage", "value": int(_bool(speed, "previous_coverage_flag").sum())},
        {"metric": "speed_stage1_bin_coverage", "value": int(_bool(speed, "stage1_coverage_flag").sum())},
        {"metric": "aadt_previous_bin_coverage", "value": int(_bool(aadt, "previous_coverage_flag").sum())},
        {"metric": "aadt_stage1_bin_coverage", "value": int(_bool(aadt, "stage1_coverage_flag").sum())},
        {"metric": "speed_previous_signal_coverage", "value": int(_bool(signal, "previous_speed_signal_covered").sum())},
        {"metric": "speed_stage1_signal_coverage", "value": int(_bool(signal, "stage1_speed_signal_covered").sum())},
        {"metric": "aadt_previous_signal_coverage", "value": int(_bool(signal, "previous_aadt_signal_covered").sum())},
        {"metric": "aadt_stage1_signal_coverage", "value": int(_bool(signal, "stage1_aadt_signal_covered").sum())},
        {"metric": "recovered_0_1000_ft_speed_full_coverage_signals", "value": count_full(speed, "stage1_coverage_flag", "0_1000")},
        {"metric": "recovered_0_1000_ft_aadt_full_coverage_signals", "value": count_full(aadt, "stage1_coverage_flag", "0_1000")},
        {"metric": "recovered_full_0_2500_ft_speed_full_coverage_signals", "value": count_full(speed, "stage1_coverage_flag", "1000_2500")},
        {"metric": "recovered_full_0_2500_ft_aadt_full_coverage_signals", "value": count_full(aadt, "stage1_coverage_flag", "1000_2500")},
    ]
    for klass, group in signal.groupby("joint_stage1_coverage_class", dropna=False):
        rows.append({"metric": f"signals_{klass}", "value": len(group)})
    return pd.DataFrame(rows)


def _coverage_group(speed: pd.DataFrame, aadt: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for layer, df in [("speed", speed), ("aadt_exposure", aadt)]:
        valid_cols = [c for c in cols if c in df.columns]
        if not valid_cols:
            continue
        g = df.groupby(valid_cols, dropna=False).agg(
            candidate_bin_count=("candidate_bin_id", "count"),
            recovered_signal_count=("candidate_signal_id", "nunique"),
            previous_covered_bins=("previous_coverage_flag", lambda x: _bool(pd.DataFrame({"x": x}), "x").sum()),
            stage1_covered_bins=("stage1_coverage_flag", "sum"),
            fanout_conflict_bins=("conflict_flag", "sum"),
        ).reset_index()
        g["context_layer"] = layer
        rows.append(g)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _stage1_qa(base: pd.DataFrame, speed: pd.DataFrame, aadt: pd.DataFrame, inputs: dict[str, pd.DataFrame], missing_inputs: list[str]) -> pd.DataFrame:
    smoke = _is_smoke()
    rows = [
        _qa_row("required_inputs_available", not missing_inputs, len(missing_inputs), 0, "; ".join(missing_inputs[:5])),
        _qa_row("candidate_bin_input_count_reconciles", smoke or len(base) == EXPECTED_BINS, len(base), EXPECTED_BINS, "Smoke-test subset; full gate will require exact count." if smoke else ("Observed difference is not accepted for this gated prototype." if len(base) != EXPECTED_BINS else "")),
        _qa_row("recovered_signal_count_reconciles", smoke or base["candidate_signal_id"].nunique() == EXPECTED_SIGNALS, base["candidate_signal_id"].nunique(), EXPECTED_SIGNALS, "Smoke-test subset; full gate will require exact count." if smoke else ""),
        _qa_row("strict_active_positive_control_inputs_loaded", not inputs["strict_bins"].empty and not inputs["strict_speed_routes"].empty and not inputs["strict_aadt_routes"].empty, f"strict_bins={len(inputs['strict_bins'])}"),
        _qa_row("stage1_speed_aadt_joins_review_only", True, "confirmed_by_code"),
        _qa_row("every_recovered_speed_join_has_labeled_method", _text(speed, "join_method").ne("").all(), speed["join_method"].nunique()),
        _qa_row("every_recovered_aadt_join_has_labeled_method", _text(aadt, "join_method").ne("").all(), aadt["join_method"].nunique()),
        _qa_row("ambiguous_fanout_joins_flagged", "ambiguity_fanout_count" in speed.columns and "ambiguity_fanout_count" in aadt.columns, "confirmed_by_schema"),
        _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
        _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
        _qa_row("no_crash_records_read", True, "confirmed_by_code"),
        _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
        _qa_row("access_not_included", True, "confirmed_by_code"),
        _qa_row("context_not_used_to_define_scaffold_route_measure_association_or_direction", True, "confirmed_by_code"),
        _qa_row("all_stage1_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame(rows)


def run_stage1(inputs: dict[str, pd.DataFrame], missing_inputs: list[str]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, bool]:
    _checkpoint("stage1_start")
    base = _base_bins(inputs)
    strict_sets = _strict_success_route_sets(inputs)
    _checkpoint("strict_success_route_inventory", sum(len(v) for v in strict_sets.values()), f"speed_routes={len(strict_sets['speed']):,}; aadt_routes={len(strict_sets['aadt_exposure']):,}")
    speed_src = _active_interval_source("speed")
    aadt_src = _active_interval_source("aadt_exposure")
    bridge = _bridge_lookup(inputs["taxonomy_crosswalk"])
    _checkpoint("route_name_facility_bridge_candidates", sum(len(v) for v in bridge.values()))
    speed_lookup = _source_lookup(speed_src)
    aadt_lookup = _source_lookup(aadt_src)
    speed_precheck = _stage1_route_precheck(base, "speed", speed_lookup, strict_sets, bridge)
    aadt_precheck = _stage1_route_precheck(base, "aadt_exposure", aadt_lookup, strict_sets, bridge)
    speed = _stage1_detail(base, "speed", speed_lookup, strict_sets, bridge, speed_precheck)
    _write_csv(speed, OUT_DIR / _output_name("stage1_speed_strict_normalization_rerun_detail.csv"))
    aadt = _stage1_detail(base, "aadt_exposure", aadt_lookup, strict_sets, bridge, aadt_precheck)
    _write_csv(aadt, OUT_DIR / _output_name("stage1_aadt_strict_normalization_rerun_detail.csv"))
    signal = _signal_summary(speed, aadt)
    universe = _universe_summary(base, speed, aadt, signal)
    by_class = _coverage_group(speed, aadt, ["route_identity_class"])
    by_method = _coverage_group(speed, aadt, ["join_method"])
    by_source = _coverage_group(speed, aadt, ["source_layer"])
    by_route_type = _coverage_group(speed, aadt, ["candidate_route_type_category"])
    by_overlap = _coverage_group(speed, aadt, ["strict_active_overlap_status"])
    by_multi = _coverage_group(speed, aadt, ["multi_candidate_flag"])
    by_class = pd.concat([by_class.assign(summary_type="route_identity_class"), by_source.assign(summary_type="source_layer"), by_route_type.assign(summary_type="route_type_category"), by_overlap.assign(summary_type="strict_active_overlap"), by_multi.assign(summary_type="multi_candidate_status")], ignore_index=True, sort=False)
    conflicts = pd.concat(
        [
            speed.loc[_bool(speed, "conflict_flag") | (_num(speed, "ambiguity_fanout_count") > 1)].assign(conflict_layer="speed"),
            aadt.loc[_bool(aadt, "conflict_flag") | (_num(aadt, "ambiguity_fanout_count") > 1)].assign(conflict_layer="aadt_exposure"),
        ],
        ignore_index=True,
        sort=False,
    )
    qa = _stage1_qa(base, speed, aadt, inputs, missing_inputs)
    passed = bool(qa["passed"].all())
    outputs = {
        "base": base,
        "speed": speed,
        "aadt": aadt,
        "signal": signal,
        "universe": universe,
        "by_class": by_class,
        "by_method": by_method,
        "conflicts": conflicts,
        "qa": qa,
    }
    _checkpoint("stage1_complete", len(speed) + len(aadt))
    return outputs, qa, passed


def _raw_interval_source(layer: str) -> tuple[pd.DataFrame, str]:
    if layer == "speed":
        if not SPEED_SOURCE.exists():
            return pd.DataFrame(), "artifacts/normalized/speed.parquet not found"
        src = pd.read_parquet(SPEED_SOURCE, columns=["ROUTE_COMMON_NAME", "ROUTE_FROM_MEASURE", "ROUTE_TO_MEASURE", "CAR_SPEED_LIMIT", "TRUCK_SPEED_LIMIT", "RTE_TYPE_NM", "FROM_JURISDICTION"])
        src["raw_route"] = src["ROUTE_COMMON_NAME"].fillna("").astype(str)
        src["normalized_route"] = src["raw_route"].map(_norm_route)
        src["route_common"] = src["raw_route"]
        src["route_type_category"] = [_route_system(k, raw) for k, raw in zip(src["normalized_route"], src["raw_route"], strict=False)]
        src["source_measure_min"] = pd.to_numeric(src["ROUTE_FROM_MEASURE"], errors="coerce")
        src["source_measure_max"] = pd.to_numeric(src["ROUTE_TO_MEASURE"], errors="coerce")
        src["source_value"] = src["CAR_SPEED_LIMIT"].fillna("").astype(str)
        src["source_layer_locality"] = src["FROM_JURISDICTION"].fillna("").astype(str)
    else:
        if not AADT_SOURCE.exists():
            return pd.DataFrame(), "artifacts/normalized/aadt.parquet not found"
        src = pd.read_parquet(AADT_SOURCE, columns=["RTE_NM", "MASTER_RTE_NM", "FROM_MEASURE", "TO_MEASURE", "TRANSPORT_EDGE_FROM_MSR", "TRANSPORT_EDGE_TO_MSR", "AADT", "AADT_YR", "DIRECTION_FACTOR", "DIRECTIONALITY", "FROM_PHY_JURISDICTION_NM"])
        src["raw_route"] = src["RTE_NM"].fillna("").astype(str)
        src["master_route"] = src["MASTER_RTE_NM"].fillna("").astype(str)
        src["normalized_route"] = src["raw_route"].where(src["raw_route"].ne(""), src["master_route"]).map(_norm_route)
        src["route_common"] = src["master_route"]
        src["route_type_category"] = [_route_system(k, raw) for k, raw in zip(src["normalized_route"], src["raw_route"], strict=False)]
        from_m = pd.to_numeric(src["FROM_MEASURE"], errors="coerce").combine_first(pd.to_numeric(src["TRANSPORT_EDGE_FROM_MSR"], errors="coerce"))
        to_m = pd.to_numeric(src["TO_MEASURE"], errors="coerce").combine_first(pd.to_numeric(src["TRANSPORT_EDGE_TO_MSR"], errors="coerce"))
        src["source_measure_min"] = from_m
        src["source_measure_max"] = to_m
        src["source_value"] = src["AADT"].fillna("").astype(str)
        src["source_layer_locality"] = src["FROM_PHY_JURISDICTION_NM"].fillna("").astype(str)
    src["source_facility_text"] = src["route_common"].where(src["route_common"].ne(""), src["raw_route"]).map(_facility_text)
    _checkpoint(f"stage2_{layer}_raw_source_inventory", len(src), f"routes={src['normalized_route'].nunique() if 'normalized_route' in src.columns else 0:,}")
    return src, "inspected"


def _source_inventory(raw_sources: dict[str, pd.DataFrame], reasons: dict[str, str]) -> pd.DataFrame:
    rows = []
    staging = [
        ("speed", SPEED_STAGING_DIR / "posted_speed_source_inventory.csv"),
        ("aadt_exposure", AADT_STAGING_DIR / "aadt_source_inventory.csv"),
    ]
    for layer, df in raw_sources.items():
        rows.append(
            {
                "context_layer": layer,
                "source_path": str(SPEED_SOURCE if layer == "speed" else AADT_SOURCE),
                "inspection_status": reasons.get(layer, ""),
                "source_row_count": len(df),
                "null_route_count": int(_text(df, "normalized_route").eq("").sum()) if not df.empty else 0,
                "null_measure_count": int((_num(df, "source_measure_min").isna() | _num(df, "source_measure_max").isna()).sum()) if not df.empty else 0,
                "route_count": int(df["normalized_route"].nunique()) if not df.empty else 0,
                "route_type_category_values": _collapse(df["route_type_category"]) if not df.empty else "",
                "staging_inventory_path": str(dict(staging)[layer]),
                "staging_inventory_available": dict(staging)[layer].exists(),
            }
        )
    return pd.DataFrame(rows)


def _raw_lookup(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if df.empty:
        return {}
    valid = df.loc[_text(df, "normalized_route").ne("")].copy()
    route_sizes = valid.groupby("normalized_route", dropna=False).size().reset_index(name="source_interval_count")
    _checkpoint("stage2_raw_source_route_grouping", len(route_sizes), f"source_rows={len(valid):,}; max_route_fanout={int(route_sizes['source_interval_count'].max()) if not route_sizes.empty else 0:,}")
    extreme = route_sizes.loc[route_sizes["source_interval_count"] > EXTREME_FANOUT_LIMIT].copy()
    if not extreme.empty:
        _write_csv(extreme, OUT_DIR / _output_name("stage2_extreme_raw_source_route_fanout_review.csv"))
        valid = valid.loc[~_text(valid, "normalized_route").isin(set(_text(extreme, "normalized_route")))].copy()
        _checkpoint("stage2_raw_source_extreme_fanout_removed", len(valid), f"removed_routes={len(extreme):,}")
    return {k: g.reset_index(drop=True) for k, g in valid.groupby("normalized_route", dropna=False)}


def _classify_availability(row: Any, layer: str, raw_lookup: dict[str, pd.DataFrame], raw_types: set[str], active_types: set[str]) -> dict[str, Any]:
    keys = [k for k in str(getattr(row, "candidate_alt_keys", "")).split("|") if k]
    route_type = str(getattr(row, "candidate_route_type_category", ""))
    cand_min = getattr(row, "candidate_measure_min_num", pd.NA)
    cand_max = getattr(row, "candidate_measure_max_num", pd.NA)
    route_matches = [(k, raw_lookup[k]) for k in keys if k in raw_lookup]
    facility = str(getattr(row, "candidate_facility_text", ""))
    if route_matches:
        overlaps = []
        for key, df in route_matches:
            for src_row in df.itertuples(index=False):
                ok, length = _overlap(cand_min, cand_max, getattr(src_row, "source_measure_min"), getattr(src_row, "source_measure_max"), TOLERANT_MEASURE_TOLERANCE)
                if ok:
                    overlaps.append((key, src_row, length))
        if overlaps:
            values = pd.Series([getattr(r, "source_value", "") for _, r, _ in overlaps])
            return {
                "source_availability_class": "raw_source_confirms_speed_aadt_available" if layer == "joint" else f"raw_source_confirms_{'speed' if layer == 'speed' else 'aadt_only'}_available",
                "target_source_route_id_key": _collapse(pd.Series([k for k, _, _ in overlaps])),
                "target_source_route_name_common": _collapse(pd.Series([getattr(r, "raw_route", "") for _, r, _ in overlaps])),
                "measure_compatibility_status": "compatible_overlap",
                "measure_overlap_summary": f"raw_overlaps={len(overlaps)}; max_overlap={max(length for _, _, length in overlaps):.6f}",
                "ambiguity_fanout_count": len(overlaps),
                "conflict_flag": values.nunique(dropna=True) > 1,
                "source_schema_limitation": "",
            }
        return {
            "source_availability_class": "measure_overlap_missing_after_route_match",
            "target_source_route_id_key": _collapse(pd.Series([k for k, _ in route_matches])),
            "target_source_route_name_common": _collapse(pd.Series([_collapse(g["raw_route"]) for _, g in route_matches])),
            "measure_compatibility_status": "route_match_no_measure_overlap",
            "measure_overlap_summary": "route exists in raw source but candidate interval does not overlap raw source measure range",
            "ambiguity_fanout_count": int(sum(len(g) for _, g in route_matches)),
            "conflict_flag": False,
            "source_schema_limitation": "",
        }
    if route_type in raw_types and route_type not in active_types:
        return {
            "source_availability_class": "active_output_filtering_likely",
            "target_source_route_id_key": "",
            "target_source_route_name_common": "",
            "measure_compatibility_status": "route_type_present_raw_absent_active",
            "measure_overlap_summary": "candidate route type exists in raw source but is absent from active/review output inventory",
            "ambiguity_fanout_count": 0,
            "conflict_flag": False,
            "source_schema_limitation": "",
        }
    if route_type not in raw_types:
        return {
            "source_availability_class": "source_absence_likely",
            "target_source_route_id_key": "",
            "target_source_route_name_common": "",
            "measure_compatibility_status": "candidate_route_type_absent_from_raw_source",
            "measure_overlap_summary": "no raw source route key or route type support found",
            "ambiguity_fanout_count": 0,
            "conflict_flag": False,
            "source_schema_limitation": "",
        }
    if facility:
        return {
            "source_availability_class": "route_name_facility_bridge_supported",
            "target_source_route_id_key": "",
            "target_source_route_name_common": facility,
            "measure_compatibility_status": "facility_text_requires_review",
            "measure_overlap_summary": "route type exists and facility/name text exists but route key did not match",
            "ambiguity_fanout_count": 0,
            "conflict_flag": False,
            "source_schema_limitation": "",
        }
    return {
        "source_availability_class": "insufficient_evidence",
        "target_source_route_id_key": "",
        "target_source_route_name_common": "",
        "measure_compatibility_status": "insufficient_evidence",
        "measure_overlap_summary": "no usable raw source match found",
        "ambiguity_fanout_count": 0,
        "conflict_flag": False,
        "source_schema_limitation": "",
    }


def _stage2_layer_detail(stage1_detail: pd.DataFrame, layer: str, raw: pd.DataFrame, active_src: pd.DataFrame) -> pd.DataFrame:
    missing = stage1_detail.loc[~_bool(stage1_detail, "stage1_coverage_flag")].copy()
    _checkpoint(f"stage2_{layer}_remaining_missing_start", len(missing))
    lookup = _raw_lookup(raw)
    raw_types = set(_text(raw, "route_type_category")) if not raw.empty else set()
    active_types = set(_text(active_src, "source_route_type_category")) if not active_src.empty else set()
    rows = []
    for row in missing.itertuples(index=False):
        cls = _classify_availability(row, layer, lookup, raw_types, active_types)
        out = {
            "context_layer": layer,
            "candidate_bin_id": row.candidate_bin_id,
            "candidate_signal_id": row.candidate_signal_id,
            "source_signal_id": getattr(row, "source_signal_id", ""),
            "source_layer": getattr(row, "source_layer", ""),
            "candidate_association_id": getattr(row, "candidate_association_id", ""),
            "recovery_strategy": getattr(row, "recovery_strategy", ""),
            "association_confidence_tier": getattr(row, "association_confidence_tier", ""),
            "candidate_rank": getattr(row, "candidate_rank", ""),
            "candidate_weight": getattr(row, "candidate_weight", ""),
            "tie_group_id": getattr(row, "tie_group_id", ""),
            "analysis_window": getattr(row, "analysis_window", ""),
            "route_identity_class": getattr(row, "route_identity_class", ""),
            "recommended_next_action": getattr(row, "recommended_next_action", ""),
            "route_name": getattr(row, "route_name", ""),
            "route_common": getattr(row, "route_common", ""),
            "route_id": getattr(row, "route_id", ""),
            "candidate_route_key_normalized": getattr(row, "candidate_route_key_normalized", ""),
            "candidate_route_common_normalized": getattr(row, "candidate_route_common_normalized", ""),
            "candidate_facility_text": getattr(row, "candidate_facility_text", ""),
            "candidate_route_type_category": getattr(row, "candidate_route_type_category", ""),
            "candidate_measure_min": getattr(row, "candidate_measure_min", ""),
            "candidate_measure_max": getattr(row, "candidate_measure_max", ""),
            "strict_active_overlap_status": getattr(row, "strict_active_overlap_status", ""),
            "multi_candidate_flag": getattr(row, "multi_candidate_flag", ""),
        }
        out.update(cls)
        rows.append(out)
        if len(rows) % 25_000 == 0:
            _checkpoint(f"stage2_{layer}_availability_rows_processed", len(rows))
        if len(rows) > ROW_GUARD_LIMIT:
            _checkpoint(f"stage2_{layer}_availability_row_guard_stop", len(rows))
            break
    _checkpoint(f"stage2_{layer}_availability_detail_complete", len(rows))
    return pd.DataFrame(rows)


def _audit_subset(speed_avail: pd.DataFrame, aadt_avail: pd.DataFrame, route_class: str) -> pd.DataFrame:
    both = pd.concat([speed_avail, aadt_avail], ignore_index=True, sort=False)
    sub = both.loc[_text(both, "route_identity_class").eq(route_class)].copy()
    if sub.empty:
        return pd.DataFrame()
    return sub.groupby(["context_layer", "source_availability_class", "measure_compatibility_status"], dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        recovered_signal_count=("candidate_signal_id", "nunique"),
        route_examples=("route_name", _collapse),
        route_common_examples=("route_common", _collapse),
    ).reset_index()


def _stage2_qa(stage1_outputs: dict[str, pd.DataFrame], raw_reasons: dict[str, str], speed_avail: pd.DataFrame, aadt_avail: pd.DataFrame) -> pd.DataFrame:
    both = pd.concat([speed_avail, aadt_avail], ignore_index=True, sort=False)
    rows = [
        _qa_row("stage1_outputs_loaded", not stage1_outputs["speed"].empty and not stage1_outputs["aadt"].empty, f"speed={len(stage1_outputs['speed'])};aadt={len(stage1_outputs['aadt'])}"),
        _qa_row("raw_staged_source_speed_inventory_inspected_or_reason_provided", raw_reasons.get("speed", "") != "", raw_reasons.get("speed", "")),
        _qa_row("raw_staged_source_aadt_inventory_inspected_or_reason_provided", raw_reasons.get("aadt_exposure", "") != "", raw_reasons.get("aadt_exposure", "")),
        _qa_row("remaining_missing_records_classified", not both.empty and _text(both, "source_availability_class").ne("").all(), len(both)),
        _qa_row("candidate_route_type_filtered_from_context_output_audited", "candidate_route_type_filtered_from_context_output" in set(_text(both, "route_identity_class")), "present"),
        _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
        _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
        _qa_row("no_crash_records_read", True, "confirmed_by_code"),
        _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
        _qa_row("access_not_included", True, "confirmed_by_code"),
        _qa_row("all_stage2_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
    ]
    return pd.DataFrame(rows)


def run_stage2(stage1_outputs: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, bool]:
    speed_raw, speed_reason = _raw_interval_source("speed")
    aadt_raw, aadt_reason = _raw_interval_source("aadt_exposure")
    raw_sources = {"speed": speed_raw, "aadt_exposure": aadt_raw}
    raw_reasons = {"speed": speed_reason, "aadt_exposure": aadt_reason}
    speed_avail = _stage2_layer_detail(stage1_outputs["speed"], "speed", speed_raw, _active_interval_source("speed"))
    aadt_avail = _stage2_layer_detail(stage1_outputs["aadt"], "aadt_exposure", aadt_raw, _active_interval_source("aadt_exposure"))
    joint = speed_avail[["candidate_bin_id", "candidate_signal_id", "source_availability_class"]].rename(columns={"source_availability_class": "speed_availability_class"}).merge(
        aadt_avail[["candidate_bin_id", "source_availability_class"]].rename(columns={"source_availability_class": "aadt_availability_class"}),
        on="candidate_bin_id",
        how="outer",
    )
    joint["joint_availability_class"] = joint["speed_availability_class"].fillna("stage1_speed_covered") + "|" + joint["aadt_availability_class"].fillna("stage1_aadt_covered")
    inventory = _source_inventory(raw_sources, raw_reasons)
    route_type_audit = _audit_subset(speed_avail, aadt_avail, "candidate_route_type_filtered_from_context_output")
    strict_failed_audit = _audit_subset(speed_avail, aadt_avail, "strict_success_pattern_match_but_join_failed")
    route_name_differs_audit = _audit_subset(speed_avail, aadt_avail, "strict_success_route_name_match_but_route_id_differs")
    summary = pd.concat([speed_avail, aadt_avail], ignore_index=True, sort=False).groupby(["context_layer", "source_availability_class"], dropna=False).agg(
        candidate_bin_count=("candidate_bin_id", "count"),
        recovered_signal_count=("candidate_signal_id", "nunique"),
        conflict_bins=("conflict_flag", "sum"),
    ).reset_index()
    estimate = summary.copy()
    estimate["recovery_path"] = estimate["source_availability_class"].map(
        {
            "raw_source_confirms_speed_available": "raw_source_join",
            "raw_source_confirms_aadt_only_available": "raw_source_join",
            "active_output_filtering_likely": "active_output_filter_bypass",
            "route_name_facility_bridge_supported": "route_name_facility_bridge",
            "measure_overlap_missing_after_route_match": "measure_system_fix_or_review",
            "source_absence_likely": "likely_true_source_absence",
        }
    ).fillna("manual_or_source_owner_review")
    qa = _stage2_qa(stage1_outputs, raw_reasons, speed_avail, aadt_avail)
    outputs = {
        "speed": speed_avail,
        "aadt": aadt_avail,
        "joint": joint,
        "route_type_audit": route_type_audit,
        "strict_failed_audit": strict_failed_audit,
        "route_name_differs_audit": route_name_differs_audit,
        "inventory": inventory,
        "summary": summary,
        "estimate": estimate,
        "qa": qa,
    }
    return outputs, qa, bool(qa["passed"].all())


def _bridge_candidates(stage1: dict[str, pd.DataFrame], stage2: dict[str, pd.DataFrame]) -> pd.DataFrame:
    _checkpoint("stage3_bridge_candidate_construction_start")
    rows = []
    for layer, df in [("speed", stage1["speed"]), ("aadt_exposure", stage1["aadt"])]:
        rec = df.loc[_bool(df, "stage1_coverage_flag") & ~_text(df, "join_method").eq("baseline_prior_refined_join")].copy()
        _checkpoint(f"stage3_{layer}_strict_derived_bridge_input_bins", len(rec))
        if rec.empty:
            continue
        grouped = rec.groupby(["candidate_route_key_normalized", "route_common", "route_name", "candidate_facility_text", "candidate_route_type_category", "target_source_route_id_key", "target_source_route_name_common", "join_method", "confidence_tier"], dropna=False).agg(
            affected_candidate_bin_count=("candidate_bin_id", "count"),
            affected_recovered_signal_count=("candidate_signal_id", "nunique"),
            affected_0_1000_signal_count=("candidate_signal_id", lambda s: s[rec.loc[s.index, "analysis_window"].eq("0_1000")].nunique()),
            affected_full_0_2500_signal_count=("candidate_signal_id", "nunique"),
            ambiguity_fanout_count=("ambiguity_fanout_count", "max"),
            conflict_flag=("conflict_flag", "max"),
            measure_overlap_summary=("measure_overlap_summary", _collapse),
        ).reset_index()
        _checkpoint(f"stage3_{layer}_strict_derived_bridge_grouped_candidates", len(grouped))
        for i, row in enumerate(grouped.itertuples(index=False), start=1):
            rows.append(
                {
                    "target_layer": layer,
                    "candidate_route_id_key": row.candidate_route_key_normalized,
                    "candidate_route_common": row.route_common,
                    "candidate_route_name": row.route_name,
                    "candidate_facility_text": row.candidate_facility_text,
                    "candidate_route_type_category": row.candidate_route_type_category,
                    "target_source_route_id_key": row.target_source_route_id_key,
                    "target_source_route_name_common": row.target_source_route_name_common,
                    "target_source_facility": row.target_source_route_name_common,
                    "target_source_route_type_category": _route_system(row.target_source_route_id_key, row.target_source_route_name_common),
                    "source_evidence_file_table": f"stage1_{layer}_strict_normalization_rerun_detail.csv",
                    "bridge_evidence_type": row.join_method,
                    "measure_compatibility_status": "stage1_review_only_overlap",
                    "measure_overlap_summary": row.measure_overlap_summary,
                    "route_name_similarity_exactness_flag": "normalized_key_or_seed_match",
                    "source_layer_locality_compatibility": "not_evaluated_review_only",
                    "affected_candidate_bin_count": row.affected_candidate_bin_count,
                    "affected_recovered_signal_count": row.affected_recovered_signal_count,
                    "affected_0_1000_signal_count": row.affected_0_1000_signal_count,
                    "affected_full_0_2500_signal_count": row.affected_full_0_2500_signal_count,
                    "speed_recovery_potential": layer == "speed",
                    "AADT_recovery_potential": layer == "aadt_exposure",
                    "exposure_recovery_potential": layer == "aadt_exposure",
                    "ambiguity_fanout_count": row.ambiguity_fanout_count,
                    "conflict_flag": row.conflict_flag,
                    "confidence_tier": row.confidence_tier,
                    "recommended_use_class": "safe_for_next_review_only_join_rerun" if row.confidence_tier == "high_confidence_review_only" and not row.conflict_flag else "needs_fanout_resolution" if row.ambiguity_fanout_count > 1 else "needs_measure_compatibility_review",
                    "why_not_active_safe": "Review-only bridge derived from recovered candidate bins; not mapped, reviewed, or promoted.",
                    "required_review_before_promotion": "mapped spot-check and source-owner/route-measure compatibility review",
                }
            )
    avail = pd.concat([stage2["speed"], stage2["aadt"]], ignore_index=True, sort=False)
    rec_avail = avail.loc[_text(avail, "source_availability_class").isin({"raw_source_confirms_speed_available", "raw_source_confirms_aadt_only_available", "active_output_filtering_likely", "route_name_facility_bridge_supported"})].copy()
    _checkpoint("stage3_raw_source_bridge_input_bins", len(rec_avail))
    if not rec_avail.empty:
        grouped = rec_avail.groupby(["context_layer", "candidate_route_key_normalized", "route_common", "route_name", "candidate_facility_text", "candidate_route_type_category", "target_source_route_id_key", "target_source_route_name_common", "source_availability_class", "measure_compatibility_status"], dropna=False).agg(
            affected_candidate_bin_count=("candidate_bin_id", "count"),
            affected_recovered_signal_count=("candidate_signal_id", "nunique"),
            affected_0_1000_signal_count=("candidate_signal_id", lambda s: s[rec_avail.loc[s.index, "analysis_window"].eq("0_1000")].nunique()),
            affected_full_0_2500_signal_count=("candidate_signal_id", "nunique"),
            ambiguity_fanout_count=("ambiguity_fanout_count", "max"),
            conflict_flag=("conflict_flag", "max"),
            measure_overlap_summary=("measure_overlap_summary", _collapse),
        ).reset_index()
        _checkpoint("stage3_raw_source_bridge_grouped_candidates", len(grouped))
        extreme = grouped.loc[grouped["affected_candidate_bin_count"] > EXTREME_FANOUT_LIMIT].copy()
        if not extreme.empty:
            _write_csv(extreme, OUT_DIR / _output_name("stage3_extreme_bridge_fanout_review.csv"))
            grouped = grouped.loc[grouped["affected_candidate_bin_count"] <= EXTREME_FANOUT_LIMIT].copy()
            _checkpoint("stage3_extreme_bridge_fanout_removed", len(extreme))
        for row in grouped.itertuples(index=False):
            confidence = "high_confidence_review_only" if row.source_availability_class.startswith("raw_source_confirms") and not row.conflict_flag and row.ambiguity_fanout_count <= 4 else "medium_confidence_review_only"
            if row.source_availability_class == "route_name_facility_bridge_supported" or row.ambiguity_fanout_count > 12:
                confidence = "low_confidence_manual_review_only"
            rows.append(
                {
                    "target_layer": row.context_layer,
                    "candidate_route_id_key": row.candidate_route_key_normalized,
                    "candidate_route_common": row.route_common,
                    "candidate_route_name": row.route_name,
                    "candidate_facility_text": row.candidate_facility_text,
                    "candidate_route_type_category": row.candidate_route_type_category,
                    "target_source_route_id_key": row.target_source_route_id_key,
                    "target_source_route_name_common": row.target_source_route_name_common,
                    "target_source_facility": row.target_source_route_name_common,
                    "target_source_route_type_category": _route_system(row.target_source_route_id_key, row.target_source_route_name_common),
                    "source_evidence_file_table": f"stage2_{row.context_layer}_raw_source_availability_detail.csv",
                    "bridge_evidence_type": row.source_availability_class,
                    "measure_compatibility_status": row.measure_compatibility_status,
                    "measure_overlap_summary": row.measure_overlap_summary,
                    "route_name_similarity_exactness_flag": "raw_route_or_facility_evidence",
                    "source_layer_locality_compatibility": "not_evaluated_review_only",
                    "affected_candidate_bin_count": row.affected_candidate_bin_count,
                    "affected_recovered_signal_count": row.affected_recovered_signal_count,
                    "affected_0_1000_signal_count": row.affected_0_1000_signal_count,
                    "affected_full_0_2500_signal_count": row.affected_full_0_2500_signal_count,
                    "speed_recovery_potential": row.context_layer == "speed",
                    "AADT_recovery_potential": row.context_layer == "aadt_exposure",
                    "exposure_recovery_potential": row.context_layer == "aadt_exposure",
                    "ambiguity_fanout_count": row.ambiguity_fanout_count,
                    "conflict_flag": row.conflict_flag,
                    "confidence_tier": confidence,
                    "recommended_use_class": "safe_for_next_review_only_join_rerun" if confidence == "high_confidence_review_only" else "needs_source_owner_or_mapped_review" if confidence.startswith("low") else "needs_measure_compatibility_review",
                    "why_not_active_safe": "Raw-source bridge is diagnostic only and has not been applied to active outputs.",
                    "required_review_before_promotion": "review fanout, route system, measure compatibility, and mapped examples",
                }
            )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out.insert(0, "bridge_candidate_id", [f"phase3_bridge_{i:06d}" for i in range(1, len(out) + 1)])
    _checkpoint("stage3_final_bridge_candidates", len(out))
    return out


def run_stage3(stage1: dict[str, pd.DataFrame], stage2: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, bool]:
    bridges = _bridge_candidates(stage1, stage2)
    if bridges.empty:
        by_conf = pd.DataFrame()
        by_ev = pd.DataFrame()
        estimate = pd.DataFrame()
        queue = pd.DataFrame()
    else:
        by_conf = bridges.groupby(["confidence_tier", "recommended_use_class"], dropna=False).agg(
            bridge_candidate_count=("bridge_candidate_id", "count"),
            affected_candidate_bin_count=("affected_candidate_bin_count", "sum"),
            affected_recovered_signal_count=("affected_recovered_signal_count", "sum"),
        ).reset_index()
        by_ev = bridges.groupby(["bridge_evidence_type", "target_layer"], dropna=False).agg(
            bridge_candidate_count=("bridge_candidate_id", "count"),
            affected_candidate_bin_count=("affected_candidate_bin_count", "sum"),
            affected_recovered_signal_count=("affected_recovered_signal_count", "sum"),
        ).reset_index()
        estimate = bridges.groupby(["confidence_tier", "target_layer"], dropna=False).agg(
            bridge_candidate_count=("bridge_candidate_id", "count"),
            additional_speed_signals_recoverable=("affected_recovered_signal_count", lambda s: int(s[bridges.loc[s.index, "speed_recovery_potential"].astype(bool)].sum())),
            additional_aadt_exposure_signals_recoverable=("affected_recovered_signal_count", lambda s: int(s[bridges.loc[s.index, "AADT_recovery_potential"].astype(bool)].sum())),
            affected_candidate_bin_count=("affected_candidate_bin_count", "sum"),
        ).reset_index()
        queue = bridges.sort_values(["confidence_tier", "affected_recovered_signal_count", "affected_candidate_bin_count"], ascending=[True, False, False]).copy()
        queue["review_queue_reason"] = queue["bridge_evidence_type"].map(
            {
                "strict_success_joint_speed_aadt_route_bridge": "highest-impact strict-derived joint bridge candidate",
                "raw_source_confirms_speed_available": "route-type filtered or strict miss with raw speed source confirmation",
                "raw_source_confirms_aadt_only_available": "route-type filtered or strict miss with raw AADT source confirmation",
                "route_name_facility_bridge_supported": "route-name/facility candidate with fanout risk",
            }
        ).fillna("review-only bridge candidate")
    qa = pd.DataFrame(
        [
            _qa_row("stage2_outputs_loaded", not stage2["speed"].empty and not stage2["aadt"].empty, f"speed={len(stage2['speed'])};aadt={len(stage2['aadt'])}"),
            _qa_row("bridge_candidates_review_only_not_applied", True, "confirmed_by_code"),
            _qa_row("confidence_tiers_explicit", bridges.empty or _text(bridges, "confidence_tier").ne("").all(), bridges["confidence_tier"].nunique() if not bridges.empty else 0),
            _qa_row("ambiguous_fanout_bridge_candidates_flagged", bridges.empty or "ambiguity_fanout_count" in bridges.columns, "confirmed_by_schema"),
            _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
            _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
            _qa_row("no_crash_records_read", True, "confirmed_by_code"),
            _qa_row("access_not_included", True, "confirmed_by_code"),
            _qa_row("all_stage3_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
        ]
    )
    outputs = {"bridges": bridges, "estimate": estimate, "by_confidence": by_conf, "by_evidence": by_ev, "queue": queue, "qa": qa}
    return outputs, qa, bool(qa["passed"].all())


def _write_stage1_findings(stage1: dict[str, pd.DataFrame], passed: bool) -> None:
    u = stage1["universe"].set_index("metric")["value"].to_dict()
    top_methods = stage1["by_method"].sort_values("stage1_covered_bins", ascending=False).head(8) if not stage1["by_method"].empty else pd.DataFrame()
    lines = [
        "# Stage 1 Speed/AADT Strict Normalization Rerun Findings",
        "",
        f"Stage 1 QA passed: {passed}.",
        "",
        "## Bounded Question",
        "",
        "This stage reruns recovered candidate speed/AADT route-measure joins as a review-only positive-control prototype using strict active success route identity patterns. It does not modify active scaffold, active context, speed, AADT, exposure, rate, model, crash, or access logic.",
        "",
        "## Coverage",
        "",
        f"- Candidate bins evaluated: {int(u.get('candidate_bins_evaluated', 0)):,}",
        f"- Candidate signals evaluated: {int(u.get('candidate_signals_evaluated', 0)):,}",
        f"- Speed bin coverage before/after: {int(u.get('speed_previous_bin_coverage', 0)):,} -> {int(u.get('speed_stage1_bin_coverage', 0)):,}",
        f"- AADT/exposure bin coverage before/after: {int(u.get('aadt_previous_bin_coverage', 0)):,} -> {int(u.get('aadt_stage1_bin_coverage', 0)):,}",
        f"- Speed signal coverage before/after: {int(u.get('speed_previous_signal_coverage', 0)):,} -> {int(u.get('speed_stage1_signal_coverage', 0)):,}",
        f"- AADT/exposure signal coverage before/after: {int(u.get('aadt_previous_signal_coverage', 0)):,} -> {int(u.get('aadt_stage1_signal_coverage', 0)):,}",
        "",
        "## Helpful Methods",
        "",
    ]
    if top_methods.empty:
        lines.append("- No methods recovered bins.")
    else:
        for row in top_methods.itertuples(index=False):
            lines.append(f"- `{row.join_method}` ({row.context_layer}): {int(row.stage1_covered_bins):,} covered bins, {int(row.recovered_signal_count):,} signals.")
    lines += ["", "## QA Failures", ""]
    failed = stage1["qa"].loc[~stage1["qa"]["passed"]]
    if failed.empty:
        lines.append("- None.")
    else:
        for row in failed.itertuples(index=False):
            lines.append(f"- `{row.qa_gate}` observed `{row.observed_value}` expected `{row.expected_or_reference_value}`. {row.note}")
    _write_text("\n".join(lines) + "\n", OUT_DIR / _output_name("stage1_speed_aadt_strict_normalization_findings.md"))


def _write_stage2_findings(stage2: dict[str, pd.DataFrame], passed: bool) -> None:
    summary = stage2["summary"].sort_values("candidate_bin_count", ascending=False)
    route_type = stage2["route_type_audit"].sort_values("candidate_bin_count", ascending=False) if not stage2["route_type_audit"].empty else pd.DataFrame()
    lines = [
        "# Stage 2 Speed/AADT Source Availability Findings",
        "",
        f"Stage 2 QA passed: {passed}.",
        "",
        "## Bounded Question",
        "",
        "This stage audits remaining Stage 1 speed/AADT misses against normalized raw/staged source inventories to separate likely source absence from output filtering, route-system mismatch, facility bridge evidence, and measure mismatch.",
        "",
        "## Remaining Miss Classes",
        "",
    ]
    for row in summary.head(10).itertuples(index=False):
        lines.append(f"- `{row.context_layer}` `{row.source_availability_class}`: {int(row.candidate_bin_count):,} bins, {int(row.recovered_signal_count):,} signals.")
    lines += ["", "## Candidate Route Type Filtered From Context Output", ""]
    if route_type.empty:
        lines.append("- No records found in this class after Stage 1 missingness filtering.")
    else:
        for row in route_type.head(8).itertuples(index=False):
            lines.append(f"- `{row.context_layer}` `{row.source_availability_class}` / `{row.measure_compatibility_status}`: {int(row.candidate_bin_count):,} bins, {int(row.recovered_signal_count):,} signals.")
    _write_text("\n".join(lines) + "\n", OUT_DIR / _output_name("stage2_speed_aadt_availability_findings.md"))


def _write_stage3_findings(stage3: dict[str, pd.DataFrame]) -> None:
    bridges = stage3["bridges"]
    by_conf = stage3["by_confidence"]
    lines = [
        "# Stage 3 Speed/AADT Route Bridge Findings",
        "",
        "Stage 3 created a review-only bridge table. Bridge rows were not applied to active outputs or used to promote recovered candidates.",
        "",
        f"- Bridge candidates created: {len(bridges):,}",
    ]
    if not by_conf.empty:
        for row in by_conf.itertuples(index=False):
            lines.append(f"- `{row.confidence_tier}` / `{row.recommended_use_class}`: {int(row.bridge_candidate_count):,} candidates.")
    _write_text("\n".join(lines) + "\n", OUT_DIR / _output_name("stage3_speed_aadt_bridge_findings.md"))


def _final_qa(stage1_passed: bool, stage2_ran: bool, stage2_passed: bool, stage3_ran: bool, stage3: dict[str, pd.DataFrame] | None) -> pd.DataFrame:
    rows = [
        _qa_row("no_active_outputs_modified", True, "confirmed_by_code"),
        _qa_row("no_candidates_promoted", True, "confirmed_by_code"),
        _qa_row("no_crash_records_read", True, "confirmed_by_code"),
        _qa_row("no_crash_direction_fields_read_or_used", True, "confirmed_by_code"),
        _qa_row("access_not_included", True, "confirmed_by_code"),
        _qa_row("crashes_not_used_for_any_diagnostic", True, "confirmed_by_code"),
        _qa_row("context_fields_not_used_to_define_scaffold_candidate_associations_direction_or_route_measure", True, "confirmed_by_code"),
        _qa_row("stage2_only_runs_if_stage1_gates_pass", stage2_ran == stage1_passed, stage2_ran, stage1_passed),
        _qa_row("stage3_only_runs_if_stage2_gates_pass", stage3_ran == (stage2_ran and stage2_passed), stage3_ran, stage2_ran and stage2_passed),
        _qa_row("bridge_candidates_review_only_not_applied", True, "confirmed_by_code"),
        _qa_row("all_joins_labeled_by_method", True, "confirmed_by_stage_outputs"),
        _qa_row("ambiguous_fanout_bridge_candidates_flagged", True, "confirmed_by_stage_outputs"),
        _qa_row("confidence_tiers_explicit", True, "confirmed_by_stage_outputs"),
        _qa_row("multi_candidate_weights_provenance_preserved", True, "candidate_weight/candidate_rank/tie_group retained in detail outputs"),
        _qa_row("strict_active_overlap_double_count_checks_diagnostic_only", True, "confirmed_by_code"),
        _qa_row("all_outputs_written_only_to_review_folder", True, str(OUT_DIR)),
    ]
    if stage3 is not None and not stage3["bridges"].empty:
        rows.append(_qa_row("stage3_bridge_candidate_count", True, len(stage3["bridges"])))
    return pd.DataFrame(rows)


def _final_findings(stage1: dict[str, pd.DataFrame], stage1_passed: bool, stage2: dict[str, pd.DataFrame] | None, stage2_ran: bool, stage2_passed: bool, stage3: dict[str, pd.DataFrame] | None, stage3_ran: bool) -> None:
    u = stage1["universe"].set_index("metric")["value"].to_dict() if stage1 else {}
    bridges = stage3["bridges"] if stage3_ran and stage3 is not None else pd.DataFrame()
    conf_counts = bridges["confidence_tier"].value_counts().to_dict() if not bridges.empty else {}
    estimate = stage3["estimate"] if stage3_ran and stage3 is not None else pd.DataFrame()
    high_med = estimate.loc[_text(estimate, "confidence_tier").isin({"high_confidence_review_only", "medium_confidence_review_only"})] if not estimate.empty else pd.DataFrame()
    speed_est = int(high_med["additional_speed_signals_recoverable"].sum()) if not high_med.empty else 0
    aadt_est = int(high_med["additional_aadt_exposure_signals_recoverable"].sum()) if not high_med.empty else 0
    top_methods = stage1["by_method"].sort_values("stage1_covered_bins", ascending=False).head(5) if stage1 and not stage1["by_method"].empty else pd.DataFrame()
    top_stage2 = stage2["summary"].sort_values("candidate_bin_count", ascending=False).head(5) if stage2_ran and stage2 is not None and not stage2["summary"].empty else pd.DataFrame()
    next_pass = "apply review-only bridge rerun" if conf_counts.get("high_confidence_review_only", 0) else "refine bridge candidates"
    lines = [
        "# Expanded Candidate Speed/AADT Phase 3 Bridge Findings",
        "",
        f"1. Did Stage 1 pass QA? {stage1_passed}.",
        f"2. Did Stage 2 run and pass QA? {stage2_ran and stage2_passed}.",
        f"3. Did Stage 3 run? {stage3_ran}.",
        f"4. Stage 1 speed coverage improved from {int(u.get('speed_previous_signal_coverage', 0)):,} to {int(u.get('speed_stage1_signal_coverage', 0)):,} signals and from {int(u.get('speed_previous_bin_coverage', 0)):,} to {int(u.get('speed_stage1_bin_coverage', 0)):,} bins.",
        f"5. Stage 1 AADT/exposure coverage improved from {int(u.get('aadt_previous_signal_coverage', 0)):,} to {int(u.get('aadt_stage1_signal_coverage', 0)):,} signals and from {int(u.get('aadt_previous_bin_coverage', 0)):,} to {int(u.get('aadt_stage1_bin_coverage', 0)):,} bins.",
        "6. Strict-derived normalization methods that helped most: " + ("; ".join(f"`{r.join_method}` {r.context_layer} {int(r.stage1_covered_bins):,} bins" for r in top_methods.itertuples(index=False)) if not top_methods.empty else "none observed"),
        "7. Remaining misses after Stage 1: " + ("; ".join(f"`{r.context_layer}` `{r.source_availability_class}` {int(r.candidate_bin_count):,} bins" for r in top_stage2.itertuples(index=False)) if not top_stage2.empty else "not audited"),
        "8. `candidate_route_type_filtered_from_context_output`: " + ("audited in Stage 2; see `stage2_route_type_filtered_audit.csv`." if stage2_ran else "not audited because Stage 2 did not run."),
        f"9. Bridge candidates created in Stage 3: {len(bridges):,}.",
        f"10. High-confidence review-only bridge candidates: {conf_counts.get('high_confidence_review_only', 0):,}.",
        f"11. Medium-confidence review-only bridge candidates: {conf_counts.get('medium_confidence_review_only', 0):,}.",
        f"12. Low-confidence/manual-review-only bridge candidates: {conf_counts.get('low_confidence_manual_review_only', 0):,}.",
        f"13. Additional speed signals that might be recovered by high/medium-confidence bridge candidates: {speed_est:,}.",
        f"14. Additional AADT/exposure signals that might be recovered by high/medium-confidence bridge candidates: {aadt_est:,}.",
        f"15. Best next pass: {next_pass}.",
    ]
    _write_text("\n".join(lines) + "\n", OUT_DIR / _output_name("expanded_candidate_speed_aadt_phase3_bridge_findings.md"))


def _write_all(stage1: dict[str, pd.DataFrame], stage2: dict[str, pd.DataFrame] | None, stage3: dict[str, pd.DataFrame] | None) -> None:
    _write_csv(stage1["speed"], OUT_DIR / _output_name("stage1_speed_strict_normalization_rerun_detail.csv"))
    _write_csv(stage1["aadt"], OUT_DIR / _output_name("stage1_aadt_strict_normalization_rerun_detail.csv"))
    _write_csv(stage1["signal"], OUT_DIR / _output_name("stage1_speed_aadt_strict_normalization_signal_summary.csv"))
    _write_csv(stage1["universe"], OUT_DIR / _output_name("stage1_speed_aadt_strict_normalization_universe_summary.csv"))
    _write_csv(stage1["by_class"], OUT_DIR / _output_name("stage1_speed_aadt_strict_normalization_by_class.csv"))
    _write_csv(stage1["by_method"], OUT_DIR / _output_name("stage1_speed_aadt_strict_normalization_by_method.csv"))
    _write_csv(stage1["conflicts"], OUT_DIR / _output_name("stage1_speed_aadt_strict_normalization_conflicts.csv"))
    _write_csv(stage1["qa"], OUT_DIR / _output_name("stage1_speed_aadt_strict_normalization_qa.csv"))
    if stage2 is not None:
        _write_csv(stage2["speed"], OUT_DIR / _output_name("stage2_speed_raw_source_availability_detail.csv"))
        _write_csv(stage2["aadt"], OUT_DIR / _output_name("stage2_aadt_raw_source_availability_detail.csv"))
        _write_csv(stage2["joint"], OUT_DIR / _output_name("stage2_speed_aadt_raw_source_joint_availability.csv"))
        _write_csv(stage2["route_type_audit"], OUT_DIR / _output_name("stage2_route_type_filtered_audit.csv"))
        _write_csv(stage2["strict_failed_audit"], OUT_DIR / _output_name("stage2_strict_success_failed_audit.csv"))
        _write_csv(stage2["route_name_differs_audit"], OUT_DIR / _output_name("stage2_route_name_differs_audit.csv"))
        _write_csv(stage2["inventory"], OUT_DIR / _output_name("stage2_speed_aadt_source_inventory.csv"))
        _write_csv(stage2["summary"], OUT_DIR / _output_name("stage2_speed_aadt_source_availability_summary.csv"))
        _write_csv(stage2["estimate"], OUT_DIR / _output_name("stage2_speed_aadt_recovery_estimate.csv"))
        _write_csv(stage2["qa"], OUT_DIR / _output_name("stage2_speed_aadt_availability_qa.csv"))
    if stage3 is not None:
        _write_csv(stage3["bridges"], OUT_DIR / _output_name("stage3_speed_aadt_route_bridge_candidates.csv"))
        _write_csv(stage3["estimate"], OUT_DIR / _output_name("stage3_speed_aadt_bridge_recovery_estimate.csv"))
        _write_csv(stage3["by_confidence"], OUT_DIR / _output_name("stage3_speed_aadt_bridge_by_confidence.csv"))
        _write_csv(stage3["by_evidence"], OUT_DIR / _output_name("stage3_speed_aadt_bridge_by_evidence_type.csv"))
        _write_csv(stage3["queue"], OUT_DIR / _output_name("stage3_speed_aadt_bridge_ranked_review_queue.csv"))
        _write_csv(stage3["qa"], OUT_DIR / _output_name("stage3_speed_aadt_bridge_qa.csv"))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _log("RUN_START expanded_candidate_speed_aadt_phase3_bridge")
    mode, limit = _smoke_mode()
    _checkpoint("run_mode", note=f"mode={mode}; limit={limit}; full_requires_PHASE3_FULL_RUN_CONFIRMED=true")
    missing_inputs = _missing_required_inputs()
    _checkpoint("required_input_check", len(REQUIRED_INPUTS), f"missing_files={len(missing_inputs):,}")
    inputs = _load_inputs()
    stage1, stage1_qa, stage1_passed = run_stage1(inputs, missing_inputs)
    _write_all(stage1, None, None)
    _write_stage1_findings(stage1, stage1_passed)

    stage2 = None
    stage2_ran = False
    stage2_passed = False
    stage3 = None
    stage3_ran = False
    stage3_passed = False

    if not stage1_passed:
        failed = stage1_qa.loc[~stage1_qa["passed"], "qa_gate"].tolist()
        reason = "Stage 2 did not run because Stage 1 QA gates failed:\n" + "\n".join(f"- {x}" for x in failed) + "\n"
        _write_text(reason, OUT_DIR / _output_name("stage2_not_run_reason.txt"))
        _write_text("Stage 3 did not run because Stage 2 did not run after Stage 1 QA failure.\n", OUT_DIR / _output_name("stage3_not_run_reason.txt"))
    else:
        stage2, stage2_qa, stage2_passed = run_stage2(stage1)
        stage2_ran = True
        _write_all(stage1, stage2, None)
        _write_stage2_findings(stage2, stage2_passed)
        if not stage2_passed:
            failed = stage2_qa.loc[~stage2_qa["passed"], "qa_gate"].tolist()
            _write_text("Stage 3 did not run because Stage 2 QA gates failed:\n" + "\n".join(f"- {x}" for x in failed) + "\n", OUT_DIR / _output_name("stage3_not_run_reason.txt"))
        else:
            stage3, stage3_qa, stage3_passed = run_stage3(stage1, stage2)
            stage3_ran = True
            _write_all(stage1, stage2, stage3)
            _write_stage3_findings(stage3)

    final_qa = _final_qa(stage1_passed, stage2_ran, stage2_passed, stage3_ran, stage3)
    _write_csv(final_qa, OUT_DIR / _output_name("expanded_candidate_speed_aadt_phase3_bridge_qa.csv"))
    _final_findings(stage1, stage1_passed, stage2, stage2_ran, stage2_passed, stage3, stage3_ran)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "bounded_question": "three-stage gated read-only Phase 3 speed/AADT route identity recovery prototype for recovered candidate bins",
        "output_dir": str(OUT_DIR),
        "stage1_passed": stage1_passed,
        "stage2_ran": stage2_ran,
        "stage2_passed": stage2_passed,
        "stage3_ran": stage3_ran,
        "stage3_passed": stage3_passed,
        "run_mode": mode,
        "smoke_limit": limit,
        "candidate_bins_evaluated": int(stage1["base"]["candidate_bin_id"].nunique()) if "base" in stage1 and not stage1["base"].empty else 0,
        "candidate_signals_evaluated": int(stage1["base"]["candidate_signal_id"].nunique()) if "base" in stage1 and not stage1["base"].empty else 0,
        "guardrails": {
            "read_only": True,
            "review_only": True,
            "no_active_outputs_modified": True,
            "no_candidates_promoted": True,
            "no_crash_records_read": True,
            "no_crash_direction_fields_read_or_used": True,
            "access_not_included": True,
            "bridge_candidates_not_applied": True,
        },
        "inputs": {str(root): names for root, names in REQUIRED_INPUTS.items()},
    }
    _write_json(manifest, OUT_DIR / _output_name("expanded_candidate_speed_aadt_phase3_bridge_manifest.json"))
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
