"""Roadway directionality doctrine and feasibility diagnostic.

Bounded question: determine where downstream/upstream can be assigned directly,
where undivided centerline synthesis is required, and where final analysis bins
must remain bidirectional/undirected for now.

This is review-only doctrine/feasibility work. It does not assign final
downstream/upstream labels, rerun access/crash assignment, calculate rates, or
use crash direction fields.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine"
ANALYSIS = REPO / "work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset"
ENHANCED = REPO / "work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement"
REVIEW = REPO / "work/output/roadway_graph/review/current"
SOURCE_GPKG = REPO / "work/output/roadway_graph/map_review/access_review/access_review.gpkg"

INPUTS = {
    "analysis_signal": ANALYSIS / "analysis_signal.csv",
    "analysis_bin": ANALYSIS / "analysis_bin.csv",
    "analysis_signal_window": ANALYSIS / "analysis_signal_window.csv",
    "analysis_approach_window": ANALYSIS / "analysis_signal_approach_window.csv",
    "analysis_dictionary": ANALYSIS / "analysis_data_dictionary.csv",
    "analysis_manifest": ANALYSIS / "final_analysis_dataset_build_manifest.json",
    "enhanced_bin": ENHANCED / "analysis_bin_enhanced.csv",
    "directionality_field_inventory": ENHANCED / "directionality_field_inventory.csv",
    "directionality_completeness": ENHANCED / "directionality_completeness_summary.csv",
    "enhanced_signal_window": ENHANCED / "analysis_signal_window_enhanced.csv",
    "enhanced_approach_window": ENHANCED / "analysis_signal_approach_window_enhanced.csv",
    "enhanced_manifest": ENHANCED / "directional_numeric_context_enhancement_manifest.json",
    "source_travelway": SOURCE_GPKG,
    "final_summary": REVIEW / "final_leg_corrected_clean_universe_summary/final_leg_corrected_bin_universe.csv",
    "anchor_context": REVIEW / "final_clean_intersection_zone_anchor_context_refresh/final_clean_consolidated_bin_detail_with_anchor_context.csv",
    "residual_context": REVIEW / "final_clean_residual_leg_context_refresh_and_summary/final_clean_leg_corrected_bin_detail.csv",
}


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with (OUT / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")
    print(message, flush=True)


def read_csv(path: Path, **kwargs) -> pd.DataFrame:
    if not path.exists():
        log(f"Missing input: {path}")
        return pd.DataFrame()
    return pd.read_csv(path, **kwargs)


def write_csv(df: pd.DataFrame, name: str) -> None:
    df.to_csv(OUT / name, index=False, lineterminator="\n")
    log(f"Wrote {name}: {len(df):,} rows")


def source_travelway_columns() -> list[str]:
    if not SOURCE_GPKG.exists():
        return []
    with sqlite3.connect(SOURCE_GPKG) as con:
        return [row[1] for row in con.execute("pragma table_info(source_travelway_full)").fetchall()]


def support_inventory(bin_cols: list[str], enhanced_cols: list[str]) -> pd.DataFrame:
    patterns = [
        "one",
        "two",
        "divid",
        "median",
        "route",
        "rte",
        "bearing",
        "measure",
        "carriage",
        "subpart",
        "facility",
        "ramp",
        "direction",
    ]
    rows = []
    for table_name, cols in [
        ("analysis_bin", bin_cols),
        ("analysis_bin_enhanced", enhanced_cols),
        ("source_travelway_full", source_travelway_columns()),
    ]:
        for c in cols:
            if any(p in c.lower() for p in patterns):
                rows.append(
                    {
                        "source_table": table_name,
                        "field_name": c,
                        "directionality_relevance": relevance(c),
                    }
                )
    return pd.DataFrame(rows)


def relevance(field: str) -> str:
    low = field.lower()
    if "bearing" in low:
        return "approach_geometry_support"
    if "median" in low or "divid" in low or "facility" in low or "rim_faci" in low:
        return "divided_undivided_or_configuration_support"
    if "ramp" in low:
        return "ramp_or_interchange_review_support"
    if "route" in low or "rte" in low:
        return "route_identity_direction_suffix_support"
    if "measure" in low:
        return "route_measure_orientation_support"
    if "carriage" in low or "subpart" in low:
        return "carriageway_source_subpart_support"
    if "direction" in low:
        return "direction_field_inventory"
    return "context_support"


def has_route_suffix(row: pd.Series) -> bool:
    text = " ".join(str(row.get(c, "")) for c in ["source_route_name", "source_route_common", "source_route_id", "route_key_name", "route_key_common"])
    return bool(re.search(r"(^|[^A-Z])(NB|SB|EB|WB|NORTH|SOUTH|EAST|WEST)([^A-Z]|$)", text.upper()))


def classify_bin(row: pd.Series) -> tuple[str, str, str]:
    facility = str(row.get("rim_facility_raw", "") or row.get("facility_type", "") or "").lower()
    route_suffix = has_route_suffix(row)
    bearing = pd.notna(row.get("signal_approach_bearing")) or pd.notna(row.get("source_bearing_sector"))
    measure_ready = pd.notna(row.get("source_measure_midpoint")) or (pd.notna(row.get("source_measure_start")) and pd.notna(row.get("source_measure_end")))
    subpart = pd.notna(row.get("carriageway_source_subpart_id"))
    median = str(row.get("median_group", "")).lower()
    ramp = "ramp" in facility or str(row.get("RTE_RAMP_C", "")).strip() not in {"", "nan", "None"}
    one_way = "one-way" in facility or "one way" in facility
    divided = "divided" in facility and "undivided" not in facility
    undivided = "undivided" in facility

    if ramp:
        return (
            "ramp_or_interchange_direction_review",
            "ramp/interchange facility context requires special review; route/measure and bearing may help",
            "medium_review_needed" if (bearing or measure_ready) else "low_review_needed",
        )
    if one_way:
        if route_suffix or measure_ready or bearing:
            return ("one_way_row_direction_supported", "one-way facility plus route/measure/bearing evidence", "medium")
        return ("insufficient_direction_evidence", "one-way facility but missing route/measure/bearing evidence", "low")
    if divided:
        if route_suffix and measure_ready:
            return ("direct_divided_row_direction_supported", "divided Travelway row with route direction suffix and measure context", "high_feasibility")
        if route_suffix or subpart or bearing:
            return ("direct_divided_row_direction_supported", "divided Travelway row with partial route/carriageway/bearing evidence", "medium_feasibility")
        return ("insufficient_direction_evidence", "divided facility but missing route/carriageway/bearing evidence", "low")
    if undivided or median in {"no_median_or_lt_4ft", "unprotected_or_painted_median"}:
        if bearing or measure_ready:
            return (
                "undivided_centerline_requires_synthetic_direction",
                "undivided/shared centerline; approach geometry and route measure may support synthetic sides",
                "medium_synthesis_candidate",
            )
        return (
            "undivided_centerline_requires_synthetic_direction",
            "undivided/shared centerline but missing bearing or measure support",
            "low_synthesis_candidate",
        )
    return ("insufficient_direction_evidence", "roadway configuration is unknown or not directionally interpretable", "low")


def bin_detail() -> pd.DataFrame:
    cols = [
        "stable_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "signal_approach_id",
        "carriageway_source_subpart_id",
        "analysis_window",
        "distance_start_ft",
        "distance_end_ft",
        "final_review_leg_source",
        "final_review_recovery_provenance",
        "rim_facility_raw",
        "rim_facility_secondary_raw",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "median_group",
        "rim_median_raw",
        "signal_approach_bearing",
        "source_bearing_sector",
        "directional_role",
        "directionality_method",
        "directionality_confidence",
        "route_key_common",
        "route_key_name",
    ]
    bins = read_csv(INPUTS["enhanced_bin"], usecols=lambda c: c in cols, low_memory=False)
    classes = bins.apply(classify_bin, axis=1, result_type="expand")
    bins["directionality_support_class"] = classes[0]
    bins["directionality_source_evidence"] = classes[1]
    bins["directionality_confidence"] = classes[2]
    bins["can_assign_final_downstream_upstream_now"] = False
    bins["recommended_directionality_action"] = np.select(
        [
            bins["directionality_support_class"].eq("direct_divided_row_direction_supported"),
            bins["directionality_support_class"].eq("one_way_row_direction_supported"),
            bins["directionality_support_class"].eq("undivided_centerline_requires_synthetic_direction"),
            bins["directionality_support_class"].eq("ramp_or_interchange_direction_review"),
        ],
        [
            "implement_direct_divided_row_direction_rule_next",
            "implement_one_way_direction_rule_with_review",
            "develop_undivided_centerline_synthetic_direction_logic",
            "map_review_or_special_ramp_direction_rule",
        ],
        default="remain_bidirectional_or_undirected",
    )
    return bins


def signal_summary(detail: pd.DataFrame) -> pd.DataFrame:
    total = detail.groupby("stable_signal_id").size().rename("total_bins")
    piv = pd.crosstab(detail["stable_signal_id"], detail["directionality_support_class"])
    out = piv.join(total)
    for col in [
        "direct_divided_row_direction_supported",
        "undivided_centerline_requires_synthetic_direction",
        "one_way_row_direction_supported",
        "ramp_or_interchange_direction_review",
        "insufficient_direction_evidence",
    ]:
        if col not in out:
            out[col] = 0
        out[col + "_share"] = (out[col] / out["total_bins"]).round(4)
    out["directionality_feasibility_status"] = np.select(
        [
            out["direct_divided_row_direction_supported_share"].ge(0.75),
            out["undivided_centerline_requires_synthetic_direction_share"].ge(0.75),
            (out["direct_divided_row_direction_supported"] + out["one_way_row_direction_supported"]).gt(0),
            out["insufficient_direction_evidence_share"].ge(0.75),
        ],
        [
            "suitable_for_direct_divided_directionality_pilot",
            "requires_undivided_centerline_synthesis",
            "mixed_directionality_evidence_review",
            "remain_undirected_for_now",
        ],
        default="mixed_or_partial_directionality_evidence",
    )
    return out.reset_index()


def undivided_feasibility(detail: pd.DataFrame) -> pd.DataFrame:
    und = detail[detail["directionality_support_class"].eq("undivided_centerline_requires_synthetic_direction")]
    if und.empty:
        return pd.DataFrame()
    return (
        und.groupby(["stable_signal_id", "signal_approach_id"], dropna=False)
        .agg(
            bins=("stable_bin_id", "size"),
            bins_with_bearing=("signal_approach_bearing", lambda s: int(s.notna().sum())),
            bins_with_measure=("source_measure_midpoint", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            travelways=("stable_travelway_id", "nunique"),
        )
        .reset_index()
        .assign(
            synthesis_feasible_at_signal_level=lambda d: d["bins_with_measure"].gt(0),
            synthesis_feasible_at_approach_level=lambda d: d["bins_with_bearing"].gt(0) & d["bins_with_measure"].gt(0),
            synthesis_feasible_at_bin_level=False,
            synthesis_note="Synthetic upstream/downstream side construction required; final labels not assigned in this diagnostic.",
        )
    )


def divided_feasibility(detail: pd.DataFrame) -> pd.DataFrame:
    div = detail[detail["directionality_support_class"].isin(["direct_divided_row_direction_supported", "one_way_row_direction_supported", "ramp_or_interchange_direction_review"])]
    if div.empty:
        return pd.DataFrame()
    return (
        div.groupby(["stable_signal_id", "signal_approach_id", "directionality_support_class"], dropna=False)
        .agg(
            bins=("stable_bin_id", "size"),
            bins_with_route_suffix=("stable_bin_id", lambda s: int(detail.loc[s.index].apply(has_route_suffix, axis=1).sum())),
            bins_with_measure=("source_measure_midpoint", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
            bins_with_bearing=("signal_approach_bearing", lambda s: int(s.notna().sum())),
        )
        .reset_index()
        .assign(
            direct_directionality_feasible=lambda d: d["directionality_support_class"].isin(["direct_divided_row_direction_supported", "one_way_row_direction_supported"]) & d["bins_with_measure"].gt(0),
            direct_directionality_note="Direct rule feasible only after validating Travelway row orientation relative to signal anchor.",
        )
    )


def doctrine_table() -> pd.DataFrame:
    rows = [
        ("downstream", "Movement away from the signal along the relevant approach after crossing the signalized intersection.", "Use only when roadway row direction or validated synthetic centerline direction supports it.", "Never derive from crash direction fields."),
        ("upstream", "Movement toward the signal along the relevant approach before reaching the signalized intersection.", "Use only when roadway row direction or validated synthetic centerline direction supports it.", "Never derive from crash direction fields."),
        ("direct divided row", "A divided or one-way Travelway row whose row direction, route suffix, measure direction, and geometry can be validated.", "Good first implementation target.", "Requires validation of Travelway row orientation."),
        ("undivided centerline", "A shared centerline representing both directions.", "Requires synthetic side/direction construction from approach geometry and route measure.", "Do not assign final upstream/downstream until synthetic logic is validated."),
        ("unclear direction", "Insufficient row direction, measure, route suffix, or geometry evidence.", "Remain bidirectional/undirected.", "Do not force labels for coverage."),
        ("crash direction", "Crash record directional attributes.", "Inventory only if needed elsewhere.", "Not used to define scaffold directionality or downstream/upstream."),
    ]
    return pd.DataFrame(rows, columns=["concept", "plain_language_definition", "when_valid", "caveat"])


def recommendation(detail: pd.DataFrame, signal: pd.DataFrame) -> pd.DataFrame:
    counts = detail["directionality_support_class"].value_counts().to_dict()
    direct = counts.get("direct_divided_row_direction_supported", 0) + counts.get("one_way_row_direction_supported", 0)
    und = counts.get("undivided_centerline_requires_synthetic_direction", 0)
    rec = "implement_direct_divided_road_directionality_first" if direct > 0 else "defer_directionality_and_continue_non_directional_figures"
    if und > direct:
        rec = "develop_undivided_centerline_synthesis_after_direct_divided_pilot"
    return pd.DataFrame(
        [
            {
                "recommendation": rec,
                "direct_supported_bins": direct,
                "undivided_synthesis_bins": und,
                "unclear_or_review_bins": len(detail) - direct - und,
                "rationale": "Do not assign final downstream/upstream labels globally. Pilot direct divided/one-way row direction first, then build undivided centerline synthesis.",
            }
        ]
    )


def findings(detail: pd.DataFrame, sig: pd.DataFrame, rec: pd.DataFrame) -> str:
    counts = detail["directionality_support_class"].value_counts()
    direct = int(counts.get("direct_divided_row_direction_supported", 0) + counts.get("one_way_row_direction_supported", 0))
    und = int(counts.get("undivided_centerline_requires_synthetic_direction", 0))
    unclear = int(counts.get("insufficient_direction_evidence", 0))
    ramp = int(counts.get("ramp_or_interchange_direction_review", 0))
    return f"""# Final Analysis Directionality Doctrine Findings

