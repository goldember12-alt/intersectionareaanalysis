"""Read-only validation audit for chain-aware approach corridors.

This audit validates the staged chain-aware approach_corridors.parquet layer
before bin_context construction. It does not mutate staged data or generate
bins.
"""

from __future__ import annotations

import csv
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/chain_aware_approach_corridors_validation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"
CHAIN_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_chain_completeness_audit"
SIGNAL_QA = REPO / "work/roadway_graph/review/approach_corridors_signal_level_qa_audit"
ONE_SIDED_REVIEW = REPO / "work/roadway_graph/review/rebuild_one_sided_approach_corridors"
SIDE_REACH_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_side_reach_audit"
GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
BUILD_APPROACH_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"
CONTRACT_REVIEW = REPO / "work/roadway_graph/review/cache_contract_and_rebuild_plan"

MAX_REACH_FT = 2500.0
FLOAT_TOL_FT = 0.001
SOURCE_CONTINUATION_GAP_FT = 50.0


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
    if series.empty:
        return ""
    counts = series.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{idx}:{int(val)}" for idx, val in counts.items())


def density_class(count: int, gate: str = "") -> str:
    if gate == "corridor_build_blocked_pending_rule_repair":
        return "source_limited_or_blocked"
    if count <= 0:
        return "insufficient_evidence"
    if count <= 2:
        return "normal_chain_density"
    if count <= 4:
        return "moderate_chain_density_review"
    if count <= 8:
        return "high_chain_density_review"
    return "extreme_chain_density_review"


def interval_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def band_flags(reach: float) -> dict[str, bool]:
    return {
        "covers_0_250": reach >= 250 - FLOAT_TOL_FT,
        "covers_250_500": reach >= 500 - FLOAT_TOL_FT,
        "covers_500_1000": reach >= 1000 - FLOAT_TOL_FT,
        "covers_1000_1500": reach >= 1500 - FLOAT_TOL_FT,
        "covers_1500_2000": reach >= 2000 - FLOAT_TOL_FT,
        "covers_2000_2500": reach >= 2500 - FLOAT_TOL_FT,
    }


def structural_baseline(signals: pd.DataFrame, roads: pd.DataFrame, approaches: pd.DataFrame, corridors: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    signal_ids = set(signals["stable_signal_id"])
    approach_ids = set(approaches["signal_approach_id"])
    road_ids = set(roads["stable_travelway_id"])
    direction_cols = [
        c for c in corridors.columns
        if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"}
        or c.lower().endswith("_directionality")
    ]
    outside = int(
        (
            (corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6)
            | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)
        ).sum()
    )
    source_limited_signal_ids = set(signals[signals["source_limited_status"].ne("not_source_limited")]["stable_signal_id"])
    checks = [
        ("approach_corridor_id_unique", int(corridors["approach_corridor_id"].duplicated(keep=False).sum()), "0"),
        ("logical_corridor_chain_id_non_null", int(corridors["logical_corridor_chain_id"].isna().sum() + corridors["logical_corridor_chain_id"].astype(str).eq("").sum()), "0"),
        ("valid_signal_approach_id_links", int((~corridors["signal_approach_id"].isin(approach_ids)).sum()), "0"),
        ("valid_stable_signal_id_links", int((~corridors["stable_signal_id"].isin(signal_ids)).sum()), "0"),
        ("valid_stable_travelway_id_links", int((~corridors["stable_travelway_id"].isin(road_ids)).sum()), "0"),
        ("blocked_parent_approaches_absent", int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum()), "0"),
        ("source_limited_no_corridor_signals_absent", int(corridors["stable_signal_id"].isin(source_limited_signal_ids).sum()), "0"),
        ("warning_provenance_carried", int(corridors[corridors["parent_approach_gate"].eq("corridor_build_ready_with_warning")]["warning_provenance"].fillna("").eq("").sum()), "0"),
        ("signal_spanning_rows_absent", int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum()), "0"),
        ("reviewed_measure_outside_rows_absent", outside, "0"),
        ("one_sided_overextension_absent", int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum()), "0"),
        ("boundary_crossing_violations_absent", int(corridors["cross_signal_boundary_flag"].fillna(False).astype(bool).sum()), "0"),
        ("directionality_fields_absent", len(direction_cols), "0"),
    ]
    rows = []
    for name, value, condition in checks:
        rows.append({"check_name": name, "value": value, "pass_condition": condition, "status": "pass" if value == 0 else "fail", "detail": "|".join(direction_cols) if name == "directionality_fields_absent" else ""})
    rows.extend(
        [
            {"check_name": "signal_rows_read", "value": int(len(signals)), "status": "info"},
            {"check_name": "approach_rows_read", "value": int(len(approaches)), "status": "info"},
            {"check_name": "corridor_segment_rows_read", "value": int(len(corridors)), "status": "info"},
        ]
    )
    return rows, direction_cols


