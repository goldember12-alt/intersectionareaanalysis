"""Review-only directionality proposal for exact corridor-linked bins.

This script consumes the staged source-signal/Travelway projection indexes and
builds proposals only for unresolved bins that link to exactly one
signal-bounded Travelway corridor interval. It does not mutate bin_context,
canonical products, source artifacts, or MVP products.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/exact_corridor_link_directionality_proposal"
ARTIFACTS = REPO_ROOT / "artifacts/normalized"
PROJECTION_REVIEW = REPO_ROOT / "work/roadway_graph/review/source_signal_travelway_projection_index"
CASE_OUT = REPO_ROOT / "work/roadway_graph/review/corridor_side_geometry_engine_case_tests"
GLOBAL_OUT = REPO_ROOT / "work/roadway_graph/review/global_corridor_side_geometry_directionality_proposal"

BIN_CONTEXT = STAGING / "bin_context.parquet"
PROJECTION_INDEX = STAGING / "source_signal_travelway_projection_index.parquet"
CORRIDOR_INDEX = STAGING / "signal_bounded_travelway_corridor_index.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
CONTINUATION_CORRIDORS = STAGING / "continuation_corridors.parquet"
SIGNALS = ARTIFACTS / "signals.parquet"
ROADS = ARTIFACTS / "roads.parquet"

CURRENT_DIRECTION_READY_UNITS = 98_831
CONSERVATIVE_TARGET = 109_842
UPPER_TARGET = 132_866
EXPECTED_EXACT_LINKED_BINS = 7_959
MEASURE_EPS = 1.0e-7
TOO_CLOSE_MEASURE = 0.001

CASE_IDS = {
    "case_2": "sig_05a2cb689cbc4f27814d",
    "case_3": "sig_439930214d7b1b49426f",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} - {message}\n")


def write_csv(name: str, df: pd.DataFrame) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / name, index=False)


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>"])


def side_values(df: pd.DataFrame) -> pd.Series:
    side = df["upstream_downstream"] if "upstream_downstream" in df.columns else pd.Series(pd.NA, index=df.index)
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonmissing(side), df["upstream_downstream_values"])
    return side


def route_token(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper().strip()
    match = re.search(r"(NB|SB|EB|WB)$", text)
    return match.group(1) if match else ""


def route_base(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper().strip()
    token = route_token(text)
    return text[: -len(token)].strip() if token else text


def opposite_route(route: str) -> str:
    token = route_token(route)
    if not token:
        return ""
    opp = {"NB": "SB", "SB": "NB", "EB": "WB", "WB": "EB"}.get(token, "")
    return route[: -len(token)] + opp if opp else ""


def side_from_token(token: str, interval_side: str) -> str:
    if token in {"NB", "EB"}:
        return "upstream" if interval_side == "before_signal_interval" else "downstream"
    if token in {"SB", "WB"}:
        return "downstream" if interval_side == "before_signal_interval" else "upstream"
    return ""


def load_inputs() -> dict[str, pd.DataFrame]:
    bin_cols = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "source_measure_midpoint",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "distance_band_v2",
        "signal_approach_id_v2",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "rim_facility_raw",
        "bin_row_origin",
        "generated_bin_flag",
        "continuation_corridor_id",
        "upstream_downstream_values",
        "upstream_downstream",
        "directionality_status",
        "directionality_recovery_status",
    ]
    available = pd.read_parquet(BIN_CONTEXT, columns=None).columns
    return {
        "bin_context": pd.read_parquet(BIN_CONTEXT, columns=[c for c in bin_cols if c in available]),
        "projection": pd.read_parquet(PROJECTION_INDEX),
        "corridors": pd.read_parquet(CORRIDOR_INDEX),
        "signal_approaches": pd.read_parquet(SIGNAL_APPROACHES),
        "continuation_corridors": pd.read_parquet(CONTINUATION_CORRIDORS),
        "signals": pd.read_parquet(SIGNALS, columns=["GLOBALID", "geometry"]),
        "roads": pd.read_parquet(ROADS, columns=["RTE_NM", "RTE_COMMON", "RIM_FACILI", "RIM_TRAVEL", "RIM_COUPLE", "FROM_MEASURE", "TO_MEASURE", "RTE_ID"]),
        "projection_link_summary": pd.read_csv(PROJECTION_REVIEW / "unresolved_bin_to_corridor_link_summary.csv") if (PROJECTION_REVIEW / "unresolved_bin_to_corridor_link_summary.csv").exists() else pd.DataFrame(),
        "case_results": pd.read_csv(CASE_OUT / "case_test_pass_fail_summary.csv") if (CASE_OUT / "case_test_pass_fail_summary.csv").exists() else pd.DataFrame(),
        "global_results": pd.read_csv(GLOBAL_OUT / "manual_case_global_validation.csv") if (GLOBAL_OUT / "manual_case_global_validation.csv").exists() else pd.DataFrame(),
    }


def unresolved_universe(bin_context: pd.DataFrame) -> pd.DataFrame:
    side = side_values(bin_context)
    status_text = (
        bin_context.get("directionality_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
        + "|"
        + bin_context.get("directionality_recovery_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
    )
    mask = (~nonmissing(side)) | status_text.str.contains("not_recovered|unresolved", regex=True, na=False)
    out = bin_context[mask].copy()
    out["distance_band_out"] = out.get("distance_band_v2", out.get("distance_band"))
    out["_existing_side"] = side.loc[out.index]
    return out


def bin_measure(row: pd.Series) -> float:
    mid = pd.to_numeric(pd.Series([row.get("source_measure_midpoint")]), errors="coerce").iloc[0]
    if pd.notna(mid):
        return float(mid)
    start = pd.to_numeric(pd.Series([row.get("source_measure_start")]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([row.get("source_measure_end")]), errors="coerce").iloc[0]
    if pd.notna(start) and pd.notna(end):
        return (float(start) + float(end)) / 2.0
    return math.nan


def interval_matches(measure: float, corridor: pd.Series) -> list[str]:
    matches: list[str] = []
    before_from = pd.to_numeric(pd.Series([corridor.get("before_interval_from_measure")]), errors="coerce").iloc[0]
    before_to = pd.to_numeric(pd.Series([corridor.get("before_interval_to_measure")]), errors="coerce").iloc[0]
    after_from = pd.to_numeric(pd.Series([corridor.get("after_interval_from_measure")]), errors="coerce").iloc[0]
    after_to = pd.to_numeric(pd.Series([corridor.get("after_interval_to_measure")]), errors="coerce").iloc[0]
    if pd.notna(before_from) and pd.notna(before_to) and float(before_from) - MEASURE_EPS <= measure <= float(before_to) + MEASURE_EPS:
        matches.append("before_signal_interval")
    if pd.notna(after_from) and pd.notna(after_to) and float(after_from) - MEASURE_EPS <= measure <= float(after_to) + MEASURE_EPS:
        matches.append("after_signal_interval")
    return matches


def classify_roadway_representation(row: pd.Series, route_names: set[str]) -> str:
    route = str(row.get("source_route_name", ""))
    token = route_token(route)
    text = " ".join(
        str(row.get(c, ""))
        for c in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw", "roadway_configuration"]
    ).lower()
    if "one-way" in text or "one way" in text:
        return "one_way_direct" if token else "unknown"
    if "divided" in text and "undivided" not in text:
        if token and opposite_route(route) in route_names:
            return "true_paired_divided_carriageway"
        if token:
            return "divided_centerline_proxy"
        return "divided_centerline_proxy"
    if "undivided" in text or "two-way" in text or "two way" in text:
        return "undivided_centerline" if token else "unknown"
    return "unknown"


def method_and_status(representation: str, token: str) -> tuple[str, str, str]:
    if representation == "true_paired_divided_carriageway":
        if token in {"SB", "WB"}:
            return "reverse_carriageway_signal_bounded_corridor", "proposed_reverse_carriageway_signal_bounded_corridor", "high"
        return "direct_divided_signal_bounded_corridor", "proposed_direct_divided_signal_bounded_corridor", "high"
    if representation == "undivided_centerline":
        return "synthetic_undivided_signal_bounded_corridor", "proposed_synthetic_undivided_signal_bounded_corridor", "high"
    if representation == "divided_centerline_proxy":
        return "divided_centerline_proxy_signal_bounded_corridor", "proposed_divided_centerline_proxy_signal_bounded_corridor", "medium"
    if representation == "one_way_direct":
        return "one_way_signal_bounded_corridor", "proposed_one_way_signal_bounded_corridor", "high"
    return "", "", "none"


def build_exact_link_inventory(unresolved: pd.DataFrame, corridors: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    usable_corridors = corridors[corridors["corridor_confidence"].isin(["high", "medium"])].copy()
    road_config = roads.groupby("RTE_NM")["RIM_FACILI"].agg(lambda s: "|".join(sorted(set(s.dropna().astype(str))))).reset_index().rename(columns={"RTE_NM": "source_route_name", "RIM_FACILI": "roadway_configuration"})
    usable_corridors = usable_corridors.merge(road_config.rename(columns={"source_route_name": "route_name"}), on="route_name", how="left")
    route_names = set(roads["RTE_NM"].dropna().astype(str)).union(set(corridors["route_name"].dropna().astype(str))).union(set(unresolved["source_route_name"].dropna().astype(str)))
    route_map = {k: v for k, v in usable_corridors.groupby(["stable_signal_id", "route_name"], dropna=False)}

    records: list[dict[str, Any]] = []
    out_of_scope: list[dict[str, Any]] = []
    for _, b in unresolved.iterrows():
        measure = bin_measure(b)
        base = {
            "stable_bin_id": b.get("stable_bin_id"),
            "stable_signal_id": b.get("stable_signal_id"),
            "signal_approach_id_v2": b.get("signal_approach_id_v2"),
            "distance_band": b.get("distance_band_out"),
            "distance_start_ft": b.get("distance_start_ft"),
            "distance_end_ft": b.get("distance_end_ft"),
            "bin_row_origin": b.get("bin_row_origin"),
            "generated_bin_flag": b.get("generated_bin_flag"),
            "continuation_corridor_id": b.get("continuation_corridor_id"),
            "stable_travelway_id": b.get("stable_travelway_id"),
            "source_route_id": b.get("source_route_id"),
            "source_route_name": b.get("source_route_name"),
            "source_route_common": b.get("source_route_common"),
            "source_measure_start": b.get("source_measure_start"),
            "source_measure_end": b.get("source_measure_end"),
            "source_measure_midpoint": b.get("source_measure_midpoint"),
            "bin_measure_for_linkage": measure if not math.isnan(measure) else pd.NA,
            "existing_roadway_division_context": b.get("existing_roadway_division_context"),
            "generated_roadway_division_context": b.get("generated_roadway_division_context"),
            "rim_facility_raw": b.get("rim_facility_raw"),
        }
        if math.isnan(measure):
            out_of_scope.append({**base, "link_status": "out_of_scope_missing_bin_measure", "linked_corridor_count": 0})
            continue
        cands = route_map.get((b.get("stable_signal_id"), b.get("source_route_name")))
        if cands is None or cands.empty:
            out_of_scope.append({**base, "link_status": "out_of_scope_no_corridor", "linked_corridor_count": 0})
            continue
        linked_rows = []
        for _, c in cands.iterrows():
            sides = interval_matches(measure, c)
            for side in sides:
                linked_rows.append((c, side))
        if len(linked_rows) == 0:
            out_of_scope.append({**base, "link_status": "out_of_scope_outside_corridor_intervals", "linked_corridor_count": 0})
            continue
        if len(linked_rows) > 1:
            out_of_scope.append({**base, "link_status": "out_of_scope_multiple_corridors", "linked_corridor_count": len(linked_rows)})
            continue
        c, side = linked_rows[0]
        representation = classify_roadway_representation(pd.concat([b, c]), route_names)
        records.append({
            **base,
            "link_status": "linked_to_single_corridor_interval",
            "linked_corridor_count": 1,
            "linked_interval_side": side,
            "corridor_index_id": c.get("corridor_index_id"),
            "reviewed_source_signal_globalid": c.get("reviewed_source_signal_globalid"),
            "reviewed_signal_estimated_measure": c.get("reviewed_signal_estimated_measure"),
            "before_endpoint_globalid": c.get("before_endpoint_globalid"),
            "before_endpoint_stable_signal_id": c.get("before_endpoint_stable_signal_id"),
            "before_endpoint_measure": c.get("before_endpoint_measure"),
            "after_endpoint_globalid": c.get("after_endpoint_globalid"),
            "after_endpoint_stable_signal_id": c.get("after_endpoint_stable_signal_id"),
            "after_endpoint_measure": c.get("after_endpoint_measure"),
            "boundary_method": c.get("boundary_method"),
            "endpoint_source_only_used": c.get("endpoint_source_only_used"),
            "corridor_confidence": c.get("corridor_confidence"),
            "road_row_id": c.get("road_row_id"),
            "roadway_configuration": c.get("roadway_configuration"),
            "route_base": c.get("route_base"),
            "carriageway_direction_token": c.get("carriageway_direction_token") or route_token(b.get("source_route_name")),
            "roadway_representation": representation,
        })
    return pd.DataFrame(records), pd.DataFrame(out_of_scope)


def build_proposals(candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    proposals: list[dict[str, Any]] = []
    no_rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        signal_measure = pd.to_numeric(pd.Series([row.get("reviewed_signal_estimated_measure")]), errors="coerce").iloc[0]
        bin_m = pd.to_numeric(pd.Series([row.get("bin_measure_for_linkage")]), errors="coerce").iloc[0]
        if pd.isna(signal_measure) or pd.isna(bin_m):
            no_rows.append(no_proposal_row(row, "no_proposal_missing_required_fields"))
            continue
        if abs(float(bin_m) - float(signal_measure)) <= TOO_CLOSE_MEASURE:
            no_rows.append(no_proposal_row(row, "no_proposal_bin_overlaps_signal_split"))
            continue
        interval_side = row.get("linked_interval_side")
        if interval_side not in {"before_signal_interval", "after_signal_interval"}:
            no_rows.append(no_proposal_row(row, "no_proposal_bin_outside_corridor_interval"))
            continue
        token = str(row.get("carriageway_direction_token") or route_token(row.get("source_route_name")))
        proposed_side = side_from_token(token, str(interval_side))
        if not proposed_side:
            no_rows.append(no_proposal_row(row, "no_proposal_side_mapping_unknown"))
            continue
        method, status, confidence = method_and_status(str(row.get("roadway_representation")), token)
        if not method:
            no_rows.append(no_proposal_row(row, "no_proposal_roadway_type_unclear"))
            continue
        if str(row.get("corridor_confidence")) == "medium" and confidence == "high":
            confidence = "medium"
        proposals.append({
            **row.to_dict(),
            "proposed_upstream_downstream": proposed_side,
            "proposal_status": status,
            "directionality_method": method,
            "proposal_confidence": confidence,
            "evidence_fields": json.dumps({
                "rule": "exact_single_signal_bounded_corridor_interval",
                "corridor_index_id": row.get("corridor_index_id"),
                "interval_side": interval_side,
                "route_token": token,
                "boundary_method": row.get("boundary_method"),
                "endpoint_source_only_used": bool(row.get("endpoint_source_only_used")),
            }, sort_keys=True),
        })
    return pd.DataFrame(proposals), pd.DataFrame(no_rows)


def no_proposal_row(row: pd.Series, reason: str) -> dict[str, Any]:
    keep = row.to_dict()
    keep["proposal_status"] = reason
    keep["no_proposal_reason"] = reason
    return keep


def unit_summary(proposals: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if proposals.empty:
        return pd.DataFrame(columns=group_cols + ["proposed_bins", "proposed_units"])
    bins = proposals.groupby(group_cols, dropna=False).size().reset_index(name="proposed_bins")
    unit_cols = ["stable_signal_id", "signal_approach_id_v2", "proposed_upstream_downstream", "distance_band"]
    units = proposals.drop_duplicates(unit_cols + group_cols).groupby(group_cols, dropna=False).size().reset_index(name="proposed_units")
    return bins.merge(units, on=group_cols, how="left")


def proposal_summary(candidates: pd.DataFrame, proposals: pd.DataFrame, no_rows: pd.DataFrame, out_of_scope: pd.DataFrame) -> pd.DataFrame:
    high = proposals[proposals["proposal_confidence"].eq("high")] if not proposals.empty else proposals
    high_units = high.drop_duplicates(["stable_signal_id", "signal_approach_id_v2", "proposed_upstream_downstream", "distance_band"]).shape[0] if not high.empty else 0
    all_units = proposals.drop_duplicates(["stable_signal_id", "signal_approach_id_v2", "proposed_upstream_downstream", "distance_band"]).shape[0] if not proposals.empty else 0
    ready = CURRENT_DIRECTION_READY_UNITS + high_units
    return pd.DataFrame([{
        "exact_corridor_candidate_bins": int(len(candidates)),
        "expected_exact_corridor_candidate_bins": EXPECTED_EXACT_LINKED_BINS,
        "candidate_count_matches_expected": bool(len(candidates) == EXPECTED_EXACT_LINKED_BINS),
        "proposed_bins": int(len(proposals)),
        "high_confidence_proposed_bins": int(len(high)),
        "proposed_units": int(all_units),
        "high_confidence_proposed_units": int(high_units),
        "no_proposal_candidate_bins": int(len(no_rows)),
        "out_of_scope_unresolved_bins": int(len(out_of_scope)),
        "direction_ready_units_if_high_confidence_applied": int(ready),
        "percent_of_conservative_target_reached": round(ready / CONSERVATIVE_TARGET * 100.0, 2),
        "remaining_gap_to_conservative_target": int(max(CONSERVATIVE_TARGET - ready, 0)),
        "remaining_gap_to_upper_bound_target": int(max(UPPER_TARGET - ready, 0)),
    }])


def case_checks(candidates: pd.DataFrame, proposals: pd.DataFrame, no_rows: pd.DataFrame, out_of_scope: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for case_id, sid in CASE_IDS.items():
        cand = candidates[candidates["stable_signal_id"].astype(str).eq(sid)] if not candidates.empty else candidates
        prop = proposals[proposals["stable_signal_id"].astype(str).eq(sid)] if not proposals.empty else proposals
        no = no_rows[no_rows["stable_signal_id"].astype(str).eq(sid)] if not no_rows.empty else no_rows
        out = out_of_scope[out_of_scope["stable_signal_id"].astype(str).eq(sid)] if not out_of_scope.empty else out_of_scope
        represented = len(cand) > 0
        if represented:
            explanation = ""
        elif not out.empty:
            explanation = "|".join(sorted(out["link_status"].dropna().astype(str).unique()))
        else:
            explanation = "no_unresolved_rows_for_case_signal"
        rows.append({
            "case_id": case_id,
            "stable_signal_id": sid,
            "represented_in_exact_corridor_candidates": bool(represented),
            "candidate_bins": int(len(cand)),
            "proposed_bins": int(len(prop)),
            "high_confidence_proposed_bins": int(len(prop[prop["proposal_confidence"].eq("high")])) if not prop.empty else 0,
            "no_proposal_bins": int(len(no)),
            "out_of_scope_bins": int(len(out)),
            "explanation_if_not_represented": explanation,
        })
    return pd.DataFrame(rows)


def conflict_checks(candidates: pd.DataFrame, proposals: pd.DataFrame, bin_context: pd.DataFrame, exact_count_expected: int) -> pd.DataFrame:
    rows = [
        {"check_name": "no_staged_or_canonical_mutation", "status": "pass", "detail": "Script writes only review outputs."},
        {"check_name": "no_crash_direction_fields_used", "status": "pass", "detail": "No crash files or crash direction fields are read."},
        {"check_name": "exact_corridor_candidate_count", "status": "pass" if len(candidates) == exact_count_expected else "review", "detail": f"candidates={len(candidates)} expected={exact_count_expected}"},
    ]
    multi_corr = int((candidates.groupby("stable_bin_id")["corridor_index_id"].nunique() > 1).sum()) if not candidates.empty else 0
    rows.append({"check_name": "every_candidate_has_exactly_one_corridor", "status": "pass" if multi_corr == 0 else "fail", "detail": f"multi-corridor candidate bins={multi_corr}"})
    if proposals.empty:
        multi_side = 0
    else:
        multi_side = int((proposals.groupby("stable_bin_id")["proposed_upstream_downstream"].nunique() > 1).sum())
    rows.append({"check_name": "every_proposed_bin_has_one_side", "status": "pass" if multi_side == 0 else "fail", "detail": f"multi-side proposed bins={multi_side}"})
    side = side_values(bin_context)
    existing = bin_context[["stable_bin_id"]].copy()
    existing["_existing_side"] = side
    if proposals.empty:
        conflicts = 0
    else:
        joined = proposals[["stable_bin_id", "proposed_upstream_downstream"]].merge(existing, on="stable_bin_id", how="left")
        conflicts = int((nonmissing(joined["_existing_side"]) & joined["_existing_side"].astype(str).ne(joined["proposed_upstream_downstream"].astype(str))).sum())
    rows.append({"check_name": "no_conflict_with_existing_staged_directionality", "status": "pass" if conflicts == 0 else "fail", "detail": f"conflicting existing side rows={conflicts}"})
    unclear = int(proposals["roadway_representation"].astype(str).eq("unknown").sum()) if not proposals.empty else 0
    rows.append({"check_name": "method_provenance_clear", "status": "pass" if unclear == 0 else "fail", "detail": f"unknown representation proposals={unclear}"})
    rows.append({"check_name": "no_upstream_downstream_written_to_staging", "status": "pass", "detail": "No staged Parquet was written."})
    return pd.DataFrame(rows)


def recommendations(summary: pd.DataFrame, checks: pd.DataFrame, by_method: pd.DataFrame) -> pd.DataFrame:
    failed = checks["status"].eq("fail").any()
    high_bins = int(summary.iloc[0]["high_confidence_proposed_bins"])
    if failed:
        rec = "do_not_apply_due_to_conflicts"
    elif high_bins > 0:
        rec = "implement_high_confidence_exact_corridor_proposals_to_staging"
    elif not by_method.empty:
        rec = "implement_specific_method_first"
    else:
        rec = "needs_corridor_side_rule_revision"
    return pd.DataFrame([{
        "recommendation": rec,
        "high_confidence_proposed_bins": high_bins,
        "remaining_gap_to_conservative_target": int(summary.iloc[0]["remaining_gap_to_conservative_target"]),
        "next_step": "Review this proposal package; any staging update must be a separate explicitly approved mutation task.",
    }])


def write_findings(summary: pd.DataFrame, by_method: pd.DataFrame, case_check: pd.DataFrame, no_reasons: pd.DataFrame, checks: pd.DataFrame, recs: pd.DataFrame) -> None:
    s = summary.iloc[0]
    case2 = case_check[case_check["case_id"].eq("case_2")].iloc[0]
    case3 = case_check[case_check["case_id"].eq("case_3")].iloc[0]
    safety_ok = not checks["status"].eq("fail").any()
    text = f"""# Exact Corridor-Link Directionality Proposal

