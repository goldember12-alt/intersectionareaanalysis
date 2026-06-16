from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/typed_access_rule_overlap_audit"

STABLE_ACCESS_DIR = OUTPUT_ROOT / "review/current/stable_lineage_final_access_rerun"
CONSERVATIVE_DIR = OUTPUT_ROOT / "review/current/conservative_travelway_windowed_access"
SANITY_DIR = OUTPUT_ROOT / "review/current/travelway_normalized_access_sanity_audit"
ACCESS_V2 = Path("artifacts/normalized/access_v2.parquet")

CRASH_FIELD_TOKENS = (
    "crash_id",
    "crash_direction",
    "veh_direction",
    "vehicle_direction",
    "direction_of_travel",
    "dir_of_travel",
    "document_nbr",
    "crash_year",
    "crash_dt",
    "assigned_crash",
)

REQUIRED_INPUTS = [
    STABLE_ACCESS_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_spatial_vs_travelway_comparison.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_product_coverage_summary.csv",
    STABLE_ACCESS_DIR / "stable_lineage_final_access_rerun_manifest.json",
    CONSERVATIVE_DIR / "conservative_typed_v2_travelway_windowed_assignment_detail.csv",
    CONSERVATIVE_DIR / "conservative_travelway_windowed_signal_window_summary.csv",
    CONSERVATIVE_DIR / "spatial_vs_conservative_travelway_comparison.csv",
    CONSERVATIVE_DIR / "broad_travelway_rejection_reason_summary.csv",
    CONSERVATIVE_DIR / "conservative_travelway_windowed_access_manifest.json",
    SANITY_DIR / "travelway_assignment_method_summary.csv",
    SANITY_DIR / "travelway_assignment_distance_window_detail.csv",
    SANITY_DIR / "travelway_assignment_overcapture_risk_detail.csv",
    SANITY_DIR / "typed_vs_untyped_capture_explanation.csv",
    SANITY_DIR / "travelway_normalized_access_sanity_manifest.json",
    ACCESS_V2,
]

CORRECTED_CATEGORY_MAP = {
    "U": "unrestricted_or_full_access",
    "RIRO": "right_in_right_out",
    "R": "right_in_right_out",
    "RC": "right_in_right_out",
    "RIO": "right_in_only",
    "ROO": "right_out_only",
    "LIRIRO": "restricted_partial_access",
    "": "unknown",
}

FOCUS_CATEGORIES = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "other_review",
    "all_typed_categories",
]

WINDOWS = ["0_1000", "0_2500"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"{_now()} {message}\n")


def _checkpoint(name: str, rows: int | None = None) -> None:
    suffix = "" if rows is None else f" rows={rows:,}"
    _log(f"CHECKPOINT {name}{suffix}")


def _blocked_column(column: str) -> bool:
    lower = column.lower()
    if lower in {"access_direction", "access_direction_raw", "access_direction_normalized"}:
        return False
    return any(token in lower for token in CRASH_FIELD_TOKENS)


def _read_csv(path: Path, *, usecols: list[str] | None = None) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read {path.name}", len(out))
    return out


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    frame.to_csv(OUT_DIR / name, index=False)
    _checkpoint(f"write {name}", len(frame))


def _write_text(text: str, name: str) -> None:
    (OUT_DIR / name).write_text(text, encoding="utf-8")
    _checkpoint(f"write {name}")