def build_chain_summary(corridors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    chain = corridors.groupby("logical_corridor_chain_id").agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        segment_count=("approach_corridor_id", "size"),
        declared_segment_count=("segment_count_in_chain", "first"),
        min_segment_order=("segment_order", "min"),
        max_segment_order=("segment_order", "max"),
        unique_segment_orders=("segment_order", "nunique"),
        max_segment_end_distance_ft=("segment_end_distance_ft", "max"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        reviewed_signal_measure=("reviewed_signal_measure", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        chain_completeness_status=("chain_completeness_status", "first"),
        source_route_name_values=("source_route_name", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        route_base_values=("route_base", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        carriageway_token_values=("carriageway_direction_token", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        roadway_configuration_values=("roadway_configuration", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        measure_side_class=("measure_side_class", "first"),
        stop_reason_count=("chain_stop_reason", "nunique"),
        completeness_status_count=("chain_completeness_status", "nunique"),
        stable_travelway_count=("stable_travelway_id", "nunique"),
    ).reset_index()
    chain["segment_count_matches_declared"] = chain["segment_count"].eq(chain["declared_segment_count"])
    chain["segment_order_complete_unique"] = chain["min_segment_order"].eq(1) & chain["max_segment_order"].eq(chain["segment_count"]) & chain["unique_segment_orders"].eq(chain["segment_count"])
    chain["chain_total_matches_max_segment_end"] = (chain["chain_total_reach_ft"] - chain["max_segment_end_distance_ft"]).abs() <= 1.0
    order_rows = []
    for chain_id, group in corridors.sort_values(["logical_corridor_chain_id", "segment_order"]).groupby("logical_corridor_chain_id"):
        prev_end = None
        monotonic = True
        overlap_count = 0
        gap_count = 0
        inconsistent_length = 0
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
                inconsistent_length += 1
            prev_end = max(prev_end or 0.0, end)
        order_rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "segment_distance_monotonic": monotonic,
                "unexpected_overlap_count": overlap_count,
                "large_gap_count": gap_count,
                "corridor_length_inconsistent_rows": inconsistent_length,
            }
        )
    order = pd.DataFrame(order_rows)
    chain = chain.merge(order, on="logical_corridor_chain_id", how="left")
    chain["chain_identity_status"] = chain.apply(
        lambda r: "pass"
        if r["segment_count_matches_declared"]
        and r["segment_order_complete_unique"]
        and r["chain_total_matches_max_segment_end"]
        and r["segment_distance_monotonic"]
        and int(r["unexpected_overlap_count"]) == 0
        and int(r["corridor_length_inconsistent_rows"]) == 0
        and clean(r["chain_stop_reason"])
        and clean(r["chain_completeness_status"])
        else "review",
        axis=1,
    )
    return chain, order


def build_density(approaches: pd.DataFrame, corridors: pd.DataFrame, chain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    app = approaches[["stable_signal_id", "signal_approach_id", "corridor_build_gate", "corridor_gate_severity", "dominant_roadway_configuration", "dominant_carriageway_token_values", "route_base"]].merge(
        chain.groupby("signal_approach_id").agg(
            logical_chain_count=("logical_corridor_chain_id", "nunique"),
            segment_rows=("segment_count", "sum"),
            max_segments_per_chain=("segment_count", "max"),
            route_base_values=("route_base_values", lambda s: "|".join(sorted(set("|".join(s.dropna().astype(str)).split("|"))))),
            carriageway_token_values=("carriageway_token_values", lambda s: "|".join(sorted(set("|".join(s.dropna().astype(str)).split("|"))))),
            roadway_configuration_values=("roadway_configuration_values", lambda s: "|".join(sorted(set("|".join(s.dropna().astype(str)).split("|"))))),
            stop_reason_mix=("chain_stop_reason", compact_counts),
        ).reset_index(),
        on="signal_approach_id",
        how="left",
    )
    for col in ["logical_chain_count", "segment_rows", "max_segments_per_chain"]:
        app[col] = app[col].fillna(0).astype(int)
    for col in ["route_base_values", "carriageway_token_values", "roadway_configuration_values", "stop_reason_mix"]:
        app[col] = app[col].fillna("")
    app["chain_density_class"] = app.apply(lambda r: density_class(int(r["logical_chain_count"]), clean(r["corridor_build_gate"])), axis=1)
    sig = app.groupby("stable_signal_id").agg(
        approach_count=("signal_approach_id", "size"),
        logical_chain_count=("logical_chain_count", "sum"),
        segment_rows=("segment_rows", "sum"),
        max_chains_per_approach=("logical_chain_count", "max"),
    ).reset_index()
    density_dist = pd.concat(
        [
            app["chain_density_class"].value_counts().sort_index().reset_index(name="object_count").assign(grain="approach").rename(columns={"chain_density_class": "density_class"}),
            pd.cut(sig["logical_chain_count"], bins=[-1, 0, 2, 4, 8, 15, 30, 999999], labels=["0", "1_2", "3_4", "5_8", "9_15", "16_30", "31_plus"]).value_counts().sort_index().reset_index(name="object_count").assign(grain="signal").rename(columns={"logical_chain_count": "density_class"}),
        ],
        ignore_index=True,
    )
    return app, sig, density_dist


def explain_high_density(app_density: pd.DataFrame, chain: pd.DataFrame) -> pd.DataFrame:
    high = app_density[app_density["logical_chain_count"] >= 3].copy()
    rows = []
    for _, app in high.iterrows():
        chains = chain[chain["signal_approach_id"].eq(app["signal_approach_id"])]
        configs = set("|".join(chains["roadway_configuration_values"].fillna("").astype(str)).split("|")) - {""}
        tokens = set("|".join(chains["carriageway_token_values"].fillna("").astype(str)).split("|")) - {""}
        routes = set("|".join(chains["route_base_values"].fillna("").astype(str)).split("|")) - {""}
        if any("Divided" in x for x in configs) and len(tokens) >= 2:
            explanation = "divided_carriageway_subbranches"
        elif len(tokens) >= 2:
            explanation = "one_way_pair_or_parallel_carriageway"
        elif len(routes) >= 2:
            explanation = "legitimate_route_source_segmentation"
        elif int(app["logical_chain_count"]) >= 5:
            explanation = "duplicate_candidate_alternatives_possible"
        else:
            explanation = "unknown_needs_review"
        rows.append(
            {
                "stable_signal_id": app["stable_signal_id"],
                "signal_approach_id": app["signal_approach_id"],
                "logical_chain_count": int(app["logical_chain_count"]),
                "segment_rows": int(app["segment_rows"]),
                "route_base_values": "|".join(sorted(routes)),
                "carriageway_token_values": "|".join(sorted(tokens)),
                "roadway_configuration_values": "|".join(sorted(configs)),
                "stop_reason_mix": app["stop_reason_mix"],
                "high_density_explanation": explanation,
            }
        )
    return pd.DataFrame(rows)


def chain_overlap_audit(chain: pd.DataFrame, corridors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    chain = chain.copy()
    source_ranges = corridors.groupby("logical_corridor_chain_id").agg(
        source_measure_min=("segment_source_from_measure", "min"),
        source_measure_max=("segment_source_to_measure", "max"),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
    ).reset_index()
    chain = chain.merge(source_ranges, on="logical_corridor_chain_id", how="left")
    pair_rows = []
    for approach_id, group in chain.groupby("signal_approach_id"):
        if len(group) < 2:
            continue
        for _, a in group.iterrows():
            for _, b in group[group["logical_corridor_chain_id"] > a["logical_corridor_chain_id"]].iterrows():
                same_side = clean(a["measure_side_class"]) == clean(b["measure_side_class"])
                same_route = clean(a["route_base_values"]) == clean(b["route_base_values"]) or clean(a["source_route_name_values"]) == clean(b["source_route_name_values"])
                same_token = clean(a["carriageway_token_values"]) == clean(b["carriageway_token_values"])
                dist_overlap = interval_overlap(0.0, float(a["chain_total_reach_ft"]), 0.0, float(b["chain_total_reach_ft"]))
                src_overlap = interval_overlap(float(a["source_measure_min"]), float(a["source_measure_max"]), float(b["source_measure_min"]), float(b["source_measure_max"]))
                ids_a = set(clean(a.get("stable_travelway_ids")).split("|")) - {""}
                ids_b = set(clean(b.get("stable_travelway_ids")).split("|")) - {""}
                shared_tw = len(ids_a & ids_b)
                if not same_side or not same_route:
                    cls = "no_overlap_distinct_branch"
                elif same_side and same_route and same_token and (src_overlap > 0.001 or shared_tw > 0):
                    cls = "likely_duplicate_chain_same_route_space"
                elif same_side and same_route and same_token and dist_overlap >= 250:
                    cls = "possible_duplicate_chain_same_route_space"
                elif same_side and same_route and not same_token:
                    cls = "legitimate_parallel_divided_subbranch"
                else:
                    cls = "insufficient_evidence"
                pair_rows.append(
                    {
                        "signal_approach_id": approach_id,
                        "stable_signal_id": a["stable_signal_id"],
                        "chain_a": a["logical_corridor_chain_id"],
                        "chain_b": b["logical_corridor_chain_id"],
                        "same_measure_side": same_side,
                        "same_route_or_base": same_route,
                        "same_carriageway_token": same_token,
                        "distance_overlap_ft": dist_overlap,
                        "source_measure_overlap": src_overlap,
                        "shared_stable_travelway_id_count": shared_tw,
                        "pair_overlap_class": cls,
                    }
                )
    pairs = pd.DataFrame(pair_rows)
    if pairs.empty:
        pairs = pd.DataFrame(columns=["signal_approach_id", "pair_overlap_class", "distance_overlap_ft"])
    likely = pairs[pairs["pair_overlap_class"].isin(["likely_duplicate_chain_same_route_space", "possible_duplicate_chain_same_route_space"])].copy()
    risk = pairs.groupby("signal_approach_id").agg(
        pair_count=("pair_overlap_class", "size"),
        likely_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "likely_duplicate_chain_same_route_space").sum())),
        possible_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "possible_duplicate_chain_same_route_space").sum())),
        max_distance_overlap_ft=("distance_overlap_ft", "max"),
    ).reset_index() if not pairs.empty else pd.DataFrame(columns=["signal_approach_id", "pair_count", "likely_duplicate_pairs", "possible_duplicate_pairs", "max_distance_overlap_ft"])
    def risk_class(row: pd.Series) -> str:
        if int(row.get("likely_duplicate_pairs", 0)) > 0:
            return "likely_duplicate_chains_block_bin_context"
        if int(row.get("possible_duplicate_pairs", 0)) >= 3:
            return "high_duplication_risk"
        if int(row.get("possible_duplicate_pairs", 0)) > 0:
            return "moderate_duplication_review"
        if int(row.get("pair_count", 0)) > 0:
            return "low_duplication_risk"
        return "no_duplication_risk"
    risk["approach_duplication_risk"] = risk.apply(risk_class, axis=1)
    band_risk = pairs[pairs["distance_overlap_ft"] >= 50].groupby("signal_approach_id").agg(overlapping_chain_pair_count=("pair_overlap_class", "size"), max_distance_overlap_ft=("distance_overlap_ft", "max")).reset_index() if not pairs.empty else pd.DataFrame(columns=["signal_approach_id", "overlapping_chain_pair_count", "max_distance_overlap_ft"])
    return pairs, likely, risk, band_risk


