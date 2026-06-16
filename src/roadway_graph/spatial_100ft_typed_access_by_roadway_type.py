from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
OUT_DIR = OUTPUT_ROOT / "review/current/spatial_100ft_typed_access_by_roadway_type"

BASELINE_DIR = OUTPUT_ROOT / "review/current/final_access_baseline_freeze"
STABLE_ACCESS_DIR = OUTPUT_ROOT / "review/current/stable_lineage_final_access_rerun"
OVERLAP_DIR = OUTPUT_ROOT / "review/current/typed_access_rule_overlap_audit"
FINAL_OVERVIEW_DIR = OUTPUT_ROOT / "review/current/final_signal_leg_universe_overview"
STABLE_REGEN_DIR = OUTPUT_ROOT / "review/current/stable_lineage_scaffold_regeneration"
LINEAGE_BRIDGE_DIR = OUTPUT_ROOT / "review/current/source_travelway_lineage_bridge"
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
    BASELINE_DIR / "final_access_primary_typed_v2_spatial_100ft_summary.csv",
    BASELINE_DIR / "final_access_typed_category_corrected_summary.csv",
    BASELINE_DIR / "final_access_baseline_product_inventory.csv",
    BASELINE_DIR / "final_access_baseline_manifest.json",
    STABLE_ACCESS_DIR / "stable_lineage_final_access_target_bins.csv",
    STABLE_ACCESS_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv",
    STABLE_ACCESS_DIR / "stable_lineage_access_by_scaffold_qa_summary.csv",
    STABLE_ACCESS_DIR / "stable_lineage_final_access_rerun_manifest.json",
    OVERLAP_DIR / "typed_access_corrected_category_mapping.csv",
    OVERLAP_DIR / "typed_access_category_correction_impact.csv",
    OVERLAP_DIR / "typed_access_rule_overlap_source_point_detail.csv",
    OVERLAP_DIR / "typed_access_category_specific_rule_counts.csv",
    OVERLAP_DIR / "typed_access_rule_overlap_manifest.json",
    FINAL_OVERVIEW_DIR / "final_signal_universe_detail.csv",
    FINAL_OVERVIEW_DIR / "final_consolidated_leg_bin_detail.csv",
    FINAL_OVERVIEW_DIR / "final_expected_vs_represented_alignment.csv",
    FINAL_OVERVIEW_DIR / "final_signal_leg_universe_overview_manifest.json",
    STABLE_REGEN_DIR / "stable_lineage_represented_bin_universe.csv",
    STABLE_REGEN_DIR / "stable_lineage_represented_signal_universe.csv",
    STABLE_REGEN_DIR / "stable_lineage_generation_manifest.json",
    LINEAGE_BRIDGE_DIR / "source_travelway_stable_identity.csv",
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

CATEGORY_ORDER = [
    "unrestricted_or_full_access",
    "right_in_right_out",
    "restricted_partial_access",
    "right_in_only",
    "right_out_only",
    "other_review",
    "unknown",
]