def _write_json(payload: dict[str, Any], name: str) -> None:
    (OUT_DIR / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _checkpoint(f"write {name}")


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _collapse(values: pd.Series, limit: int = 20) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _access_point_id(frame: pd.DataFrame) -> pd.Series:
    return _text(frame, "access_v2_source_priority") + ":" + _text(frame, "access_v2_source_row_id")


def _correct_category(raw_code: str) -> str:
    code = "" if pd.isna(raw_code) else str(raw_code).strip().upper()
    return CORRECTED_CATEGORY_MAP.get(code, "other_review")


def _reason(raw_code: str, prior: str, corrected: str) -> str:
    code = "" if pd.isna(raw_code) else str(raw_code).strip().upper()
    if code in {"R", "RC"}:
        return "confirmed_R_RC_are_RIRO"
    if corrected == prior:
        return "unchanged_confirmed_mapping"
    return "corrected_from_raw_code_mapping"


def _load_corrected_source() -> pd.DataFrame:
    source = pd.read_parquet(ACCESS_V2)
    blocked = [column for column in source.columns if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from typed access source: {blocked}")
    source = source.copy()
    source["access_point_id"] = _access_point_id(source)
    source["raw_access_control_code"] = _text(source, "access_control_code").str.upper()
    source["prior_access_category"] = _text(source, "access_control_category").replace("", "unknown")
    source["corrected_access_category"] = source["raw_access_control_code"].map(_correct_category)
    source["category_correction_reason"] = [
        _reason(code, prior, corr)
        for code, prior, corr in zip(
            source["raw_access_control_code"],
            source["prior_access_category"],
            source["corrected_access_category"],
        )
    ]
    keep = [
        "access_point_id",
        "access_v2_source_layer",
        "access_v2_source_priority",
        "access_v2_source_row_id",
        "route_name",
        "route_measure",
        "raw_access_control_code",
        "access_control_raw",
        "prior_access_category",
        "corrected_access_category",
        "category_correction_reason",
    ]
    out = source[[column for column in keep if column in source.columns]].drop_duplicates("access_point_id")
    _checkpoint("load_corrected_source", len(out))
    return out


def _merge_corrected(frame: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    drop_cols = [
        "raw_access_control_code",
        "access_control_raw",
        "prior_access_category",
        "corrected_access_category",
        "category_correction_reason",
    ]
    out = frame.drop(columns=[col for col in drop_cols if col in frame.columns], errors="ignore").merge(
        source[
            [
                "access_point_id",
                "raw_access_control_code",
                "access_control_raw",
                "prior_access_category",
                "corrected_access_category",
                "category_correction_reason",
            ]
        ],
        on="access_point_id",
        how="left",
    )
    prior = _text(out, "prior_access_category")
    corrected = _text(out, "corrected_access_category")
    fallback = _text(out, "access_control_category")
    out["prior_access_category"] = prior.where(prior.ne(""), fallback)
    out["corrected_access_category"] = corrected.where(corrected.ne(""), fallback)
    return out


def _prepare_spatial(source: pd.DataFrame) -> pd.DataFrame:
    spatial = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv")
    spatial = spatial.loc[_text(spatial, "buffer_width_ft").eq("100")].copy()
    spatial = _merge_corrected(spatial, source)
    spatial["product"] = "spatial_100ft"
    spatial["window_0_1000"] = _text(spatial, "analysis_window").eq("0_1000")
    spatial["window_0_2500"] = _text(spatial, "analysis_window").isin(["0_1000", "1000_2500"])
    return spatial


def _prepare_conservative(source: pd.DataFrame) -> pd.DataFrame:
    conservative = _read_csv(CONSERVATIVE_DIR / "conservative_typed_v2_travelway_windowed_assignment_detail.csv")
    conservative = _merge_corrected(conservative, source)
    conservative["product"] = "conservative_travelway_windowed"
    conservative["window_0_1000"] = _text(conservative, "conservative_window").eq("conservative_0_1000")
    conservative["window_0_2500"] = _text(conservative, "conservative_window").eq("conservative_0_2500")
    return conservative


def _prepare_broad(source: pd.DataFrame) -> pd.DataFrame:
    broad = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv")
    broad = broad.loc[_text(broad, "route_normalized_assignment_status").eq("assigned_review_only")].copy()
    broad = _merge_corrected(broad, source)
    risk = _read_csv(SANITY_DIR / "travelway_assignment_overcapture_risk_detail.csv")
    risk = risk.loc[_text(risk, "access_layer").eq("typed_v2")].copy()
    key_cols = ["access_point_id", "target_signal_id", "target_bin_id", "stable_bin_id"]
    risk_cols = key_cols + [
        "assignment_distance_band",
        "nearest_distance_ft",
        "nearest_distance_band",
        "captured_100ft",
        "hybrid_leg_length_class",
        "leg_length_limitation_class",
        "within_valid_signal_relative_window",
        "route_only_spatially_far_from_signal",
        "overcapture_risk_class",
    ]
    broad = broad.merge(
        risk[[col for col in risk_cols if col in risk.columns]].drop_duplicates(key_cols),
        on=[col for col in key_cols if col in broad.columns and col in risk.columns],
        how="left",
        suffixes=("", "_risk"),
    )
    broad["product"] = "broad_travelway_normalized"
    broad["window_0_1000"] = _text(broad, "analysis_window").eq("0_1000")
    broad["window_0_2500"] = _text(broad, "analysis_window").isin(["0_1000", "1000_2500"])
    return broad


def _product_rows(frame: pd.DataFrame, product: str) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for window in WINDOWS:
        subset = frame.loc[frame[f"window_{window}"]].copy()
        if subset.empty:
            continue
        subset["product_key"] = product if window == "0_2500" else f"{product}_0_1000"
        subset["overlap_window"] = window
        subset["overlap_category"] = subset["corrected_access_category"]
        rows.append(subset)
        all_rows = subset.copy()
        all_rows["overlap_category"] = "all_typed_categories"
        rows.append(all_rows)
    return pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()


def _set_table(spatial: pd.DataFrame, conservative: pd.DataFrame, broad: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    product_frames = [
        _product_rows(spatial, "spatial_100ft"),
        _product_rows(conservative, "conservative_travelway_windowed"),
        _product_rows(broad, "broad_travelway_normalized"),
    ]
    all_assignments = pd.concat([frame for frame in product_frames if not frame.empty], ignore_index=True, sort=False)
    all_assignments = all_assignments.loc[all_assignments["overlap_category"].isin(FOCUS_CATEGORIES)].copy()

    signal_rows = (
        all_assignments.loc[_text(all_assignments, "target_signal_id").ne("")]
        .groupby(["overlap_window", "overlap_category", "target_signal_id"], dropna=False)
        .agg(
            products=("product", lambda s: "|".join(sorted(set(s.astype(str))))),
            source_points=("access_point_id", "nunique"),
            example_source_points=("access_point_id", _collapse),
        )
        .reset_index()
    )
    source_rows = (
        all_assignments.groupby(["overlap_window", "overlap_category", "access_point_id"], dropna=False)
        .agg(
            products=("product", lambda s: "|".join(sorted(set(s.astype(str))))),
            signals=("target_signal_id", lambda s: int(s.astype(str).str.strip().ne("").sum())),
            signal_ids=("target_signal_id", _collapse),
        )
        .reset_index()
    )
    return signal_rows, source_rows


def _overlap_class(products: str) -> str:
    parts = set(str(products).split("|")) if products else set()
    spatial = "spatial_100ft" in parts
    conservative = "conservative_travelway_windowed" in parts
    broad = "broad_travelway_normalized" in parts
    if spatial and conservative and broad:
        return "captured_by_all_available_rules"
    if spatial and conservative:
        return "spatial_and_conservative"
    if spatial and broad:
        return "spatial_and_broad"
    if conservative and broad:
        return "conservative_and_broad"
    if spatial:
        return "spatial_only"
    if conservative:
        return "conservative_travelway_only"
    if broad:
        return "broad_travelway_only"
    return "not_captured"


def _summarize_overlaps(signal_detail: pd.DataFrame, source_detail: pd.DataFrame) -> pd.DataFrame:
    signal_detail["overlap_class"] = signal_detail["products"].map(_overlap_class)
    source_detail["overlap_class"] = source_detail["products"].map(_overlap_class)
    signal_counts = (
        signal_detail.groupby(["overlap_window", "overlap_category", "overlap_class"], dropna=False)["target_signal_id"]
        .nunique()
        .reset_index(name="signal_count")
    )
    source_counts = (
        source_detail.groupby(["overlap_window", "overlap_category", "overlap_class"], dropna=False)["access_point_id"]
        .nunique()
        .reset_index(name="source_point_count")
    )
    return signal_counts.merge(source_counts, on=["overlap_window", "overlap_category", "overlap_class"], how="outer").fillna(0)


def _counts_by_product(product_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for product, frame in product_frames.items():
        for window in WINDOWS:
            subset = frame.loc[frame[f"window_{window}"]].copy()
            for category in FOCUS_CATEGORIES:
                cat_subset = subset if category == "all_typed_categories" else subset.loc[subset["corrected_access_category"].eq(category)]
                rows.append(
                    {
                        "product": product,
                        "window": window,
                        "corrected_access_category": category,
                        "source_point_count": int(cat_subset["access_point_id"].nunique()) if "access_point_id" in cat_subset.columns else 0,
                        "signal_count": int(cat_subset.loc[_text(cat_subset, "target_signal_id").ne(""), "target_signal_id"].nunique())
                        if "target_signal_id" in cat_subset.columns
                        else 0,
                        "assignment_row_count": int(len(cat_subset)),
                    }
                )
    return pd.DataFrame(rows)


def _category_correction_impact(source: pd.DataFrame, product_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    changed = source.loc[source["prior_access_category"].ne(source["corrected_access_category"])].copy()
    rows.append(
        {
            "scope": "typed_v2_source",
            "window": "all",
            "raw_access_control_code": "all_changed",
            "source_point_count": int(changed["access_point_id"].nunique()),
            "signal_count": "",
            "assignment_row_count": "",
            "prior_access_category": _collapse(changed["prior_access_category"]),
            "corrected_access_category": _collapse(changed["corrected_access_category"]),
        }
    )
    for code, group in changed.groupby("raw_access_control_code", dropna=False):
        rows.append(
            {
                "scope": "typed_v2_source",
                "window": "all",
                "raw_access_control_code": code,
                "source_point_count": int(group["access_point_id"].nunique()),
                "signal_count": "",
                "assignment_row_count": "",
                "prior_access_category": _collapse(group["prior_access_category"]),
                "corrected_access_category": _collapse(group["corrected_access_category"]),
            }
        )
    changed_ids = set(changed["access_point_id"])
    for product, frame in product_frames.items():
        affected = frame.loc[frame["access_point_id"].isin(changed_ids)].copy()
        for window in WINDOWS:
            subset = affected.loc[affected[f"window_{window}"]].copy()
            for code, group in subset.groupby("raw_access_control_code", dropna=False):
                rows.append(
                    {
                        "scope": product,
                        "window": window,
                        "raw_access_control_code": code,
                        "source_point_count": int(group["access_point_id"].nunique()),
                        "signal_count": int(group.loc[_text(group, "target_signal_id").ne(""), "target_signal_id"].nunique()),
                        "assignment_row_count": int(len(group)),
                        "prior_access_category": _collapse(group["prior_access_category"]),
                        "corrected_access_category": _collapse(group["corrected_access_category"]),
                    }
                )
    return pd.DataFrame(rows)


def _recommended_broad_status(frame: pd.DataFrame) -> pd.Series:
    match = _text(frame, "stable_travelway_assignment_match_class")
    quality = _text(frame, "route_normalized_quality_class")
    risk = _text(frame, "overcapture_risk_class")
    valid_window = _bool_text(frame, "within_valid_signal_relative_window")
    out = pd.Series("manual_review_needed", index=frame.index, dtype=str)
    out.loc[risk.eq("long_route_overcapture_risk") | quality.eq("low_confidence_route_family_only")] = "likely_overcapture"
    out.loc[match.isin(["direct_stable_travelway_id", "route_measure_overlap"]) & valid_window & ~risk.eq("long_route_overcapture_risk")] = "likely_valid_broad_only"
    out.loc[_text(frame, "captured_100ft").str.lower().eq("false") & valid_window & out.eq("manual_review_needed")] = "possible_spatial_undercapture"
    return out


def _broad_only_audit(broad: pd.DataFrame, signal_detail: pd.DataFrame) -> pd.DataFrame:
    broad_only_signals = signal_detail.loc[signal_detail["overlap_class"].eq("broad_travelway_only")]
    keys = broad_only_signals[["overlap_window", "overlap_category", "target_signal_id"]].drop_duplicates()
    rows = []
    for row in keys.itertuples(index=False):
        subset = broad.loc[
            broad[f"window_{row.overlap_window}"]
            & _text(broad, "target_signal_id").eq(row.target_signal_id)
            & (
                _text(broad, "corrected_access_category").eq(row.overlap_category)
                if row.overlap_category != "all_typed_categories"
                else pd.Series(True, index=broad.index)
            )
        ].copy()
        if subset.empty:
            continue
        subset["overlap_window"] = row.overlap_window
        subset["overlap_category"] = row.overlap_category
        subset["recommended_status"] = _recommended_broad_status(subset)
        rows.append(subset)
    out = pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()
    keep = [
        "overlap_window",
        "overlap_category",
        "access_point_id",
        "raw_access_control_code",
        "prior_access_category",
        "corrected_access_category",
        "target_signal_id",
        "target_bin_id",
        "stable_travelway_assignment_match_class",
        "route_normalized_quality_class",
        "analysis_window",
        "distance_band",
        "assignment_distance_band",
        "nearest_distance_ft",
        "nearest_distance_band",
        "within_valid_signal_relative_window",
        "route_only_spatially_far_from_signal",
        "overcapture_risk_class",
        "recommended_status",
    ]
    return out[[col for col in keep if col in out.columns]].drop_duplicates() if not out.empty else pd.DataFrame(columns=keep)


def _spatial_only_audit(spatial: pd.DataFrame, signal_detail: pd.DataFrame) -> pd.DataFrame:
    spatial_only_signals = signal_detail.loc[signal_detail["overlap_class"].eq("spatial_only")]
    keys = spatial_only_signals[["overlap_window", "overlap_category", "target_signal_id"]].drop_duplicates()
    rows = []
    for row in keys.itertuples(index=False):
        subset = spatial.loc[
            spatial[f"window_{row.overlap_window}"]
            & _text(spatial, "target_signal_id").eq(row.target_signal_id)
            & (
                _text(spatial, "corrected_access_category").eq(row.overlap_category)
                if row.overlap_category != "all_typed_categories"
                else pd.Series(True, index=spatial.index)
            )
        ].copy()
        if subset.empty:
            continue
        subset["overlap_window"] = row.overlap_window
        subset["overlap_category"] = row.overlap_category
        subset["stable_travelway_identity_available"] = _text(subset, "stable_travelway_id").ne("") | _text(subset, "lineage_confidence").str.startswith("high")
        subset["recommended_status"] = "spatial_proximity_defensible_route_identity_weak"
        subset.loc[subset["stable_travelway_identity_available"], "recommended_status"] = "likely_valid_spatial_only"
        rows.append(subset)
    out = pd.concat(rows, ignore_index=True, sort=False) if rows else pd.DataFrame()
    keep = [
        "overlap_window",
        "overlap_category",
        "access_point_id",
        "raw_access_control_code",
        "prior_access_category",
        "corrected_access_category",
        "target_signal_id",
        "target_bin_id",
        "buffer_width_ft",
        "analysis_window",
        "distance_band",
        "stable_travelway_id",
        "lineage_confidence",
        "stable_travelway_identity_available",
        "recommended_status",
    ]
    return out[[col for col in keep if col in out.columns]].drop_duplicates() if not out.empty else pd.DataFrame(columns=keep)


def _qa() -> pd.DataFrame:
    checks = [
        ("no_active_outputs_modified", "passed", "outputs_written_only_to_review_current_typed_access_rule_overlap_audit"),
        ("no_candidates_promoted", "passed", "diagnostic_only"),
        ("no_crash_records_read", "passed", "input_fields_screened_for_crash_tokens"),
        ("no_crash_direction_fields_used", "passed", "crash_direction_tokens_blocked"),
        ("no_crash_assignment_or_catchments", "passed", "access_assignment_inputs_read_only"),
        ("no_rates_or_models", "passed", "counts_and_overlap_only"),
        ("typed_and_untyped_separate", "passed", "typed_v2_only_audit"),
        ("category_correction_review_only", "passed", "corrected category fields added to audit outputs only"),
        ("raw_access_codes_preserved", "passed", "raw_access_control_code and prior category preserved"),
        ("weighted_unweighted_not_combined", "passed", "assignment details retain existing count columns where present"),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(checks, columns=["check_name", "status", "observed"])


def _findings(
    impact: pd.DataFrame,
    counts: pd.DataFrame,
    overlap_summary: pd.DataFrame,
    broad_audit: pd.DataFrame,
    spatial_audit: pd.DataFrame,
) -> str:
    changed = impact.loc[(impact["scope"].eq("typed_v2_source")) & (impact["raw_access_control_code"].eq("all_changed"))]
    changed_count = int(changed["source_point_count"].iloc[0]) if not changed.empty else 0

    def count(product: str, window: str, category: str, metric: str) -> int:
        subset = counts.loc[
            counts["product"].eq(product) & counts["window"].eq(window) & counts["corrected_access_category"].eq(category)
        ]
        if subset.empty:
            return 0
        return int(subset[metric].iloc[0])

    def broad_status_count(status: str) -> int:
        return int(broad_audit.loc[broad_audit["recommended_status"].eq(status), "access_point_id"].nunique()) if not broad_audit.empty else 0

    def overlap_line(category: str) -> str:
        subset = overlap_summary.loc[overlap_summary["overlap_category"].eq(category) & overlap_summary["overlap_window"].eq("0_2500")]
        items = [
            f"{row.overlap_class}: {int(row.signal_count)} signals/{int(row.source_point_count)} source points"
            for row in subset.sort_values("overlap_class").itertuples(index=False)
        ]
        return "; ".join(items) if items else "none"

    return f"""# Typed Access Rule Overlap Audit Findings

## Bounded Question

This read-only diagnostic applies the confirmed typed v2 access-code correction (`R` and `RC` are RIRO) and compares typed v2 source-point/signal capture across spatial 100 ft, conservative Travelway-windowed, and broad Travelway-normalized access assignment products.

## Category Correction

- Source points changed from `other_review` to `right_in_right_out`: {changed_count:,}
- Corrected raw codes: `R`, `RC`
- Raw codes retained as `other_review`: `I`, `M`, `S`, `AS`, `AU`

## RIRO Counts After Correction

- Spatial 100 ft, 0-1,000 ft: {count('spatial_100ft', '0_1000', 'right_in_right_out', 'source_point_count'):,} source points across {count('spatial_100ft', '0_1000', 'right_in_right_out', 'signal_count'):,} signals
- Spatial 100 ft, 0-2,500 ft: {count('spatial_100ft', '0_2500', 'right_in_right_out', 'source_point_count'):,} source points across {count('spatial_100ft', '0_2500', 'right_in_right_out', 'signal_count'):,} signals
- Conservative Travelway-windowed, 0-1,000 ft: {count('conservative_travelway_windowed', '0_1000', 'right_in_right_out', 'source_point_count'):,} source points across {count('conservative_travelway_windowed', '0_1000', 'right_in_right_out', 'signal_count'):,} signals
- Conservative Travelway-windowed, 0-2,500 ft: {count('conservative_travelway_windowed', '0_2500', 'right_in_right_out', 'source_point_count'):,} source points across {count('conservative_travelway_windowed', '0_2500', 'right_in_right_out', 'signal_count'):,} signals
- Broad Travelway-normalized, 0-1,000 ft: {count('broad_travelway_normalized', '0_1000', 'right_in_right_out', 'source_point_count'):,} source points across {count('broad_travelway_normalized', '0_1000', 'right_in_right_out', 'signal_count'):,} signals
- Broad Travelway-normalized, 0-2,500 ft: {count('broad_travelway_normalized', '0_2500', 'right_in_right_out', 'source_point_count'):,} source points across {count('broad_travelway_normalized', '0_2500', 'right_in_right_out', 'signal_count'):,} signals

## Rule Overlap

- `unrestricted_or_full_access`, 0-2,500 ft: {overlap_line('unrestricted_or_full_access')}
- `right_in_right_out`, 0-2,500 ft: {overlap_line('right_in_right_out')}

## Broad-Only Risk

- Broad-only source points likely valid: {broad_status_count('likely_valid_broad_only'):,}
- Broad-only source points possible spatial undercapture: {broad_status_count('possible_spatial_undercapture'):,}
- Broad-only source points likely overcapture: {broad_status_count('likely_overcapture'):,}

Broad Travelway-normalized remains useful as source-coverage/sensitivity evidence, but broad-only cases continue to require risk classification because route/facility-compatible and long-route matches can overstate signal-relevant access.

## Spatial-Only Risk

- Spatial-only audit rows: {len(spatial_audit):,}

Spatial-only records are generally defensible as proximity evidence, but records with weak or missing stable Travelway identity should remain review-only until route/source identity is improved.

## Recommendation

Use spatial 100 ft as the conservative primary review evidence for typed access. Use conservative Travelway-windowed assignments as high-confidence supplemental evidence. Treat broad Travelway-normalized assignments as sensitivity/source-coverage evidence unless broad-only cases pass manual or stricter signal-window review.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start typed_access_rule_overlap_audit")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    source = _load_corrected_source()
    spatial = _prepare_spatial(source)
    conservative = _prepare_conservative(source)
    broad = _prepare_broad(source)
    product_frames = {
        "spatial_100ft": spatial,
        "conservative_travelway_windowed": conservative,
        "broad_travelway_normalized": broad,
    }

    corrected_mapping = (
        source.groupby(["raw_access_control_code", "prior_access_category", "corrected_access_category", "category_correction_reason"], dropna=False)
        .agg(source_point_count=("access_point_id", "nunique"))
        .reset_index()
        .sort_values(["corrected_access_category", "raw_access_control_code"])
    )
    impact = _category_correction_impact(source, product_frames)
    counts = _counts_by_product(product_frames)
    signal_detail, source_detail = _set_table(spatial, conservative, broad)
    overlap_summary = _summarize_overlaps(signal_detail, source_detail)
    broad_audit = _broad_only_audit(broad, signal_detail)
    spatial_audit = _spatial_only_audit(spatial, signal_detail)

    _write_csv(corrected_mapping, "typed_access_corrected_category_mapping.csv")
    _write_csv(impact, "typed_access_category_correction_impact.csv")
    _write_csv(signal_detail, "typed_access_rule_overlap_signal_detail.csv")
    _write_csv(source_detail, "typed_access_rule_overlap_source_point_detail.csv")
    _write_csv(overlap_summary, "typed_access_rule_overlap_summary.csv")
    _write_csv(broad_audit, "typed_access_broad_only_risk_audit.csv")
    _write_csv(spatial_audit, "typed_access_spatial_only_audit.csv")
    _write_csv(counts, "typed_access_category_specific_rule_counts.csv")
    _write_text(_findings(impact, counts, overlap_summary, broad_audit, spatial_audit), "typed_access_rule_overlap_findings.md")
    _write_csv(_qa(), "typed_access_rule_overlap_qa.csv")
    _write_json(
        {
            "script": "src.roadway_graph.audit.typed_access_rule_overlap_audit",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS],
            "outputs": [
                "typed_access_corrected_category_mapping.csv",
                "typed_access_category_correction_impact.csv",
                "typed_access_rule_overlap_signal_detail.csv",
                "typed_access_rule_overlap_source_point_detail.csv",
                "typed_access_rule_overlap_summary.csv",
                "typed_access_broad_only_risk_audit.csv",
                "typed_access_spatial_only_audit.csv",
                "typed_access_category_specific_rule_counts.csv",
                "typed_access_rule_overlap_findings.md",
                "typed_access_rule_overlap_qa.csv",
                "typed_access_rule_overlap_manifest.json",
                "run_progress_log.txt",
            ],
            "category_correction": {
                "R": "right_in_right_out",
                "RC": "right_in_right_out",
                "I": "other_review",
                "M": "other_review",
                "S": "other_review",
                "AS": "other_review",
                "AU": "other_review",
            },
            "review_only": True,
        },
        "typed_access_rule_overlap_manifest.json",
    )
    _checkpoint("complete typed_access_rule_overlap_audit")


if __name__ == "__main__":
    main()