def bin_readiness(chain: pd.DataFrame, app_risk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sim = chain[
        [
            "logical_corridor_chain_id",
            "stable_signal_id",
            "signal_approach_id",
            "chain_total_reach_ft",
            "chain_stop_reason",
            "chain_completeness_status",
            "measure_side_class",
            "route_base_values",
            "carriageway_token_values",
        ]
    ].copy()
    sim["expected_bin_count_50ft"] = (sim["chain_total_reach_ft"] / 50.0).apply(lambda x: int(x) if abs(x - int(x)) < 1e-6 else int(x) + 1)
    for key, val in band_flags(0).items():
        sim[key] = False
    for idx, row in sim.iterrows():
        flags = band_flags(float(row["chain_total_reach_ft"]))
        for key, val in flags.items():
            sim.at[idx, key] = val
    sim["missing_band_reason"] = sim["chain_stop_reason"].map(
        {
            "reached_2500_ft": "",
            "stopped_at_supported_signal_boundary": "stopped_at_supported_signal_boundary",
            "stopped_at_source_extent": "stopped_at_source_extent",
        }
    ).fillna("other_stop_reason")
    app = sim.groupby("signal_approach_id").agg(
        simulated_chain_count=("logical_corridor_chain_id", "nunique"),
        expected_bin_count_50ft_sum=("expected_bin_count_50ft", "sum"),
        full_2500_chain_count=("chain_stop_reason", lambda s: int((s == "reached_2500_ft").sum())),
        boundary_clipped_chain_count=("chain_stop_reason", lambda s: int((s == "stopped_at_supported_signal_boundary").sum())),
        source_extent_chain_count=("chain_stop_reason", lambda s: int((s == "stopped_at_source_extent").sum())),
    ).reset_index()
    app = app.merge(app_risk[["signal_approach_id", "approach_duplication_risk"]] if not app_risk.empty else pd.DataFrame(columns=["signal_approach_id", "approach_duplication_risk"]), on="signal_approach_id", how="left")
    app["approach_duplication_risk"] = app["approach_duplication_risk"].fillna("no_duplication_risk")
    return sim, app


def source_extent_validation(chain: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = roads.copy()
    r["source_measure_start"] = pd.to_numeric(r["source_measure_start"], errors="coerce")
    r["source_measure_end"] = pd.to_numeric(r["source_measure_end"], errors="coerce")
    r = r[r["route_measure_status"].eq("route_measure_complete")].copy()
    r["road_lo"] = r[["source_measure_start", "source_measure_end"]].min(axis=1)
    r["road_hi"] = r[["source_measure_start", "source_measure_end"]].max(axis=1)
    groups = {route: g for route, g in r.groupby("source_route_name")}
    rows = []
    false_rows = []
    source_chains = chain[chain["chain_stop_reason"].eq("stopped_at_source_extent")]
    for _, row in source_chains.iterrows():
        route = clean(row["source_route_name_values"].split("|")[0]) if clean(row.get("source_route_name_values")) else ""
        side = clean(row.get("measure_side_class"))
        token = clean(row.get("carriageway_token_values")).split("|")[0] if clean(row.get("carriageway_token_values")) else ""
        config = clean(row.get("roadway_configuration_values")).split("|")[0] if clean(row.get("roadway_configuration_values")) else ""
        g = groups.get(route, pd.DataFrame())
        if g.empty:
            cls = "likely_true_source_extent"
            candidate_count = 0
            best_gap = ""
        else:
            g = g.copy()
            token_mask = pd.Series(True, index=g.index) if not token else (g["carriageway_direction_token"].fillna("").astype(str).str.strip().isin(["", token]))
            config_mask = pd.Series(True, index=g.index) if not config else (g["roadway_configuration"].fillna("").astype(str).str.strip().isin(["", config]))
            g = g[token_mask & config_mask]
            endpoint_measure = float(row["reviewed_signal_measure"] + (row["chain_total_reach_ft"] / 5280.0)) if side == "measure_increasing_from_signal" else float(row["reviewed_signal_measure"] - (row["chain_total_reach_ft"] / 5280.0))
            if side == "measure_increasing_from_signal":
                cand = g[g["road_hi"] > endpoint_measure + 1e-9].copy()
                cand["gap_ft"] = ((cand["road_lo"] - endpoint_measure).clip(lower=0)) * 5280
            else:
                cand = g[g["road_lo"] < endpoint_measure - 1e-9].copy()
                cand["gap_ft"] = ((endpoint_measure - cand["road_hi"]).clip(lower=0)) * 5280
            cand = cand[cand["gap_ft"] <= SOURCE_CONTINUATION_GAP_FT]
            candidate_count = int(len(cand))
            best_gap = float(cand["gap_ft"].min()) if not cand.empty else ""
            cls = "possible_missing_neighbor" if candidate_count else "likely_true_source_extent"
        rec = {
            "logical_corridor_chain_id": row["logical_corridor_chain_id"],
            "stable_signal_id": row["stable_signal_id"],
            "signal_approach_id": row["signal_approach_id"],
            "source_route_name_values": row["source_route_name_values"],
            "measure_side_class": side,
            "chain_total_reach_ft": row["chain_total_reach_ft"],
            "source_extent_validation_class": cls,
            "continuation_candidate_count_50ft": candidate_count,
            "best_continuation_gap_ft": best_gap,
        }
        rows.append(rec)
        if cls == "possible_missing_neighbor":
            false_rows.append(rec)
    return pd.DataFrame(rows), pd.DataFrame(false_rows)


def stop_reason_validation(chain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    valid = {"reached_2500_ft", "stopped_at_supported_signal_boundary", "stopped_at_source_extent", "stopped_at_route_measure_gap", "stopped_at_geometry_gap", "stopped_at_route_or_carriageway_conflict", "stopped_at_roadway_configuration_conflict", "stopped_due_side_assignment_uncertain", "stopped_due_parent_gate", "stopped_due_insufficient_evidence"}
    rows = []
    for reason, g in chain.groupby("chain_stop_reason", dropna=False):
        reason_text = clean(reason)
        if reason_text == "reached_2500_ft":
            bad = int((g["chain_total_reach_ft"] < MAX_REACH_FT - 1.0).sum())
        elif reason_text == "stopped_at_supported_signal_boundary":
            bad = int((g["chain_total_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum())
        else:
            bad = 0
        rows.append({"chain_stop_reason": reason_text, "chain_count": int(len(g)), "invalid_reason_count": bad, "is_allowed_stop_reason": reason_text in valid, "status": "pass" if bad == 0 and reason_text in valid else "review"})
    boundary = chain[chain["chain_stop_reason"].eq("stopped_at_supported_signal_boundary")].copy()
    return pd.DataFrame(rows), boundary


def write_outputs(
    signals: pd.DataFrame,
    roads: pd.DataFrame,
    approaches: pd.DataFrame,
    corridors: pd.DataFrame,
    structural: list[dict[str, Any]],
    chain: pd.DataFrame,
    app_density: pd.DataFrame,
    sig_density: pd.DataFrame,
    density_dist: pd.DataFrame,
    high_explain: pd.DataFrame,
    pairs: pd.DataFrame,
    likely_pairs: pd.DataFrame,
    app_risk: pd.DataFrame,
    band_risk: pd.DataFrame,
    sim_chain: pd.DataFrame,
    sim_app: pd.DataFrame,
    stop_validation: pd.DataFrame,
    source_validation: pd.DataFrame,
    false_source: pd.DataFrame,
    boundary_validation: pd.DataFrame,
) -> str:
    hard_fail = any(r.get("status") == "fail" for r in structural)
    chain_identity_fail = int(chain["chain_identity_status"].ne("pass").sum())
    high_dup = int(app_risk["approach_duplication_risk"].isin(["high_duplication_risk", "likely_duplicate_chains_block_bin_context"]).sum()) if not app_risk.empty else 0
    false_source_count = int(len(false_source))
    high_density_count = int(app_density["chain_density_class"].isin(["high_chain_density_review", "extreme_chain_density_review"]).sum())
    if hard_fail or chain_identity_fail:
        decision = "approach_corridors_needs_segment_order_or_chain_id_repair"
    elif high_dup:
        decision = "approach_corridors_needs_chain_deduplication_patch"
    elif false_source_count:
        decision = "approach_corridors_needs_stop_reason_or_source_extent_repair"
    elif high_density_count:
        decision = "approach_corridors_ready_after_review_of_density_outliers"
    else:
        decision = "approach_corridors_ready_for_bin_context"

    write_csv("structural_baseline_check.csv", structural)
    write_csv("chain_identity_and_segment_order_check.csv", chain.to_dict("records"))
    write_csv("chain_level_summary.csv", chain.to_dict("records"))
    write_csv("approach_level_chain_density.csv", app_density.to_dict("records"))
    write_csv("signal_level_chain_density.csv", sig_density.to_dict("records"))
    write_csv("chain_density_distribution.csv", density_dist.to_dict("records"))
    write_csv("high_chain_density_approach_review.csv", app_density[app_density["chain_density_class"].isin(["high_chain_density_review", "extreme_chain_density_review"])].sort_values(["logical_chain_count", "segment_rows"], ascending=False).to_dict("records"))
    write_csv("extreme_chain_density_approach_review.csv", app_density[app_density["chain_density_class"].eq("extreme_chain_density_review")].sort_values(["logical_chain_count", "segment_rows"], ascending=False).to_dict("records"))
    write_csv("high_chain_density_explanation.csv", high_explain.to_dict("records"))
    write_csv("chain_pair_overlap_audit.csv", pairs.to_dict("records"))
    write_csv("likely_duplicate_chain_pairs.csv", likely_pairs.to_dict("records"))
    write_csv("approach_level_bin_duplication_risk.csv", app_risk.to_dict("records"))
    write_csv("distance_band_overlap_risk_by_approach.csv", band_risk.to_dict("records"))
    write_csv("bin_readiness_simulation_by_chain.csv", sim_chain.to_dict("records"))
    write_csv("bin_readiness_simulation_by_approach.csv", sim_app.to_dict("records"))
    write_csv("stop_reason_validation.csv", stop_validation.to_dict("records"))
    write_csv("source_extent_stop_validation.csv", source_validation.to_dict("records"))
    write_csv("likely_source_extent_false_stops.csv", false_source.to_dict("records"))
    write_csv("supported_signal_boundary_stop_validation.csv", boundary_validation.to_dict("records"))
    warning = approaches[approaches["corridor_build_gate"].eq("corridor_build_ready_with_warning")][["signal_approach_id", "stable_signal_id", "corridor_gate_severity", "corridor_restriction_notes"]].merge(app_density[["signal_approach_id", "logical_chain_count", "segment_rows"]], on="signal_approach_id", how="left")
    warning["has_chain"] = warning["logical_chain_count"].fillna(0).astype(int) > 0
    write_csv("warning_gate_propagation_check.csv", warning.to_dict("records"))
    blocked = approaches[approaches["corridor_build_gate"].eq("corridor_build_blocked_pending_rule_repair")][["signal_approach_id", "stable_signal_id", "corridor_build_gate"]].merge(app_density[["signal_approach_id", "logical_chain_count", "segment_rows"]], on="signal_approach_id", how="left")
    blocked[["logical_chain_count", "segment_rows"]] = blocked[["logical_chain_count", "segment_rows"]].fillna(0).astype(int)
    blocked["excluded_from_corridors"] = blocked["logical_chain_count"].eq(0)
    write_csv("blocked_gate_exclusion_check.csv", blocked.to_dict("records"))
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "chain-aware corridor validation audit completed"}])
    write_csv("recommended_next_actions.csv", [
        {"rank": 1, "action": "review_high_density_and_duplication_risk_ledgers", "rationale": "Density thresholds are QA screens before bin_context."},
        {"rank": 2, "action": "proceed_to_bin_context_if_density_and_duplication_ledgers_are_accepted", "rationale": "Hard safety and chain identity checks are separated from review outliers."},
    ])

    structural_fail_count = sum(1 for r in structural if r.get("status") == "fail")
    density_counts = app_density["chain_density_class"].value_counts().sort_index().reset_index(name="approach_count")
    risk_counts = app_risk["approach_duplication_risk"].value_counts().sort_index().reset_index(name="approach_count") if not app_risk.empty else pd.DataFrame(columns=["approach_duplication_risk", "approach_count"])
    stop_counts = chain["chain_stop_reason"].value_counts().sort_index().reset_index(name="chain_count")
    findings = f"""# Chain-Aware Approach Corridors Validation Audit

## Hard Safety
Structural fail count: {structural_fail_count}. Signal-spanning rows, reviewed-measure-outside rows, over-2,500-ft rows, boundary crossings, blocked rows, and directionality fields are checked in `structural_baseline_check.csv`.

## Terminal Status
Every chain carries `chain_stop_reason` and `chain_completeness_status`. Stop reason counts:

{stop_counts.to_string(index=False)}

## Chain Density
Average logical chains per approach: {app_density['logical_chain_count'].mean():.2f}. Density classes:

{density_counts.to_string(index=False)}

High density is acceptable only where explained by divided/parallel subbranches or legitimate route/source complexity; outliers are ledgered.

## Duplication Risk
Approach-level duplication risk:

{risk_counts.to_string(index=False)}

## Source Extent Stops
Source extent chains checked: {len(source_validation):,}. Possible missing-neighbor source-extent stops: {len(false_source):,}.

## Gates
Warning approaches represented: {int(warning['has_chain'].sum())} / {len(warning)}. Blocked approaches excluded: {int(blocked['excluded_from_corridors'].sum())} / {len(blocked)}.

## Readiness
Final decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)],
        "method_evidence_only": [rel(RECON_REVIEW), rel(CHAIN_AUDIT), rel(SIGNAL_QA), rel(ONE_SIDED_REVIEW), rel(SIDE_REACH_AUDIT), rel(GATE_PATCH_REVIEW), rel(BUILD_APPROACH_REVIEW), rel(CONTRACT_REVIEW)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "corridor_segment_rows": int(len(corridors)),
        "logical_chains": int(chain["logical_corridor_chain_id"].nunique()),
        "structural_fail_count": int(structural_fail_count),
        "chain_identity_review_count": int(chain_identity_fail),
        "high_or_extreme_density_approaches": int(high_density_count),
        "high_duplication_risk_approaches": int(high_dup),
        "possible_source_extent_false_stops": int(false_source_count),
        "warning_approaches_with_chains": int(warning["has_chain"].sum()),
        "blocked_approaches_excluded": int(blocked["excluded_from_corridors"].sum()),
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    return decision


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting chain-aware approach corridors validation audit.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id", "source_limited_status"])
    roads = pd.read_parquet(
        TRAVELWAY_INDEX,
        columns=[
            "stable_travelway_id",
            "source_route_name",
            "route_base",
            "carriageway_direction_token",
            "roadway_configuration",
            "source_measure_start",
            "source_measure_end",
            "route_measure_status",
        ],
    )
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    log(f"Loaded signals={len(signals)}, roads={len(roads)}, approaches={len(approaches)}, corridors={len(corridors)}.")
    structural, _ = structural_baseline(signals, roads, approaches, corridors)
    log("Built structural baseline checks.")
    chain, _order = build_chain_summary(corridors)
    log(f"Built chain summary for {len(chain)} logical chains.")
    app_density, sig_density, density_dist = build_density(approaches, corridors, chain)
    high_explain = explain_high_density(app_density, chain)
    log("Built density and high-density explanation tables.")
    pairs, likely_pairs, app_risk, band_risk = chain_overlap_audit(chain, corridors)
    log(f"Built chain pair overlap audit with {len(pairs)} pair rows.")
    sim_chain, sim_app = bin_readiness(chain, app_risk)
    stop_validation, boundary_validation = stop_reason_validation(chain)
    source_validation, false_source = source_extent_validation(chain, roads)
    log("Built bin-readiness, stop reason, and source extent validation tables.")
    decision = write_outputs(signals, roads, approaches, corridors, structural, chain, app_density, sig_density, density_dist, high_explain, pairs, likely_pairs, app_risk, band_risk, sim_chain, sim_app, stop_validation, source_validation, false_source, boundary_validation)
    log(f"Audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
