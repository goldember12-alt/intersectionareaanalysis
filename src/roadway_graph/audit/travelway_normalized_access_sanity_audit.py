from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/travelway_normalized_access_sanity_audit"

STABLE_ACCESS_DIR = OUTPUT_ROOT / "review/current/stable_lineage_final_access_rerun"
HYBRID_DIR = OUTPUT_ROOT / "review/current/final_access_hybrid_source_travelway_diagnostic"

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
    STABLE_ACCESS_DIR / "stable_lineage_final_access_target_bins.csv",
    STABLE_ACCESS_DIR / "stable_lineage_untyped_spatial_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_untyped_travelway_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_source_point_accounting.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_spatial_vs_travelway_comparison.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_product_coverage_summary.csv",
    STABLE_ACCESS_DIR / "stable_lineage_final_access_rerun_manifest.json",
    HYBRID_DIR / "hybrid_access_source_point_detail.csv",
    HYBRID_DIR / "hybrid_access_travelway_match_detail.csv",
    HYBRID_DIR / "hybrid_access_signal_leg_relation.csv",
    HYBRID_DIR / "hybrid_access_leg_length_diagnostic.csv",
    HYBRID_DIR / "hybrid_access_route_identity_diagnostic.csv",
    HYBRID_DIR / "hybrid_access_manifest.json",
]


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
    _checkpoint(f"read_start {path.name}")
    header = pd.read_csv(path, nrows=0).columns.tolist()
    cols = header if usecols is None else [column for column in usecols if column in header]
    blocked = [column for column in cols if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from {path}: {blocked}")
    out = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=cols, low_memory=False)
    _checkpoint(f"read_complete {path.name}", len(out))
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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _missing_inputs() -> list[str]:
    return [str(path) for path in REQUIRED_INPUTS if not path.exists()]


def _text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series("", index=frame.index, dtype=str)
    return frame[column].fillna("").astype(str)


def _bool_text(frame: pd.DataFrame, column: str) -> pd.Series:
    return _text(frame, column).str.lower().isin({"true", "1", "yes", "y"})


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(_text(frame, column), errors="coerce")


def _collapse(values: pd.Series, limit: int = 12) -> str:
    out = []
    for value in values.dropna().astype(str):
        if value.strip() and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _is_assigned(frame: pd.DataFrame) -> pd.Series:
    return _text(frame, "route_normalized_assignment_status").eq("assigned_review_only")