## Answers
1. Directionality support fields include facility/divided-undivided fields, route names/common IDs with directional suffixes, route measure fields, source bearing sectors, median fields, ramp indicators, and carriageway/source subpart fields.
2. Bins with direct divided/one-way row direction support: {direct:,}.
3. Bins requiring undivided centerline synthetic direction logic: {und:,}.
4. Bins remaining unclear/insufficient: {unclear:,}; ramp/interchange review bins: {ramp:,}.
5. Downstream/upstream should not be assigned at bin level globally now. Direct divided/one-way bins are feasible candidates, but Travelway row orientation still needs validation.
6. Signal-approach downstream/upstream is not ready globally. Undivided centerlines need synthetic side/direction construction.
7. Doctrine: direct Travelway row direction is valid only when row direction, route/measure orientation, and signal-relative geometry are validated; undivided centerlines require synthetic direction; unclear bins remain bidirectional/undirected; crash direction is not used.
8. Recommended next pass: {rec['recommendation'].iloc[0]}.
"""


def qa_table() -> pd.DataFrame:
    rows = [
        ("no_active_outputs_modified", True, "Outputs written only to analysis/current directionality doctrine folder."),
        ("no_records_promoted", True, "Review-only doctrine diagnostic."),
        ("no_access_crash_assignment", True, "No assignment logic run."),
        ("no_rates_models", True, "No rates/models calculated."),
        ("crash_direction_fields_not_read_or_used", True, "Crash files were not read."),
        ("downstream_upstream_not_guessed", True, "Final downstream/upstream labels are not assigned where evidence is insufficient."),
        ("outputs_review_only_folder", True, str(OUT)),
    ]
    return pd.DataFrame(rows, columns=["qa_check", "passed", "note"])


def manifest(outputs: Iterable[str]) -> dict[str, object]:
    return {
        "script": "src.roadway_graph.build.final_analysis_directionality_doctrine",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "output_folder": str(OUT.relative_to(REPO)),
        "inputs": {k: str(v.relative_to(REPO)) for k, v in INPUTS.items() if v.exists()},
        "outputs": list(outputs),
        "review_only": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Starting directionality doctrine diagnostic.")
    bin_cols = pd.read_csv(INPUTS["analysis_bin"], nrows=0).columns.tolist()
    enh_cols = pd.read_csv(INPUTS["enhanced_bin"], nrows=0).columns.tolist()
    inv = support_inventory(bin_cols, enh_cols)
    detail = bin_detail()
    sig = signal_summary(detail)
    und = undivided_feasibility(detail)
    div = divided_feasibility(detail)
    doc = doctrine_table()
    rec = recommendation(detail, sig)
    write_csv(inv, "direction_support_field_inventory.csv")
    write_csv(detail, "bin_directionality_support_detail.csv")
    write_csv(sig, "signal_directionality_feasibility_summary.csv")
    write_csv(und, "undivided_centerline_synthesis_feasibility.csv")
    write_csv(div, "divided_row_directionality_feasibility.csv")
    write_csv(doc, "directionality_doctrine.csv")
    write_csv(rec, "directionality_next_action_recommendation.csv")
    (OUT / "final_analysis_directionality_doctrine_findings.md").write_text(findings(detail, sig, rec), encoding="utf-8")
    log("Wrote findings memo.")
    write_csv(qa_table(), "final_analysis_directionality_doctrine_qa.csv")
    outputs = sorted(p.name for p in OUT.iterdir() if p.is_file() and p.name != "final_analysis_directionality_doctrine_manifest.json")
    (OUT / "final_analysis_directionality_doctrine_manifest.json").write_text(json.dumps(manifest(outputs), indent=2), encoding="utf-8")
    log("Wrote manifest.")
    log("Completed directionality doctrine diagnostic.")


if __name__ == "__main__":
    main()