## What Exact-Corridor Bins Were Tested

This review-only run tested unresolved bins that link to exactly one signal-bounded Travelway corridor interval from the staged corridor index. Candidate bins: {int(s['exact_corridor_candidate_bins'])}; expected from the projection index QA: {int(s['expected_exact_corridor_candidate_bins'])}; match: {bool(s['candidate_count_matches_expected'])}.

## How Corridor Side Was Mapped To Upstream/Downstream

Each candidate was classified as before or after the reviewed signal within its single corridor interval. NB/EB route tokens map before to upstream and after to downstream; SB/WB reverse that mapping. Methods remain distinct for true paired divided, reverse carriageway, synthetic undivided, divided-centerline/proxy, and one-way/direct evidence.

## Proposal Counts And Unit Recovery

Proposed bins: {int(s['proposed_bins'])}. High-confidence proposed bins: {int(s['high_confidence_proposed_bins'])}. Proposed units: {int(s['proposed_units'])}. High-confidence proposed units: {int(s['high_confidence_proposed_units'])}.

By method: `{by_method.to_dict('records')}`.

If high-confidence proposals were later applied in a separate approved mutation task, direction-ready units would reach {int(s['direction_ready_units_if_high_confidence_applied'])}, or {s['percent_of_conservative_target_reached']}% of the conservative target, leaving a gap of {int(s['remaining_gap_to_conservative_target'])}.