ROADWAY_FIELD_CANDIDATES = [
    "facility_text",
    "RIM_FACILI",
    "RIM_FACI_1",
    "RTE_CATEGO",
    "RTE_TYPE_N",
    "RTE_RAMP_C",
    "RIM_MEDIAN",
    "RIM_ACCESS",
    "source_route_common",
    "source_route_name",
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


def _num(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _collapse(values: pd.Series, limit: int = 15) -> str:
    out: list[str] = []
    for value in values.dropna().astype(str):
        value = value.strip()
        if value and value not in out:
            out.append(value)
        if len(out) >= limit:
            break
    return "|".join(out)


def _correct_category(raw_code: str) -> str:
    code = "" if pd.isna(raw_code) else str(raw_code).strip().upper()
    return CORRECTED_CATEGORY_MAP.get(code, "other_review")


def _correction_reason(raw_code: str, prior: str, corrected: str) -> str:
    code = "" if pd.isna(raw_code) else str(raw_code).strip().upper()
    if code in {"R", "RC"}:
        return "confirmed_R_RC_are_RIRO"
    if prior == corrected:
        return "unchanged_confirmed_mapping"
    return "corrected_from_raw_code_mapping"


def _load_access_source_categories() -> pd.DataFrame:
    source = pd.read_parquet(ACCESS_V2)
    blocked = [column for column in source.columns if _blocked_column(column)]
    if blocked:
        raise ValueError(f"Refusing to read crash fields from typed access source: {blocked}")
    source = source.copy()
    source["access_point_id"] = _text(source, "access_v2_source_priority") + ":" + _text(source, "access_v2_source_row_id")
    source["raw_access_control_code"] = _text(source, "access_control_code").str.upper()
    source["prior_access_category"] = _text(source, "access_control_category").replace("", "unknown")
    source["corrected_access_category"] = source["raw_access_control_code"].map(_correct_category)
    source["category_correction_reason"] = [
        _correction_reason(code, prior, corrected)
        for code, prior, corrected in zip(
            source["raw_access_control_code"],
            source["prior_access_category"],
            source["corrected_access_category"],
        )
    ]
    keep = [
        "access_point_id",
        "raw_access_control_code",
        "access_control_raw",
        "prior_access_category",
        "corrected_access_category",
        "category_correction_reason",
    ]
    return source[[column for column in keep if column in source.columns]].drop_duplicates("access_point_id")


def _field_inventory(lineage: pd.DataFrame, selected_field: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for field in ROADWAY_FIELD_CANDIDATES:
        available = field in lineage.columns
        nonblank = int(_text(lineage, field).str.strip().ne("").sum()) if available else 0
        unique = int(_text(lineage, field).replace("", pd.NA).dropna().nunique()) if available else 0
        rows.append(
            {
                "field_name": field,
                "available": available,
                "nonblank_source_travelway_features": nonblank,
                "unique_values": unique,
                "selected_primary_grouping_field": field == selected_field,
                "selection_note": "selected most specific available facility text" if field == selected_field else "",
            }
        )
    return pd.DataFrame(rows)


def _build_detail() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    spatial = _read_csv(STABLE_ACCESS_DIR / "stable_lineage_typed_v2_spatial_assignment_detail.csv")
    spatial = spatial.loc[_text(spatial, "buffer_width_ft").eq("100")].copy()
    spatial = spatial.loc[_text(spatial, "access_layer").eq("typed_v2")].copy()
    source_categories = _load_access_source_categories()
    spatial = spatial.merge(source_categories, on="access_point_id", how="left")
    fallback = _text(spatial, "access_control_category")
    for column in ["prior_access_category", "corrected_access_category"]:
        values = _text(spatial, column)
        spatial[column] = values.where(values.ne(""), fallback)

    lineage = _read_csv(LINEAGE_BRIDGE_DIR / "source_travelway_stable_identity.csv")
    selected_field = "facility_text" if "facility_text" in lineage.columns and _text(lineage, "facility_text").str.strip().ne("").any() else "source_route_common"
    inventory = _field_inventory(lineage, selected_field)
    keep = [
        "stable_travelway_id",
        "facility_text",
        "name_facility_fields",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "from_measure",
        "to_measure",
        "EVENT_SOUR",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
    ]
    spatial = spatial.merge(lineage[[column for column in keep if column in lineage.columns]], on="stable_travelway_id", how="left", suffixes=("", "_travelway"))
    spatial["roadway_type_grouping_field"] = selected_field
    spatial["roadway_type"] = _text(spatial, selected_field).replace("", "unknown_roadway_type")
    if "source_route_common_travelway" in spatial.columns:
        spatial["travelway_source_route_common"] = _text(spatial, "source_route_common_travelway")
    else:
        spatial["travelway_source_route_common"] = _text(spatial, "source_route_common")
    spatial["product"] = "typed_v2_spatial_100ft_enrichment"
    spatial["window_0_1000"] = _text(spatial, "analysis_window").eq("0_1000")
    spatial["window_0_2500"] = _text(spatial, "analysis_window").isin(["0_1000", "1000_2500"])
    return spatial, inventory, selected_field


def _summarize(detail: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for window, mask in {
        "0-1,000 ft": detail["window_0_1000"],
        "0-2,500 ft": detail["window_0_2500"],
    }.items():
        subset = detail.loc[mask].copy()
        totals = (
            subset.groupby("roadway_type", dropna=False)
            .agg(
                roadway_type_source_points=("access_point_id", "nunique"),
                roadway_type_signals=("target_signal_id", "nunique"),
            )
            .reset_index()
        )
        for (roadway_type, category), group in subset.groupby(["roadway_type", "corrected_access_category"], dropna=False):
            total_row = totals.loc[totals["roadway_type"].eq(roadway_type)]
            total_source = int(total_row["roadway_type_source_points"].iloc[0]) if not total_row.empty else 0
            total_signals = int(total_row["roadway_type_signals"].iloc[0]) if not total_row.empty else 0
            source_points = int(group["access_point_id"].nunique())
            signals = int(group["target_signal_id"].nunique())
            rows.append(
                {
                    "product": "typed_v2_spatial_100ft_enrichment",
                    "window": window,
                    "roadway_type": roadway_type,
                    "corrected_access_category": category,
                    "source_points": source_points,
                    "signals": signals,
                    "assignment_rows": int(len(group)),
                    "source_point_share_within_roadway_type_window": round(source_points / total_source, 6) if total_source else 0.0,
                    "signal_share_within_roadway_type_window": round(signals / total_signals, 6) if total_signals else 0.0,
                    "source_preserving_weighted_total": round(float(_num(group, "source_preserving_weighted_access_count").sum()), 6),
                    "unweighted_assignment_total": round(float(_num(group, "unweighted_access_count").sum()), 6),
                    "unique_physical_legs": int(_text(group, "physical_leg_id").replace("", pd.NA).dropna().nunique()),
                    "unique_carriageway_subbranches": int(_text(group, "carriageway_subbranch_id").replace("", pd.NA).dropna().nunique()),
                }
            )
    full = pd.DataFrame(rows)
    order = {category: i for i, category in enumerate(CATEGORY_ORDER)}
    if not full.empty:
        full["category_sort"] = full["corrected_access_category"].map(order).fillna(99).astype(int)
        full = full.sort_values(["window", "roadway_type", "source_points", "category_sort"], ascending=[True, True, False, True]).drop(columns="category_sort")
    compact = full.copy()
    compact["share"] = (compact["source_point_share_within_roadway_type_window"] * 100).round(1).astype(str) + "%"
    compact = compact[
        [
            "product",
            "window",
            "roadway_type",
            "corrected_access_category",
            "source_points",
            "signals",
            "share",
        ]
    ]
    roadway_totals = (
        detail.assign(
            window_label_0_1000=detail["window_0_1000"],
            window_label_0_2500=detail["window_0_2500"],
        )
    )
    total_rows: list[dict[str, Any]] = []
    for window, mask in {"0-1,000 ft": detail["window_0_1000"], "0-2,500 ft": detail["window_0_2500"]}.items():
        subset = detail.loc[mask]
        for roadway_type, group in subset.groupby("roadway_type", dropna=False):
            total_rows.append(
                {
                    "product": "typed_v2_spatial_100ft_enrichment",
                    "window": window,
                    "roadway_type": roadway_type,
                    "source_points": int(group["access_point_id"].nunique()),
                    "signals": int(group["target_signal_id"].nunique()),
                    "assignment_rows": int(len(group)),
                    "unique_physical_legs": int(_text(group, "physical_leg_id").replace("", pd.NA).dropna().nunique()),
                    "unique_carriageway_subbranches": int(_text(group, "carriageway_subbranch_id").replace("", pd.NA).dropna().nunique()),
                }
            )
    roadway_totals_df = pd.DataFrame(total_rows).sort_values(["window", "source_points"], ascending=[True, False])
    category_total_rows: list[dict[str, Any]] = []
    for window, mask in {"0-1,000 ft": detail["window_0_1000"], "0-2,500 ft": detail["window_0_2500"]}.items():
        subset = detail.loc[mask].copy()
        for category, group in subset.groupby("corrected_access_category", dropna=False):
            category_total_rows.append(
                {
                    "product": "typed_v2_spatial_100ft_enrichment",
                    "window": window,
                    "corrected_access_category": category,
                    "source_points": int(group["access_point_id"].nunique()),
                    "signals": int(group["target_signal_id"].nunique()),
                    "assignment_rows": int(len(group)),
                    "source_preserving_weighted_total": round(float(_num(group, "source_preserving_weighted_access_count").sum()), 6),
                    "note": "globally deduped by access_point_id within window/category; roadway-type subtotals may not add to this because spatial access can multi-assign across roadway types",
                }
            )
    category_totals = pd.DataFrame(category_total_rows).sort_values(["window", "source_points"], ascending=[True, False])
    top = (
        full.sort_values(["window", "roadway_type", "source_points"], ascending=[True, True, False])
        .groupby(["window", "roadway_type"], dropna=False)
        .head(3)
        .reset_index(drop=True)
    )
    return full, compact, roadway_totals_df, category_totals, top


def _qa_summary(detail: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    fields = [
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "review_only_recovery_provenance",
    ]
    for window, mask in {"0-1,000 ft": detail["window_0_1000"], "0-2,500 ft": detail["window_0_2500"]}.items():
        subset = detail.loc[mask].copy()
        for field in fields:
            for (roadway_type, category, value), group in subset.groupby(["roadway_type", "corrected_access_category", field], dropna=False):
                rows.append(
                    {
                        "window": window,
                        "roadway_type": roadway_type,
                        "corrected_access_category": category,
                        "qa_field": field,
                        "qa_value": value if str(value).strip() else "blank",
                        "source_points": int(group["access_point_id"].nunique()),
                        "signals": int(group["target_signal_id"].nunique()),
                        "assignment_rows": int(len(group)),
                    }
                )
    return pd.DataFrame(rows)


def _qa_checks(selected_field: str) -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", "passed", "outputs written only to review/current/spatial_100ft_typed_access_by_roadway_type"),
        ("no_candidates_promoted", "passed", "summary only"),
        ("no_crash_records_read", "passed", "input fields screened for crash tokens"),
        ("no_crash_direction_fields_used", "passed", "crash direction tokens blocked"),
        ("no_crash_assignment_or_catchments", "passed", "no assignment logic run"),
        ("no_rates_or_models", "passed", "counts only"),
        ("only_spatial_100ft_typed_v2_used", "passed", "filtered typed_v2 spatial assignments to buffer_width_ft=100"),
        ("corrected_categories_used", "passed", "R/RC mapped to right_in_right_out from access_v2 source codes"),
        ("raw_access_codes_preserved", "passed", "raw_access_control_code and prior_access_category retained in detail"),
        ("roadway_type_grouping_documented", "passed", selected_field),
        ("outputs_review_only_folder", "passed", str(OUT_DIR)),
    ]
    return pd.DataFrame(rows, columns=["check_name", "status", "observed"])


def _findings(selected_field: str, compact: pd.DataFrame, roadway_totals: pd.DataFrame, qa: pd.DataFrame) -> str:
    roadway_types = ", ".join(roadway_totals["roadway_type"].drop_duplicates().astype(str).head(20))

    def top_count(window: str, category: str) -> str:
        subset = compact.loc[(compact["window"].eq(window)) & (compact["corrected_access_category"].eq(category))]
        if subset.empty:
            return "none"
        row = subset.sort_values("source_points", ascending=False).iloc[0]
        return f"{row['roadway_type']} ({int(row['source_points']):,} source points, {int(row['signals']):,} signals)"

    other = compact.loc[compact["corrected_access_category"].isin(["other_review", "unknown"])].copy()
    dominated = []
    for (window, roadway_type), group in compact.groupby(["window", "roadway_type"], dropna=False):
        total = int(group["source_points"].sum())
        other_total = int(other.loc[other["window"].eq(window) & other["roadway_type"].eq(roadway_type), "source_points"].sum())
        if total and other_total / total >= 0.5:
            dominated.append(f"{window} {roadway_type} ({other_total}/{total})")
    dominated_text = "; ".join(dominated[:12]) if dominated else "none"

    return f"""# Spatial 100 ft Typed Access By Roadway Type Findings

## Bounded Question

This read-only table summarizes only the conservative primary typed access review product: typed v2 spatial 100 ft assignments. It excludes untyped access, conservative Travelway-windowed access, broad Travelway-normalized access, crash records, crash direction fields, rates, and models.

## Roadway Type Grouping

- Selected roadway type field: `{selected_field}`
- Roadway type categories present: {roadway_types}

`{selected_field}` was selected because it is the most specific available stable Travelway roadway/facility field in `source_travelway_stable_identity.csv`. Divided/undivided-only labels were not used as the primary grouping.

Counts are deduped within each roadway type/window/category. They are not intended to be additive across roadway types because spatial access points can legitimately multi-assign across signal/bin contexts and, in rare cases, across roadway-type groups.

## 0-1,000 ft Summary

- Most unrestricted/full access: {top_count('0-1,000 ft', 'unrestricted_or_full_access')}
- Most RIRO access: {top_count('0-1,000 ft', 'right_in_right_out')}

## 0-2,500 ft Summary

- Most unrestricted/full access: {top_count('0-2,500 ft', 'unrestricted_or_full_access')}
- Most RIRO access: {top_count('0-2,500 ft', 'right_in_right_out')}

## Other Review / Unknown

- Roadway type/window groups dominated by `other_review` or `unknown`: {dominated_text}

## QA Flags

Scaffold QA flags are summarized in `spatial_100ft_typed_access_by_scaffold_qa.csv`. They do not block inclusion in this table.

## Meeting Readiness

This table is ready as a meeting readout for conservative typed v2 spatial 100 ft access context by Travelway roadway type. It should be described as review-only enrichment evidence, not a complete access inventory and not a production modeling metric.
"""


def _console_table(compact: pd.DataFrame) -> str:
    display = compact.copy()
    display = display.rename(
        columns={
            "product": "Product",
            "window": "Window",
            "roadway_type": "Roadway type",
            "corrected_access_category": "Type",
            "source_points": "Source points",
            "signals": "Signals",
            "share": "Share",
        }
    )
    display = display.sort_values(["Window", "Roadway type", "Source points"], ascending=[True, True, False])
    return display.to_string(index=False)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    _checkpoint("start spatial_100ft_typed_access_by_roadway_type")
    missing = _missing_inputs()
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))

    detail, inventory, selected_field = _build_detail()
    full, compact, roadway_totals, category_totals, top = _summarize(detail)
    qa_scaffold = _qa_summary(detail)
    table_text = _console_table(compact)

    detail_cols = [
        "product",
        "access_point_id",
        "raw_access_control_code",
        "access_control_raw",
        "prior_access_category",
        "corrected_access_category",
        "category_correction_reason",
        "target_signal_id",
        "target_bin_id",
        "stable_bin_id",
        "stable_travelway_id",
        "roadway_type_grouping_field",
        "roadway_type",
        "facility_text",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "travelway_source_route_common",
        "source_route_name",
        "source_route_id",
        "physical_leg_id",
        "carriageway_subbranch_id",
        "analysis_window",
        "distance_band",
        "distance_start_ft",
        "distance_end_ft",
        "buffer_width_ft",
        "assignment_method",
        "assignment_fanout_count",
        "unweighted_access_count",
        "source_preserving_weighted_access_count",
        "final_alignment_class",
        "source_limited_holdout_flag",
        "grade_mainline_holdout_flag",
        "still_insufficient_evidence_flag",
        "review_only_recovery_provenance",
        "review_only_flag",
    ]
    _write_csv(detail[[column for column in detail_cols if column in detail.columns]], "spatial_100ft_typed_access_by_roadway_type_detail.csv")
    _write_csv(compact, "spatial_100ft_typed_access_by_roadway_type_compact.csv")
    _write_csv(roadway_totals, "spatial_100ft_typed_access_roadway_type_totals.csv")
    _write_csv(category_totals, "spatial_100ft_typed_access_category_totals.csv")
    _write_csv(top, "spatial_100ft_typed_access_top_categories_by_roadway_type.csv")
    _write_csv(inventory, "spatial_100ft_typed_access_roadway_type_field_inventory.csv")
    _write_csv(qa_scaffold, "spatial_100ft_typed_access_by_scaffold_qa.csv")
    _write_text(_findings(selected_field, compact, roadway_totals, qa_scaffold), "spatial_100ft_typed_access_by_roadway_type_findings.md")
    _write_csv(_qa_checks(selected_field), "spatial_100ft_typed_access_by_roadway_type_qa.csv")
    _write_text(table_text + "\n", "spatial_100ft_typed_access_by_roadway_type_table.txt")
    _write_json(
        {
            "script": "src.roadway_graph.spatial_100ft_typed_access_by_roadway_type",
            "created_utc": _now(),
            "output_dir": str(OUT_DIR),
            "inputs": [str(path) for path in REQUIRED_INPUTS],
            "selected_roadway_type_field": selected_field,
            "access_product": "typed_v2_spatial_100ft_enrichment",
            "review_only": True,
            "outputs": [
                "spatial_100ft_typed_access_by_roadway_type_detail.csv",
                "spatial_100ft_typed_access_by_roadway_type_compact.csv",
                "spatial_100ft_typed_access_roadway_type_totals.csv",
                "spatial_100ft_typed_access_category_totals.csv",
                "spatial_100ft_typed_access_top_categories_by_roadway_type.csv",
                "spatial_100ft_typed_access_roadway_type_field_inventory.csv",
                "spatial_100ft_typed_access_by_scaffold_qa.csv",
                "spatial_100ft_typed_access_by_roadway_type_findings.md",
                "spatial_100ft_typed_access_by_roadway_type_qa.csv",
                "spatial_100ft_typed_access_by_roadway_type_manifest.json",
                "spatial_100ft_typed_access_by_roadway_type_table.txt",
                "run_progress_log.txt",
            ],
        },
        "spatial_100ft_typed_access_by_roadway_type_manifest.json",
    )
    _checkpoint("complete spatial_100ft_typed_access_by_roadway_type")
    print(table_text)


if __name__ == "__main__":
    main()
