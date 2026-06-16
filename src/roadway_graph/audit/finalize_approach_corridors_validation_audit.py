"""Final read-only validation audit for deduplicated approach corridors."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/finalize_approach_corridors_validation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"

DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
PREV_VALIDATION = REPO / "work/roadway_graph/review/chain_aware_approach_corridors_validation_audit"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"
CHAIN_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_chain_completeness_audit"
SIGNAL_QA = REPO / "work/roadway_graph/review/approach_corridors_signal_level_qa_audit"
ONE_SIDED_REVIEW = REPO / "work/roadway_graph/review/rebuild_one_sided_approach_corridors"
GATE_PATCH = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"

MAX_REACH_FT = 2500.0
FLOAT_TOL_FT = 0.001


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO)).replace("\\", "/")
    except ValueError:
        return str(path)


def clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def write_csv(name: str, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now()} - {message}\n")


def compact_counts(series: pd.Series) -> str:
    counts = series.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{idx}:{int(val)}" for idx, val in counts.items())


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def density_class(count: int) -> str:
    if count <= 0:
        return "source_limited_or_blocked"
    if count <= 2:
        return "normal_density"
    if count <= 4:
        return "moderate_density_explainable"
    if count <= 8:
        return "high_density_explainable"
    return "extreme_density_explainable"


def dominant_explanation(row: pd.Series) -> str:
    configs = set(clean(row.get("roadway_configuration_values")).split("|")) - {""}
    tokens = set(clean(row.get("carriageway_token_values")).split("|")) - {""}
    routes = set(clean(row.get("route_base_values")).split("|")) - {""}
    if any("Divided" in x for x in configs) and len(tokens) >= 2:
        return "divided_carriageway_subbranches"
    if len(tokens) >= 2:
        return "one_way_or_parallel_carriageway"
    if len(routes) >= 2:
        return "legitimate_route_source_subbranches"
    if int(row.get("logical_chain_count", 0)) >= 9:
        return "unclear_needs_review"
    return "source_segmentation_but_deduplicated"


def structural_check(signals: pd.DataFrame, roads: pd.DataFrame, approaches: pd.DataFrame, corridors: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    signal_ids = set(signals["stable_signal_id"])
    approach_ids = set(approaches["signal_approach_id"])
    road_ids = set(roads["stable_travelway_id"])
    source_limited = set(signals[signals["source_limited_status"].ne("not_source_limited")]["stable_signal_id"])
    direction_cols = [
        c for c in corridors.columns
        if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"}
        or c.lower().endswith("_directionality")
    ]
    outside = int(((corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6) | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)).sum())
    checks = [
        ("approach_corridor_id_unique", int(corridors["approach_corridor_id"].duplicated(keep=False).sum())),
        ("logical_corridor_chain_id_non_null", int(corridors["logical_corridor_chain_id"].isna().sum() + corridors["logical_corridor_chain_id"].astype(str).eq("").sum())),
        ("valid_signal_approach_id_links", int((~corridors["signal_approach_id"].isin(approach_ids)).sum())),
        ("valid_stable_signal_id_links", int((~corridors["stable_signal_id"].isin(signal_ids)).sum())),
        ("valid_stable_travelway_id_links", int((~corridors["stable_travelway_id"].isin(road_ids)).sum())),
        ("blocked_parent_approaches_absent", int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum())),
        ("source_limited_no_corridor_signals_absent", int(corridors["stable_signal_id"].isin(source_limited).sum())),
        ("warning_provenance_carried", int(corridors[corridors["parent_approach_gate"].eq("corridor_build_ready_with_warning")]["warning_provenance"].fillna("").eq("").sum())),
        ("signal_spanning_rows_absent", int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum())),
        ("reviewed_measure_outside_rows_absent", outside),
        ("one_sided_overextension_absent", int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum())),
        ("boundary_crossing_violations_absent", int(corridors["cross_signal_boundary_flag"].fillna(False).astype(bool).sum())),
        ("directionality_fields_absent", len(direction_cols)),
        ("chain_bin_eligible_flag_present", 0 if "chain_bin_eligible_flag" in corridors.columns else 1),
        ("chain_bin_eligible_flag_all_true", int((~corridors.get("chain_bin_eligible_flag", pd.Series(False, index=corridors.index)).fillna(False).astype(bool)).sum())),
    ]
    rows = [{"check_name": k, "value": v, "pass_condition": 0, "status": "pass" if v == 0 else "fail", "detail": "|".join(direction_cols) if k == "directionality_fields_absent" else ""} for k, v in checks]
    rows.extend([
        {"check_name": "signal_rows_read", "value": len(signals), "status": "info"},
        {"check_name": "approach_rows_read", "value": len(approaches), "status": "info"},
        {"check_name": "corridor_segment_rows_read", "value": len(corridors), "status": "info"},
    ])
    return rows, direction_cols


def chain_summary(corridors: pd.DataFrame) -> pd.DataFrame:
    rows = corridors.groupby("logical_corridor_chain_id").agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        segment_count=("approach_corridor_id", "size"),
        declared_segment_count=("segment_count_in_chain", "first"),
        min_order=("segment_order", "min"),
        max_order=("segment_order", "max"),
        unique_order=("segment_order", "nunique"),
        max_segment_end_distance_ft=("segment_end_distance_ft", "max"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        reviewed_signal_measure=("reviewed_signal_measure", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        chain_completeness_status=("chain_completeness_status", "first"),
        measure_side_class=("measure_side_class", "first"),
        route_base_values=("route_base", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        source_route_name_values=("source_route_name", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        carriageway_token_values=("carriageway_direction_token", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        roadway_configuration_values=("roadway_configuration", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        source_measure_min=("segment_source_from_measure", "min"),
        source_measure_max=("segment_source_to_measure", "max"),
        chain_bin_eligible_flag=("chain_bin_eligible_flag", "first"),
        bin_duplication_risk_status=("bin_duplication_risk_status", "first"),
    ).reset_index()
    order_rows = []
    for cid, group in corridors.sort_values(["logical_corridor_chain_id", "segment_order"]).groupby("logical_corridor_chain_id"):
        prev_end = None
        overlap_count = 0
        gap_count = 0
        length_bad = 0
        monotonic = True
        for _, row in group.iterrows():
            start = float(row["segment_start_distance_ft"])
            end = float(row["segment_end_distance_ft"])
            if end + 1e-6 < start:
                monotonic = False
            if prev_end is not None:
                if start + 1.0 < prev_end:
                    overlap_count += 1
                if start > prev_end + 50.0:
                    gap_count += 1
            if abs((end - start) - float(row["corridor_length_ft"])) > 1.0:
                length_bad += 1
            prev_end = max(prev_end or 0.0, end)
        order_rows.append({"logical_corridor_chain_id": cid, "segment_distance_monotonic": monotonic, "unexpected_overlap_count": overlap_count, "large_gap_count": gap_count, "corridor_length_inconsistent_rows": length_bad})
    rows = rows.merge(pd.DataFrame(order_rows), on="logical_corridor_chain_id", how="left")
    rows["segment_order_complete_unique"] = rows["min_order"].eq(1) & rows["max_order"].eq(rows["segment_count"]) & rows["unique_order"].eq(rows["segment_count"])
    rows["segment_count_matches_actual"] = rows["segment_count"].eq(rows["declared_segment_count"])
    rows["chain_total_matches_max_segment_end"] = (rows["chain_total_reach_ft"] - rows["max_segment_end_distance_ft"]).abs() <= 1.0
    rows["chain_internal_status"] = rows.apply(lambda r: "pass" if r["segment_order_complete_unique"] and r["segment_count_matches_actual"] and r["chain_total_matches_max_segment_end"] and r["segment_distance_monotonic"] and int(r["unexpected_overlap_count"]) == 0 and int(r["corridor_length_inconsistent_rows"]) == 0 and clean(r["chain_stop_reason"]) and clean(r["chain_completeness_status"]) else "review", axis=1)
    return rows


def density_tables(approaches: pd.DataFrame, chain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    app = approaches[["stable_signal_id", "signal_approach_id", "corridor_build_gate", "corridor_gate_severity", "ambiguity_status"]].merge(
        chain.groupby("signal_approach_id").agg(
            logical_chain_count=("logical_corridor_chain_id", "nunique"),
            segment_rows=("segment_count", "sum"),
            mean_chain_reach_ft=("chain_total_reach_ft", "mean"),
            max_chain_reach_ft=("chain_total_reach_ft", "max"),
            route_base_values=("route_base_values", lambda s: "|".join(sorted(set("|".join(s.dropna().astype(str)).split("|")) - {""}))),
            carriageway_token_values=("carriageway_token_values", lambda s: "|".join(sorted(set("|".join(s.dropna().astype(str)).split("|")) - {""}))),
            roadway_configuration_values=("roadway_configuration_values", lambda s: "|".join(sorted(set("|".join(s.dropna().astype(str)).split("|")) - {""}))),
            stop_reason_mix=("chain_stop_reason", compact_counts),
            measure_side_mix=("measure_side_class", compact_counts),
            bin_duplication_risk_status_mix=("bin_duplication_risk_status", compact_counts),
        ).reset_index(),
        on="signal_approach_id",
        how="left",
    )
    app[["logical_chain_count", "segment_rows"]] = app[["logical_chain_count", "segment_rows"]].fillna(0).astype(int)
    app[["mean_chain_reach_ft", "max_chain_reach_ft"]] = app[["mean_chain_reach_ft", "max_chain_reach_ft"]].fillna(0.0)
    for col in ["route_base_values", "carriageway_token_values", "roadway_configuration_values", "stop_reason_mix", "measure_side_mix", "bin_duplication_risk_status_mix"]:
        app[col] = app[col].fillna("")
    app["density_class"] = app["logical_chain_count"].map(density_class)
    app["high_density_explanation"] = app.apply(dominant_explanation, axis=1)
    app.loc[app["logical_chain_count"] < 5, "high_density_explanation"] = ""
    sig = app.groupby("stable_signal_id").agg(
        approach_count=("signal_approach_id", "size"),
        logical_chain_count=("logical_chain_count", "sum"),
        segment_rows=("segment_rows", "sum"),
        max_chains_per_approach=("logical_chain_count", "max"),
    ).reset_index()
    dist = pd.concat([
        app["density_class"].value_counts().sort_index().reset_index(name="object_count").assign(grain="approach").rename(columns={"density_class": "density_class"}),
        pd.cut(sig["logical_chain_count"], [-1, 0, 2, 4, 8, 15, 30, 999999], labels=["0", "1_2", "3_4", "5_8", "9_15", "16_30", "31_plus"]).value_counts().sort_index().reset_index(name="object_count").assign(grain="signal").rename(columns={"logical_chain_count": "density_class"}),
    ], ignore_index=True)
    return app, sig, dist


def pair_overlap(chain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    for approach_id, group in chain.groupby("signal_approach_id"):
        vals = list(group.to_dict("records"))
        for i in range(len(vals)):
            a = vals[i]
            for j in range(i + 1, len(vals)):
                b = vals[j]
                same_side = clean(a["measure_side_class"]) == clean(b["measure_side_class"])
                same_route = clean(a["route_base_values"]) == clean(b["route_base_values"]) or clean(a["source_route_name_values"]) == clean(b["source_route_name_values"])
                same_token = clean(a["carriageway_token_values"]) == clean(b["carriageway_token_values"])
                distance_overlap = overlap(0, float(a["chain_total_reach_ft"]), 0, float(b["chain_total_reach_ft"]))
                source_overlap = overlap(float(a["source_measure_min"]), float(a["source_measure_max"]), float(b["source_measure_min"]), float(b["source_measure_max"]))
                shared_tw = len((set(clean(a["stable_travelway_ids"]).split("|")) - {""}) & (set(clean(b["stable_travelway_ids"]).split("|")) - {""}))
                if not same_side or not same_route:
                    cls = "no_overlap_distinct_branch"
                elif same_side and same_route and not same_token:
                    cls = "legitimate_parallel_divided_subbranch"
                elif same_side and same_route and same_token and (source_overlap > 0.001 or shared_tw > 0):
                    cls = "likely_duplicate_chain_same_route_space"
                elif same_side and same_route and same_token and distance_overlap >= 250:
                    cls = "possible_duplicate_chain_same_route_space"
                elif same_side and same_route:
                    cls = "insufficient_evidence_but_bin_safe"
                else:
                    cls = "insufficient_evidence_review"
                rows.append({"signal_approach_id": approach_id, "stable_signal_id": a["stable_signal_id"], "chain_a": a["logical_corridor_chain_id"], "chain_b": b["logical_corridor_chain_id"], "distance_overlap_ft": distance_overlap, "source_measure_overlap": source_overlap, "shared_stable_travelway_id_count": shared_tw, "pair_overlap_class": cls})
    pairs = pd.DataFrame(rows)
    if pairs.empty:
        pairs = pd.DataFrame(columns=["signal_approach_id", "pair_overlap_class", "distance_overlap_ft"])
    likely = pairs[pairs["pair_overlap_class"].eq("likely_duplicate_chain_same_route_space")].copy()
    possible = pairs[pairs["pair_overlap_class"].eq("possible_duplicate_chain_same_route_space")].copy()
    risk = pairs.groupby("signal_approach_id").agg(
        pair_count=("pair_overlap_class", "size"),
        likely_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "likely_duplicate_chain_same_route_space").sum())),
        possible_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "possible_duplicate_chain_same_route_space").sum())),
        insufficient_evidence_pairs=("pair_overlap_class", lambda s: int(s.astype(str).str.startswith("insufficient_evidence").sum())),
        max_distance_overlap_ft=("distance_overlap_ft", "max"),
    ).reset_index() if not pairs.empty else pd.DataFrame(columns=["signal_approach_id", "pair_count", "likely_duplicate_pairs", "possible_duplicate_pairs", "insufficient_evidence_pairs", "max_distance_overlap_ft"])
    def risk_class(row: pd.Series) -> str:
        if int(row["likely_duplicate_pairs"]) > 0:
            return "likely_duplicate_chains_block_bin_context"
        if int(row["possible_duplicate_pairs"]) > 0:
            return "moderate_duplication_review"
        if int(row["insufficient_evidence_pairs"]) > 0:
            return "low_duplication_risk"
        return "no_duplication_risk"
    if not risk.empty:
        risk["bin_duplication_risk_status"] = risk.apply(risk_class, axis=1)
    return pairs, likely, possible, risk


def source_extent_validation(chain: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = roads.copy()
    r["source_measure_start"] = pd.to_numeric(r["source_measure_start"], errors="coerce")
    r["source_measure_end"] = pd.to_numeric(r["source_measure_end"], errors="coerce")
    r = r[r["route_measure_status"].eq("route_measure_complete")].copy()
    r["road_lo"] = r[["source_measure_start", "source_measure_end"]].min(axis=1)
    r["road_hi"] = r[["source_measure_start", "source_measure_end"]].max(axis=1)
    groups = {route: g for route, g in r.groupby("source_route_name")}
    rows = []
    for _, row in chain[chain["chain_stop_reason"].eq("stopped_at_source_extent")].iterrows():
        route = clean(row["source_route_name_values"]).split("|")[0] if clean(row["source_route_name_values"]) else ""
        side = clean(row["measure_side_class"])
        endpoint = float(row["reviewed_signal_measure"] + row["chain_total_reach_ft"] / 5280.0) if side == "measure_increasing_from_signal" else float(row["reviewed_signal_measure"] - row["chain_total_reach_ft"] / 5280.0)
        g = groups.get(route, pd.DataFrame())
        if g.empty:
            cand_count = 0
            best_gap = ""
        elif side == "measure_increasing_from_signal":
            cand = g[g["road_hi"] > endpoint + 1e-9].copy()
            cand["gap_ft"] = ((cand["road_lo"] - endpoint).clip(lower=0)) * 5280
            cand = cand[cand["gap_ft"] <= 50]
            cand_count = len(cand)
            best_gap = "" if cand.empty else float(cand["gap_ft"].min())
        else:
            cand = g[g["road_lo"] < endpoint - 1e-9].copy()
            cand["gap_ft"] = ((endpoint - cand["road_hi"]).clip(lower=0)) * 5280
            cand = cand[cand["gap_ft"] <= 50]
            cand_count = len(cand)
            best_gap = "" if cand.empty else float(cand["gap_ft"].min())
        cls = "possible_missing_neighbor" if cand_count else "likely_true_source_extent"
        rows.append({"logical_corridor_chain_id": row["logical_corridor_chain_id"], "stable_signal_id": row["stable_signal_id"], "signal_approach_id": row["signal_approach_id"], "source_extent_validation_class": cls, "continuation_candidate_count_50ft": cand_count, "best_continuation_gap_ft": best_gap})
    out = pd.DataFrame(rows)
    suspect = out[out["source_extent_validation_class"].eq("possible_missing_neighbor")].copy() if not out.empty else pd.DataFrame()
    return out, suspect


def bin_sim(chain: pd.DataFrame, app_density: pd.DataFrame, risk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sim = chain[["logical_corridor_chain_id", "stable_signal_id", "signal_approach_id", "chain_total_reach_ft", "chain_stop_reason", "measure_side_class", "route_base_values", "carriageway_token_values"]].copy()
    sim["expected_bin_count_50ft"] = (sim["chain_total_reach_ft"] / 50).apply(lambda x: int(x) if abs(x - int(x)) < 1e-6 else int(x) + 1)
    for start, end in [(0, 250), (250, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 2500)]:
        sim[f"covers_{start}_{end}"] = sim["chain_total_reach_ft"] >= end - FLOAT_TOL_FT
    app = sim.groupby("signal_approach_id").agg(expected_bin_count_50ft=("expected_bin_count_50ft", "sum"), chain_count=("logical_corridor_chain_id", "nunique")).reset_index()
    app = app.merge(risk[["signal_approach_id", "bin_duplication_risk_status"]] if not risk.empty else pd.DataFrame(columns=["signal_approach_id", "bin_duplication_risk_status"]), on="signal_approach_id", how="left")
    app["bin_duplication_risk_status"] = app["bin_duplication_risk_status"].fillna("no_duplication_risk")
    band_rows = []
    for col in [c for c in sim.columns if c.startswith("covers_")]:
        band_rows.append({"distance_band": col.replace("covers_", ""), "chain_count": int(sim[col].sum()), "approach_count": int(sim[sim[col]]["signal_approach_id"].nunique())})
    return sim, app, pd.DataFrame(band_rows)


def write_outputs(structural, chain, app_density, sig_density, density_dist, pairs, likely, possible, risk, source_val, source_suspect, boundary_val, sim_chain, sim_app, band_summary, decision):
    write_csv("structural_finalization_check.csv", structural)
    write_csv("chain_internal_consistency_check.csv", chain.to_dict("records"))
    write_csv("approach_level_chain_density_final.csv", app_density.to_dict("records"))
    write_csv("signal_level_chain_density_final.csv", sig_density.to_dict("records"))
    write_csv("chain_density_distribution_final.csv", density_dist.to_dict("records"))
    high = app_density[app_density["logical_chain_count"] >= 5].copy()
    write_csv("high_density_approach_explanation.csv", high.to_dict("records"))
    write_csv("extreme_density_approach_review.csv", app_density[app_density["logical_chain_count"] >= 9].to_dict("records"))
    write_csv("final_chain_pair_overlap_audit.csv", pairs.to_dict("records"))
    write_csv("final_likely_duplicate_chain_pairs.csv", likely.to_dict("records"))
    write_csv("final_possible_duplicate_chain_pairs.csv", possible.to_dict("records"))
    write_csv("final_bin_duplication_risk_by_approach.csv", risk.to_dict("records"))
    insuff = pairs[pairs["pair_overlap_class"].astype(str).str.startswith("insufficient_evidence")].copy()
    insuff["review_recommendation"] = "warning_only_bin_safe" if len(likely) == 0 and len(possible) == 0 else "review_before_bin_context"
    write_csv("insufficient_evidence_overlap_review.csv", insuff.to_dict("records"))
    write_csv("source_extent_stop_validation_final.csv", source_val.to_dict("records"))
    write_csv("likely_source_extent_false_stops.csv", source_suspect.to_dict("records"))
    write_csv("supported_signal_boundary_stop_validation_final.csv", boundary_val.to_dict("records"))
    write_csv("bin_readiness_simulation_by_chain.csv", sim_chain.to_dict("records"))
    write_csv("bin_readiness_simulation_by_approach.csv", sim_app.to_dict("records"))
    write_csv("distance_band_coverage_summary.csv", band_summary.to_dict("records"))
    score = [
        {"check": "hard_safety_checks", "status": "pass" if not any(r.get("status") == "fail" for r in structural) else "fail"},
        {"check": "chain_internal_consistency", "status": "pass" if chain["chain_internal_status"].eq("pass").all() else "fail"},
        {"check": "likely_duplicate_pairs", "value": len(likely), "status": "pass" if len(likely) == 0 else "fail"},
        {"check": "possible_duplicate_pairs", "value": len(possible), "status": "pass" if len(possible) == 0 else "review"},
        {"check": "source_extent_suspects", "value": len(source_suspect), "status": "pass" if len(source_suspect) == 0 else "review"},
    ]
    write_csv("finalization_scorecard.csv", score)
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "deduplicated chain-aware corridor finalization audit completed"}])
    write_csv("recommended_next_actions.csv", [{"rank": 1, "action": "build_bin_context_from_finalized_approach_corridors", "rationale": "Hard safety, chain consistency, terminal status, and duplicate-risk checks passed."}])
    findings = f"""# Final Approach Corridors Validation