## Case 2 And Case 3 Results

Case 2 represented: {bool(case2['represented_in_exact_corridor_candidates'])}; candidate bins: {int(case2['candidate_bins'])}; proposed bins: {int(case2['proposed_bins'])}; explanation: {case2['explanation_if_not_represented'] or ''}.

Case 3 represented: {bool(case3['represented_in_exact_corridor_candidates'])}; candidate bins: {int(case3['candidate_bins'])}; proposed bins: {int(case3['proposed_bins'])}; explanation: {case3['explanation_if_not_represented'] or ''}.

## What Remained Unresolved And Why

No-proposal candidate reasons: `{no_reasons.to_dict('records')}`. Bins with no corridor, outside intervals, multiple corridors, or missing bin measure were out of scope and not evaluated for side assignment.

## Whether High-Confidence Proposals Are Safe To Apply

High-confidence proposals are review-only. Conflict checks passed: {safety_ok}. They are not applied here and should only be used in a separate approved mutation task.

## Recommended Next Step

Recommendation: `{recs.iloc[0]['recommendation']}`.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "progress_log.md").write_text("# Progress Log\n", encoding="utf-8")
    log("Loading staged bin_context, projection/corridor indexes, source artifacts, and prior review outputs.")
    data = load_inputs()

    log("Rebuilding unresolved universe and exact-one-corridor candidate inventory.")
    unresolved = unresolved_universe(data["bin_context"])
    candidates, out_of_scope = build_exact_link_inventory(unresolved, data["corridors"], data["roads"])

    log("Mapping exact corridor interval side to review-only upstream/downstream proposals.")
    proposals, no_rows = build_proposals(candidates)

    log("Building summaries, hard acceptance checks, and review outputs.")
    summary = proposal_summary(candidates, proposals, no_rows, out_of_scope)
    by_method = unit_summary(proposals, ["proposal_status", "directionality_method"]) if not proposals.empty else pd.DataFrame(columns=["proposal_status", "directionality_method", "proposed_bins", "proposed_units"])
    by_distance = unit_summary(proposals, ["distance_band"]) if not proposals.empty else pd.DataFrame(columns=["distance_band", "proposed_bins", "proposed_units"])
    by_signal = unit_summary(proposals, ["stable_signal_id"]) if not proposals.empty else pd.DataFrame(columns=["stable_signal_id", "proposed_bins", "proposed_units"])
    by_conf = unit_summary(proposals, ["proposal_confidence"]) if not proposals.empty else pd.DataFrame(columns=["proposal_confidence", "proposed_bins", "proposed_units"])
    no_reasons = no_rows.groupby("no_proposal_reason", dropna=False).size().reset_index(name="bins").sort_values("bins", ascending=False) if not no_rows.empty else pd.DataFrame(columns=["no_proposal_reason", "bins"])
    out_scope_summary = out_of_scope.groupby("link_status", dropna=False).size().reset_index(name="bins").sort_values("bins", ascending=False) if not out_of_scope.empty else pd.DataFrame(columns=["link_status", "bins"])
    case_check = case_checks(candidates, proposals, no_rows, out_of_scope)
    checks = conflict_checks(candidates, proposals, data["bin_context"], EXPECTED_EXACT_LINKED_BINS)
    recs = recommendations(summary, checks, by_method)

    candidate_out = candidates.drop(columns=[c for c in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"] if c in candidates.columns])
    write_csv("exact_corridor_candidate_bin_inventory.csv", candidate_out)
    write_csv("exact_corridor_directionality_proposal.csv", proposals)
    write_csv("exact_corridor_directionality_proposal_summary.csv", summary)
    write_csv("proposal_no_assignment_reasons.csv", no_reasons)
    write_csv("proposed_recovery_by_method.csv", by_method)
    write_csv("proposed_recovery_by_distance_band.csv", by_distance)
    write_csv("proposed_recovery_by_signal.csv", by_signal)
    write_csv("proposed_recovery_by_confidence.csv", by_conf)
    write_csv("case2_case3_exact_corridor_check.csv", case_check)
    write_csv("conflict_and_safety_checks.csv", checks)
    write_csv("recommended_next_actions.csv", recs)
    write_csv("out_of_scope_link_status_summary.csv", out_scope_summary)
    write_findings(summary, by_method, case_check, no_reasons, checks, recs)

    manifest = {
        "created_utc": now_iso(),
        "bounded_question": "Review-only directionality proposal for unresolved bins linked to exactly one signal-bounded Travelway corridor interval.",
        "source_inputs": [rel(p) for p in [BIN_CONTEXT, PROJECTION_INDEX, CORRIDOR_INDEX, SIGNAL_APPROACHES, CONTINUATION_CORRIDORS, SIGNALS, ROADS]],
        "prior_review_inputs": [rel(PROJECTION_REVIEW), rel(CASE_OUT), rel(GLOBAL_OUT)],
        "output_dir": rel(OUT_DIR),
        "summary": summary.iloc[0].to_dict(),
        "out_of_scope_summary": out_scope_summary.to_dict("records"),
        "no_mutation": True,
        "crash_direction_fields_used": False,
    }
    qa_manifest = {
        "created_utc": now_iso(),
        "hard_acceptance": {
            "exact_corridor_candidate_count": int(len(candidates)),
            "expected_exact_corridor_candidate_count": EXPECTED_EXACT_LINKED_BINS,
            "candidate_count_matches_expected": bool(len(candidates) == EXPECTED_EXACT_LINKED_BINS),
            "no_staged_directionality_mutation": True,
            "every_proposed_bin_one_corridor_one_side": bool((checks["status"] != "fail").all()),
            "no_crash_direction_fields_used": True,
        },
        "case_checks": case_check.to_dict("records"),
        "conflict_and_safety_checks": checks.to_dict("records"),
        "recommendation": recs.iloc[0]["recommendation"],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    log("Completed exact corridor-link directionality proposal.")


if __name__ == "__main__":
    main()