def _source_denominators(source: pd.DataFrame, travelway_match: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer in ["untyped", "typed_v2"]:
        src = source.loc[_text(source, "access_layer").eq(layer)]
        tw = travelway_match.loc[_text(travelway_match, "access_layer").eq(layer)]
        cand = assignments.loc[_text(assignments, "access_layer").eq(layer)]
        assigned = cand.loc[_is_assigned(cand)]
        rows.append(
            {
                "access_layer": layer,
                "total_source_points": int(_text(src, "access_point_id").nunique()),
                "source_points_with_geometry": int(src.loc[_bool_text(src, "has_geometry"), "access_point_id"].nunique()),
                "source_points_with_route_fields": int(src.loc[_bool_text(src, "has_route_fields"), "access_point_id"].nunique()),
                "source_points_with_stable_or_source_travelway_match": int(_text(tw.loc[_text(tw, "source_travelway_match_confidence").ne("")], "access_point_id").nunique()),
                "source_points_with_signal_window_eligible_assignment": int(_text(assigned.loc[_text(assigned, "target_bin_id").ne("") & _text(assigned, "analysis_window").isin(["0_1000", "1000_2500"])], "access_point_id").nunique()),
                "travelway_normalized_captured_source_points": int(_text(assigned, "access_point_id").nunique()),
                "travelway_normalized_assignment_rows": int(len(assigned)),
            }
        )
    return pd.DataFrame(rows)


def _assignment_method_summary(assignments: pd.DataFrame) -> pd.DataFrame:
    assigned = assignments.loc[_is_assigned(assignments)].copy()
    method = _text(assigned, "stable_travelway_assignment_match_class")
    assigned["assignment_method_group"] = np.select(
        [
            method.eq("direct_stable_travelway_id"),
            method.eq("route_measure_overlap"),
            _text(assigned, "route_normalized_quality_class").eq("low_confidence_route_family_only"),
            method.eq("route_facility_compatible"),
            method.eq("spatial_catchment_only"),
            method.str.contains("unknown|unmatched|fallback", case=False, regex=True),
        ],
        [
            "direct_stable_travelway_id_match",
            "route_measure_overlap",
            "route_family_only",
            "route_facility_compatible",
            "spatial_fallback",
            "unknown_fallback",
        ],
        default="other",
    )
    return assigned.groupby(["access_layer", "assignment_method_group", "stable_travelway_assignment_match_class", "route_normalized_quality_class"], dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        assignment_count=("access_point_id", "size"),
        signal_count=("target_signal_id", "nunique"),
        stable_travelway_count=("stable_travelway_id", "nunique"),
    ).reset_index().sort_values(["access_layer", "source_point_count"], ascending=[True, False])


def _distance_band_from_assignment(frame: pd.DataFrame) -> pd.Series:
    distance_band = _text(frame, "distance_band")
    analysis = _text(frame, "analysis_window")
    hybrid_class = _text(frame, "hybrid_leg_length_class")
    nearest_band = _text(frame, "nearest_distance_band")
    out = pd.Series("unknown", index=frame.index, dtype=str)
    out.loc[distance_band.eq("0_250ft")] = "0_250"
    out.loc[distance_band.eq("250_500ft")] = "250_500"
    out.loc[distance_band.eq("500_750ft")] = "500_750"
    out.loc[distance_band.eq("750_1000ft")] = "750_1000"
    out.loc[distance_band.eq("1000_1500ft")] = "1000_1500"
    out.loc[distance_band.eq("1500_2500ft")] = "1500_2500"
    out.loc[analysis.eq("1000_2500") & out.eq("unknown")] = "1000_2500"
    out.loc[hybrid_class.str.contains("beyond_2500|out_of_scope", case=False, regex=True)] = ">2500"
    out.loc[nearest_band.eq("gt_1000ft") & analysis.eq("")] = ">2500"
    return out


def _window_eligible(frame: pd.DataFrame) -> pd.Series:
    return _text(frame, "target_bin_id").ne("") & _text(frame, "stable_bin_id").ne("") & _text(frame, "analysis_window").isin(["0_1000", "1000_2500"])


def _build_distance_detail(assignments: pd.DataFrame, hybrid_relation: pd.DataFrame) -> pd.DataFrame:
    assigned = assignments.loc[_is_assigned(assignments)].copy()
    hybrid_cols = [
        "access_point_id",
        "access_layer",
        "target_bin_id",
        "captured_100ft",
        "captured_any_buffer",
        "nearest_distance_ft",
        "nearest_distance_band",
        "leg_length_limitation_class",
        "hybrid_leg_length_class",
        "route_identity_opportunity_flag",
        "catchment_geometry_opportunity_flag",
        "leg_extension_0_1000_opportunity_flag",
        "leg_extension_1000_2500_opportunity_flag",
    ]
    hybrid = hybrid_relation[[col for col in hybrid_cols if col in hybrid_relation.columns]].copy()
    out = assigned.merge(hybrid, on=["access_point_id", "access_layer", "target_bin_id"], how="left", suffixes=("", "_hybrid"))
    out["assignment_distance_band"] = _distance_band_from_assignment(out)
    out["within_valid_signal_relative_window"] = _window_eligible(out)
    out["route_only_spatially_far_from_signal"] = (
        _text(out, "stable_travelway_assignment_match_class").isin(["route_facility_compatible", "route_measure_overlap"])
        & ~_bool_text(out, "captured_100ft")
        & _text(out, "nearest_distance_band").isin(["gt_1000ft", "unknown", ""])
    )
    keep = [
        "access_point_id",
        "access_layer",
        "target_signal_id",
        "target_bin_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_stable_travelway_id",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "analysis_window",
        "distance_band",
        "assignment_distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "nearest_distance_ft",
        "nearest_distance_band",
        "captured_100ft",
        "stable_travelway_assignment_match_class",
        "route_normalized_quality_class",
        "route_normalized_fanout_count",
        "lineage_confidence",
        "hybrid_leg_length_class",
        "leg_length_limitation_class",
        "within_valid_signal_relative_window",
        "route_only_spatially_far_from_signal",
    ]
    return out[[col for col in keep if col in out.columns]].copy()


def _overcapture_class(frame: pd.DataFrame) -> pd.Series:
    match_class = _text(frame, "stable_travelway_assignment_match_class")
    quality = _text(frame, "route_normalized_quality_class")
    captured = _bool_text(frame, "captured_100ft")
    eligible = frame["within_valid_signal_relative_window"].fillna(False).astype(bool)
    distance_band = _text(frame, "assignment_distance_band")
    route_far = frame["route_only_spatially_far_from_signal"].fillna(False).astype(bool)
    target_missing = _text(frame, "target_bin_id").eq("") | _text(frame, "stable_bin_id").eq("")
    out = pd.Series("manual_review_needed", index=frame.index, dtype=str)
    out.loc[captured & eligible] = "valid_spatial_and_travelway_supported"
    out.loc[~captured & eligible & match_class.isin(["direct_stable_travelway_id", "route_measure_overlap"])] = "valid_travelway_supported_within_signal_window"
    out.loc[target_missing | (~eligible & match_class.isin(["direct_stable_travelway_id", "route_measure_overlap", "route_facility_compatible"]))] = "route_identity_match_but_distance_uncertain"
    out.loc[route_far | distance_band.eq(">2500")] = "long_route_overcapture_risk"
    out.loc[~eligible & distance_band.eq(">2500")] = "route_identity_match_but_beyond_signal_window"
    out.loc[quality.eq("low_confidence_route_family_only")] = "route_family_only_low_confidence"
    return out


def _risk_detail(distance_detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    out = distance_detail.copy()
    out["overcapture_risk_class"] = _overcapture_class(out)
    summary = out.groupby(["access_layer", "overcapture_risk_class", "stable_travelway_assignment_match_class", "route_normalized_quality_class"], dropna=False).agg(
        source_point_count=("access_point_id", "nunique"),
        assignment_count=("access_point_id", "size"),
        signal_count=("target_signal_id", "nunique"),
    ).reset_index().sort_values(["access_layer", "source_point_count"], ascending=[True, False])
    return out, summary


def _typed_vs_untyped_explanation(denom: pd.DataFrame, methods: pd.DataFrame, risk_summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for layer in ["untyped", "typed_v2"]:
        d = denom.loc[denom["access_layer"].eq(layer)].iloc[0]
        total = int(d.total_source_points)
        captured = int(d.travelway_normalized_captured_source_points)
        route_facility = methods.loc[(methods["access_layer"].eq(layer)) & (methods["assignment_method_group"].eq("route_facility_compatible")), "source_point_count"].sum()
        direct = methods.loc[(methods["access_layer"].eq(layer)) & (methods["assignment_method_group"].eq("direct_stable_travelway_id_match")), "source_point_count"].sum()
        route_family = methods.loc[(methods["access_layer"].eq(layer)) & (methods["assignment_method_group"].eq("route_family_only")), "source_point_count"].sum()
        risk = risk_summary.loc[(risk_summary["access_layer"].eq(layer)) & (risk_summary["overcapture_risk_class"].isin(["long_route_overcapture_risk", "route_identity_match_but_distance_uncertain", "route_family_only_low_confidence"])), "source_point_count"].sum()
        rows.append(
            {
                "access_layer": layer,
                "total_source_points": total,
                "travelway_captured_source_points": captured,
                "travelway_capture_rate": round(captured / total, 6) if total else 0,
                "direct_stable_source_points": int(direct),
                "route_facility_compatible_source_points": int(route_facility),
                "route_family_only_source_points": int(route_family),
                "overcapture_risk_source_points": int(risk),
                "explanation": (
                    "Typed v2 capture is dominated by route/facility-compatible and route-family rows; high share reflects cleaner/concentrated route source coverage plus permissive fallback, not validated final signal-window access."
                    if layer == "typed_v2"
                    else "Untyped access has broader source coverage, more unrepresented/out-of-scope routes, and lower Travelway-normalized capture share."
                ),
            }
        )
    return pd.DataFrame(rows)


def _coverage_for_filter(detail: pd.DataFrame, label: str, mask: pd.Series) -> list[dict[str, Any]]:
    rows = []
    sub = detail.loc[mask].copy()
    for layer in ["untyped", "typed_v2"]:
        layer_sub = sub.loc[_text(sub, "access_layer").eq(layer)]
        rows.append(
            {
                "filter_name": label,
                "access_layer": layer,
                "source_point_count": int(_text(layer_sub, "access_point_id").nunique()),
                "assignment_count": int(len(layer_sub)),
                "signal_count": int(_text(layer_sub, "target_signal_id").nunique()),
                "zero_to_1000_source_point_count": int(_text(layer_sub.loc[_text(layer_sub, "analysis_window").eq("0_1000")], "access_point_id").nunique()),
                "zero_to_2500_source_point_count": int(_text(layer_sub.loc[_text(layer_sub, "analysis_window").isin(["0_1000", "1000_2500"])], "access_point_id").nunique()),
            }
        )
    return rows


def _conservative_estimates(risk_detail: pd.DataFrame) -> pd.DataFrame:
    quality = _text(risk_detail, "route_normalized_quality_class")
    risk = _text(risk_detail, "overcapture_risk_class")
    window = _text(risk_detail, "analysis_window")
    distance_uncertain = risk.isin(["route_identity_match_but_distance_uncertain", "long_route_overcapture_risk", "route_family_only_low_confidence", "manual_review_needed"])
    rows: list[dict[str, Any]] = []
    rows.extend(_coverage_for_filter(risk_detail, "all_travelway_normalized_assigned", pd.Series(True, index=risk_detail.index)))
    rows.extend(_coverage_for_filter(risk_detail, "high_confidence_only", quality.eq("high_confidence_source_travelway_match")))
    rows.extend(_coverage_for_filter(risk_detail, "high_plus_medium_confidence", quality.isin(["high_confidence_source_travelway_match", "medium_confidence_route_facility_match"])))
    rows.extend(_coverage_for_filter(risk_detail, "within_0_1000_only", window.eq("0_1000") & ~distance_uncertain))
    rows.extend(_coverage_for_filter(risk_detail, "within_0_2500_only", window.isin(["0_1000", "1000_2500"]) & ~distance_uncertain))
    rows.extend(_coverage_for_filter(risk_detail, "exclude_route_family_only", ~quality.eq("low_confidence_route_family_only")))
    rows.extend(_coverage_for_filter(risk_detail, "exclude_distance_uncertain", ~distance_uncertain))
    return pd.DataFrame(rows)


def _qa() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("no_active_outputs_modified", True, "Writes only to travelway_normalized_access_sanity_audit."),
            ("no_candidates_promoted", True, "Diagnostic only."),
            ("no_crash_records_read", True, "No crash files are in required inputs."),
            ("no_crash_direction_fields_read_or_used", True, "Reader blocks crash field tokens."),
            ("no_crash_assignment_or_catchments", True, "No crash assignment/catchment logic."),
            ("no_rates_or_models", True, "Only counts and QA diagnostics."),
            ("typed_and_untyped_separate", True, "All summaries group by access_layer."),
            ("source_point_counts_separate_from_assignment_counts", True, "Outputs include both source_point_count and assignment_count."),
            ("review_only_outputs", True, "No final metric is chosen."),
        ],
        columns=["qa_check", "passed", "detail"],
    )


def _findings(denom: pd.DataFrame, methods: pd.DataFrame, risk_summary: pd.DataFrame, conservative: pd.DataFrame) -> str:
    def d(layer: str, field: str) -> int:
        row = denom.loc[denom["access_layer"].eq(layer)].iloc[0]
        return int(row[field])

    def method_count(layer: str, method: str) -> int:
        return int(methods.loc[(methods["access_layer"].eq(layer)) & (methods["assignment_method_group"].eq(method)), "source_point_count"].sum())

    def risk_count(layer: str, cls: str) -> int:
        return int(risk_summary.loc[(risk_summary["access_layer"].eq(layer)) & (risk_summary["overcapture_risk_class"].eq(cls)), "source_point_count"].sum())

    def conservative_line(filter_name: str) -> str:
        sub = conservative.loc[conservative["filter_name"].eq(filter_name)]
        parts = []
        for row in sub.itertuples(index=False):
            parts.append(f"{row.access_layer}: {int(row.source_point_count):,} source points / {int(row.signal_count):,} signals")
        return "; ".join(parts)

    return f"""# Travelway-Normalized Access Sanity Audit Findings

## Bounded Question

Are Travelway-normalized access assignments genuinely signal-window relevant, or are they mostly route/Travelway identity matches along long represented routes?

## Denominators

- Untyped source points: {d('untyped', 'total_source_points'):,}; with geometry: {d('untyped', 'source_points_with_geometry'):,}; with route fields: {d('untyped', 'source_points_with_route_fields'):,}; captured by Travelway-normalized assignment: {d('untyped', 'travelway_normalized_captured_source_points'):,}.
- Typed v2 source points: {d('typed_v2', 'total_source_points'):,}; with geometry: {d('typed_v2', 'source_points_with_geometry'):,}; with route fields: {d('typed_v2', 'source_points_with_route_fields'):,}; captured by Travelway-normalized assignment: {d('typed_v2', 'travelway_normalized_captured_source_points'):,}.

## Method Mix

- Untyped direct stable Travelway ID matches: {method_count('untyped', 'direct_stable_travelway_id_match'):,}; route/measure overlap: {method_count('untyped', 'route_measure_overlap'):,}; route/facility compatible: {method_count('untyped', 'route_facility_compatible'):,}.
- Typed v2 direct stable Travelway ID matches: {method_count('typed_v2', 'direct_stable_travelway_id_match'):,}; route/measure overlap: {method_count('typed_v2', 'route_measure_overlap'):,}; route/facility compatible: {method_count('typed_v2', 'route_facility_compatible'):,}.

## Overcapture Risk

- Untyped route-family low-confidence source points: {risk_count('untyped', 'route_family_only_low_confidence'):,}; distance-uncertain: {risk_count('untyped', 'route_identity_match_but_distance_uncertain'):,}; long-route overcapture risk: {risk_count('untyped', 'long_route_overcapture_risk'):,}.
- Typed v2 route-family low-confidence source points: {risk_count('typed_v2', 'route_family_only_low_confidence'):,}; distance-uncertain: {risk_count('typed_v2', 'route_identity_match_but_distance_uncertain'):,}; long-route overcapture risk: {risk_count('typed_v2', 'long_route_overcapture_risk'):,}.

## Conservative Coverage Estimates

- High-confidence only: {conservative_line('high_confidence_only')}.
- High + medium confidence: {conservative_line('high_plus_medium_confidence')}.
- Within 0-1,000 ft and not distance-uncertain: {conservative_line('within_0_1000_only')}.
- Within 0-2,500 ft and not distance-uncertain: {conservative_line('within_0_2500_only')}.
- Excluding route-family-only: {conservative_line('exclude_route_family_only')}.
- Excluding distance-uncertain: {conservative_line('exclude_distance_uncertain')}.

## Interpretation

Typed v2's high Travelway-normalized capture share is not enough evidence that those points are all signal-window-relevant. The typed product has much more route/facility-compatible coverage, but a large share is not direct stable-ID or strict route/measure overlap. Some rows are assigned with blank target-bin fields or weak route-family evidence, so the prior Travelway-normalized assignment is too permissive as a final access product.

## Recommendation

The next access rule should require signal-window distance support. Use spatial catchment as the conservative primary review product for now, and treat Travelway-normalized assignments as sensitivity/source-coverage evidence unless they are direct stable-ID or route/measure-overlap matches with a nonblank target bin inside the 0-1,000 ft or 1,000-2,500 ft scaffold window. Route/family-only rows should remain diagnostic, not final access assignments.
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    started = datetime.now(timezone.utc)
    _checkpoint("run_start")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    source = _read_csv(HYBRID_DIR / "hybrid_access_source_point_detail.csv")
    travelway_match = _read_csv(HYBRID_DIR / "hybrid_access_travelway_match_detail.csv")
    hybrid_relation = _read_csv(HYBRID_DIR / "hybrid_access_signal_leg_relation.csv")
    untyped_tw = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_untyped_travelway_assignment_detail.csv")
    typed_tw = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_typed_v2_travelway_assignment_detail.csv")
    assignments = pd.concat([untyped_tw, typed_tw], ignore_index=True, sort=False)

    denominators = _source_denominators(source, travelway_match, assignments)
    method_summary = _assignment_method_summary(assignments)
    distance_detail = _build_distance_detail(assignments, hybrid_relation)
    risk_detail, risk_summary = _risk_detail(distance_detail)
    explanation = _typed_vs_untyped_explanation(denominators, method_summary, risk_summary)
    conservative = _conservative_estimates(risk_detail)
    qa = _qa()

    _write_csv(denominators, "access_source_denominator_validation.csv")
    _write_csv(method_summary, "travelway_assignment_method_summary.csv")
    _write_csv(distance_detail, "travelway_assignment_distance_window_detail.csv")
    _write_csv(risk_detail, "travelway_assignment_overcapture_risk_detail.csv")
    _write_csv(explanation, "typed_vs_untyped_capture_explanation.csv")
    _write_csv(conservative, "conservative_travelway_access_coverage_estimates.csv")
    _write_csv(qa, "travelway_normalized_access_sanity_qa.csv")
    _write_text(_findings(denominators, method_summary, risk_summary, conservative), "travelway_normalized_access_sanity_findings.md")

    manifest = {
        "created_at_utc": _now(),
        "started_at_utc": started.isoformat(),
        "script": "src.roadway_graph.audit.travelway_normalized_access_sanity_audit",
        "bounded_question": "Read-only sanity audit of stable Travelway-normalized access assignment relevance and overcapture risk.",
        "output_dir": str(OUT_DIR),
        "inputs": {
            "stable_lineage_final_access_rerun": str(STABLE_ACCESS_DIR),
            "hybrid_access_source_travelway_diagnostic": str(HYBRID_DIR),
            "stable_access_manifest": _load_json(STABLE_ACCESS_DIR / "stable_lineage_final_access_rerun_manifest.json"),
            "hybrid_manifest": _load_json(HYBRID_DIR / "hybrid_access_manifest.json"),
        },
        "metrics": {
            "untyped_source_points": int(denominators.loc[denominators["access_layer"].eq("untyped"), "total_source_points"].iloc[0]),
            "typed_v2_source_points": int(denominators.loc[denominators["access_layer"].eq("typed_v2"), "total_source_points"].iloc[0]),
            "untyped_travelway_captured_source_points": int(denominators.loc[denominators["access_layer"].eq("untyped"), "travelway_normalized_captured_source_points"].iloc[0]),
            "typed_v2_travelway_captured_source_points": int(denominators.loc[denominators["access_layer"].eq("typed_v2"), "travelway_normalized_captured_source_points"].iloc[0]),
        },
        "outputs": [
            "access_source_denominator_validation.csv",
            "travelway_assignment_method_summary.csv",
            "travelway_assignment_distance_window_detail.csv",
            "travelway_assignment_overcapture_risk_detail.csv",
            "typed_vs_untyped_capture_explanation.csv",
            "conservative_travelway_access_coverage_estimates.csv",
            "travelway_normalized_access_sanity_findings.md",
            "travelway_normalized_access_sanity_qa.csv",
            "travelway_normalized_access_sanity_manifest.json",
            "run_progress_log.txt",
        ],
        "non_goals_confirmed": {
            "active_outputs_modified": False,
            "candidates_promoted": False,
            "crash_records_read": False,
            "crash_direction_fields_read": False,
            "crash_assignment_or_catchments": False,
            "rates_or_models": False,
            "final_access_metric_chosen": False,
        },
    }
    _write_json(manifest, "travelway_normalized_access_sanity_manifest.json")
    _checkpoint("run_complete")


if __name__ == "__main__":
    main()