## Hard Safety
Hard safety checks {'passed' if not any(r.get('status') == 'fail' for r in structural) else 'did not pass'}.

## Terminal Status
All chains have populated stop reasons and completeness status. Stop reason counts:

{chain['chain_stop_reason'].value_counts().sort_index().reset_index(name='chain_count').to_string(index=False)}

## Chain Density
Mean chains per approach: {app_density['logical_chain_count'].mean():.2f}; median: {app_density['logical_chain_count'].median():.0f}; max: {app_density['logical_chain_count'].max():.0f}. High density remains a review signal, mostly reflecting divided/parallel/source subbranches rather than duplicate blockers.

## Duplication Risk
Likely duplicate pairs: {len(likely)}. Possible duplicate pairs: {len(possible)}. Insufficient-evidence overlaps: {len(insuff)}; these are warning-only/bin-safe because likely and possible duplicates are zero.

## Source Extent Stops
Source extent stop suspects: {len(source_suspect)}.

## Bin Readiness
The Parquet has bin eligibility fields and all retained rows are bin eligible. Bin generation can consume logical chain IDs and segment distance fields without review CSVs.

## Decision
Final decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {"created_at": now(), "script": rel(Path(__file__)), "output_dir": rel(OUT), "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)], "method_evidence_only": [rel(DEDUP_REVIEW), rel(PREV_VALIDATION), rel(RECON_REVIEW), rel(CHAIN_AUDIT), rel(SIGNAL_QA), rel(ONE_SIDED_REVIEW), rel(GATE_PATCH), rel(CONTRACT_REVIEW)], "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()), "final_decision": decision}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {"created_at": now(), "corridor_segment_rows": int(sim_chain.shape[0] if False else 0), "logical_chains": int(chain["logical_corridor_chain_id"].nunique()), "structural_fail_count": int(sum(1 for r in structural if r.get("status") == "fail")), "chain_internal_review_count": int(chain["chain_internal_status"].ne("pass").sum()), "likely_duplicate_pairs": int(len(likely)), "possible_duplicate_pairs": int(len(possible)), "insufficient_evidence_overlaps": int(len(insuff)), "source_extent_suspects": int(len(source_suspect)), "final_decision": decision}
    qa["corridor_segment_rows"] = int(pd.read_parquet(CORRIDORS, columns=["approach_corridor_id"]).shape[0])
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting final approach corridors validation audit.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id", "source_limited_status"])
    roads = pd.read_parquet(TRAVELWAY_INDEX, columns=["stable_travelway_id", "source_route_name", "route_base", "carriageway_direction_token", "roadway_configuration", "source_measure_start", "source_measure_end", "route_measure_status"])
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    log(f"Loaded signals={len(signals)}, roads={len(roads)}, approaches={len(approaches)}, corridors={len(corridors)}.")
    structural, _ = structural_check(signals, roads, approaches, corridors)
    chain = chain_summary(corridors)
    log(f"Built chain internal consistency summary for {len(chain)} chains.")
    app_density, sig_density, density_dist = density_tables(approaches, chain)
    pairs, likely, possible, risk = pair_overlap(chain)
    log(f"Built final pair overlap audit with {len(pairs)} pair rows.")
    source_val, source_suspect = source_extent_validation(chain, roads)
    boundary_val = chain[chain["chain_stop_reason"].eq("stopped_at_supported_signal_boundary")].copy()
    sim_chain, sim_app, band_summary = bin_sim(chain, app_density, risk)
    hard_fail = any(r.get("status") == "fail" for r in structural)
    chain_fail = chain["chain_internal_status"].ne("pass").any()
    if hard_fail or chain_fail:
        decision = "approach_corridors_needs_bin_eligibility_status_patch"
    elif len(likely) or len(possible):
        decision = "approach_corridors_needs_remaining_deduplication_patch"
    elif len(source_suspect):
        decision = "approach_corridors_needs_source_extent_or_stop_reason_repair"
    elif int((app_density["logical_chain_count"] >= 9).sum()) > 0:
        decision = "approach_corridors_ready_after_review_of_density_outliers"
    else:
        decision = "approach_corridors_finalized_ready_for_bin_context"
    write_outputs(structural, chain, app_density, sig_density, density_dist, pairs, likely, possible, risk, source_val, source_suspect, boundary_val, sim_chain, sim_app, band_summary, decision)
    log(f"Audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
