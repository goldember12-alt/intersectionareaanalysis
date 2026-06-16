"""Read-only chain completeness audit for one-sided approach corridors.

This audit determines whether staged approach_corridors rows are logical
branches or source-row fragments, and whether short chains appear to stop early
despite same-corridor Travelway continuation candidates.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/approach_corridor_chain_completeness_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

REBUILD_REVIEW = REPO / "work/roadway_graph/review/rebuild_one_sided_approach_corridors"
SIGNAL_QA_REVIEW = REPO / "work/roadway_graph/review/approach_corridors_signal_level_qa_audit"
SIDE_REACH_AUDIT = REPO / "work/roadway_graph/review/approach_corridor_side_reach_audit"
GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"
BUILD_APPROACH_REVIEW = REPO / "work/roadway_graph/review/build_signal_approaches"

MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
FLOAT_TOL_FT = 0.001
CHAIN_GAP_TOL_FT = 25.0
NEIGHBOR_LIKELY_GAP_FT = 50.0
NEIGHBOR_POSSIBLE_GAP_FT = 250.0


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


def hash_text(text: str, length: int = 24) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def compact_counts(series: pd.Series) -> str:
    if series.empty:
        return ""
    counts = series.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{idx}:{int(val)}" for idx, val in counts.items())


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


def structural_checks(approaches: pd.DataFrame, corridors: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    approach_ids = set(approaches["signal_approach_id"])
    direction_cols = [
        c for c in corridors.columns
        if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"}
        or c.lower().endswith("_directionality")
    ]
    checks = [
        {"check_name": "approach_corridor_id_unique", "value": int(corridors["approach_corridor_id"].duplicated(keep=False).sum()), "pass_condition": "0"},
        {"check_name": "valid_parent_approach_links", "value": int((~corridors["signal_approach_id"].isin(approach_ids)).sum()), "pass_condition": "0"},
        {"check_name": "blocked_approaches_absent", "value": int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum()), "pass_condition": "0"},
        {"check_name": "signal_spanning_rows_absent", "value": int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum()), "pass_condition": "0"},
        {"check_name": "one_sided_overextension_absent", "value": int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum()), "pass_condition": "0"},
        {"check_name": "directionality_fields_absent", "value": len(direction_cols), "detail": "|".join(direction_cols), "pass_condition": "0"},
    ]
    for row in checks:
        row["status"] = "pass" if int(row["value"]) == 0 else "fail"
    checks.extend(
        [
            {"check_name": "approach_rows_read", "value": int(len(approaches)), "status": "info"},
            {"check_name": "corridor_rows_read", "value": int(len(corridors)), "status": "info"},
        ]
    )
    return checks, direction_cols


def prepare_roads(roads: pd.DataFrame) -> pd.DataFrame:
    out = roads.copy()
    out["source_measure_start"] = pd.to_numeric(out["source_measure_start"], errors="coerce")
    out["source_measure_end"] = pd.to_numeric(out["source_measure_end"], errors="coerce")
    out = out[out["route_measure_status"].eq("route_measure_complete")].copy()
    out["road_lo"] = out[["source_measure_start", "source_measure_end"]].min(axis=1)
    out["road_hi"] = out[["source_measure_start", "source_measure_end"]].max(axis=1)
    return out.dropna(subset=["road_lo", "road_hi", "source_route_name"])


def find_continuation(chain: pd.Series, roads_by_route: dict[str, pd.DataFrame], used_ids: set[str]) -> dict[str, Any]:
    route = clean(chain.get("source_route_name"))
    roads = roads_by_route.get(route)
    if roads is None or roads.empty:
        return {
            "continuation_candidate_count": 0,
            "best_continuation_stable_travelway_id": "",
            "best_continuation_gap_ft": "",
            "early_stop_classification": "correct_stop_at_source_extent" if chain.get("expected_stop_reason") == "source_extent" else "partial_unclear_possible_early_stop",
        }
    side = clean(chain.get("measure_side_class"))
    signal_measure = float(chain["reviewed_signal_measure"])
    if side == "measure_increasing_from_signal":
        endpoint = float(chain["chain_to_measure"])
        max_endpoint = signal_measure + MAX_REACH_MILES
        cand = roads[(roads["road_hi"] > endpoint + 1e-9) & (roads["road_lo"] <= max_endpoint + 1e-9)].copy()
        cand["gap_ft"] = ((cand["road_lo"] - endpoint).clip(lower=0.0)) * 5280.0
    else:
        endpoint = float(chain["chain_from_measure"])
        min_endpoint = signal_measure - MAX_REACH_MILES
        cand = roads[(roads["road_lo"] < endpoint - 1e-9) & (roads["road_hi"] >= min_endpoint - 1e-9)].copy()
        cand["gap_ft"] = ((endpoint - cand["road_hi"]).clip(lower=0.0)) * 5280.0
    cand = cand[~cand["stable_travelway_id"].isin(used_ids)].copy()
    if cand.empty:
        stop = clean(chain.get("expected_stop_reason"))
        if stop == "source_extent":
            cls = "correct_stop_at_source_extent"
        else:
            cls = "partial_unclear_possible_early_stop"
        return {"continuation_candidate_count": 0, "best_continuation_stable_travelway_id": "", "best_continuation_gap_ft": "", "early_stop_classification": cls}
    chain_token = clean(chain.get("carriageway_direction_token"))
    chain_config = clean(chain.get("roadway_configuration"))
    token_values = cand["carriageway_direction_token"].fillna("").astype(str).str.strip()
    config_values = cand["roadway_configuration"].fillna("").astype(str).str.strip()
    token_mask = pd.Series(True, index=cand.index) if not chain_token else ((token_values == "") | (token_values == chain_token))
    config_mask = pd.Series(True, index=cand.index) if not chain_config else ((config_values == "") | (config_values == chain_config))
    compatible = cand[token_mask & config_mask].sort_values("gap_ft")
    if compatible.empty:
        best = cand.sort_values("gap_ft").iloc[0]
        return {
            "continuation_candidate_count": int(len(cand)),
            "best_continuation_stable_travelway_id": clean(best.get("stable_travelway_id")),
            "best_continuation_gap_ft": float(best["gap_ft"]),
            "early_stop_classification": "route_or_carriageway_conflict_blocks_extension",
        }
    best = compatible.iloc[0]
    gap_ft = float(best["gap_ft"])
    if gap_ft <= NEIGHBOR_LIKELY_GAP_FT:
        cls = "likely_early_stop_neighbor_available"
    elif gap_ft <= NEIGHBOR_POSSIBLE_GAP_FT:
        cls = "possible_early_stop_but_uncertain"
    else:
        cls = "route_measure_gap_blocks_extension"
    return {
        "continuation_candidate_count": int(len(compatible)),
        "best_continuation_stable_travelway_id": clean(best.get("stable_travelway_id")),
        "best_continuation_gap_ft": gap_ft,
        "early_stop_classification": cls,
    }


def build_chains(corridors: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    c = corridors.copy()
    c["corridor_from_measure"] = pd.to_numeric(c["corridor_from_measure"], errors="coerce")
    c["corridor_to_measure"] = pd.to_numeric(c["corridor_to_measure"], errors="coerce")
    c["reviewed_signal_measure"] = pd.to_numeric(c["reviewed_signal_measure"], errors="coerce")
    c["segment_lo"] = c[["corridor_from_measure", "corridor_to_measure"]].min(axis=1)
    c["segment_hi"] = c[["corridor_from_measure", "corridor_to_measure"]].max(axis=1)
    key_cols = [
        "stable_signal_id",
        "signal_approach_id",
        "measure_side_class",
        "source_route_name",
        "route_base",
        "carriageway_direction_token",
        "roadway_configuration",
    ]
    gap_tol_miles = CHAIN_GAP_TOL_FT / 5280.0
    chain_rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    grouped = c.groupby(key_cols, dropna=False)
    log(f"Building provisional chains from {grouped.ngroups} approach/side/route groups.")
    for idx, (key, group) in enumerate(grouped, start=1):
        if idx % 5000 == 0:
            log(f"Processed {idx} / {grouped.ngroups} chain source groups; provisional chains so far={len(chain_rows)}.")
        g = group.sort_values(["segment_lo", "segment_hi", "stable_travelway_id"]).copy()
        chain_seq = 0
        current: list[pd.Series] = []
        current_hi: float | None = None
        for _, row in g.iterrows():
            row_lo = float(row["segment_lo"])
            row_hi = float(row["segment_hi"])
            if current and current_hi is not None:
                gap = row_lo - current_hi
                if gap > gap_tol_miles:
                    chain_seq = flush_chain(key_cols, key, current, chain_seq, chain_rows, assignment_rows, gap_rows)
                    current = []
                    current_hi = None
                elif gap < -1e-9:
                    gap_rows.append({"gap_overlap_type": "overlap", "gap_or_overlap_ft": abs(gap) * 5280.0, "signal_approach_id": clean(row.get("signal_approach_id")), "source_route_name": clean(row.get("source_route_name"))})
                else:
                    gap_rows.append({"gap_overlap_type": "adjacent_or_small_gap", "gap_or_overlap_ft": max(gap, 0.0) * 5280.0, "signal_approach_id": clean(row.get("signal_approach_id")), "source_route_name": clean(row.get("source_route_name"))})
            current.append(row)
            current_hi = row_hi if current_hi is None else max(current_hi, row_hi)
        if current:
            flush_chain(key_cols, key, current, chain_seq, chain_rows, assignment_rows, gap_rows)
    chains = pd.DataFrame.from_records(chain_rows)
    assignments = pd.DataFrame.from_records(assignment_rows)
    log(f"Built {len(chains)} provisional chains from {len(assignments)} corridor segment assignments.")
    road_groups = {route: df.copy() for route, df in prepare_roads(roads).groupby("source_route_name")}
    log(f"Prepared route-indexed Travelway continuation candidates for {len(road_groups)} source routes.")
    cont_rows: list[dict[str, Any]] = []
    if not chains.empty:
        chain_used_ids = assignments.groupby("logical_corridor_chain_id")["stable_travelway_id"].apply(lambda s: set(s.dropna().astype(str))).to_dict()
        log(f"Starting continuation/early-stop checks for {len(chains)} chains.")
        for idx, (_, chain) in enumerate(chains.iterrows(), start=1):
            if idx % 5000 == 0:
                log(f"Checked continuation for {idx} / {len(chains)} chains.")
            if chain["chain_one_sided_reach_ft"] >= MAX_REACH_FT - FLOAT_TOL_FT:
                cls = "correct_stop_at_2500"
                cont = {"continuation_candidate_count": 0, "best_continuation_stable_travelway_id": "", "best_continuation_gap_ft": "", "early_stop_classification": cls}
            elif chain["expected_stop_reason"] == "signal_boundary":
                cont = {"continuation_candidate_count": 0, "best_continuation_stable_travelway_id": "", "best_continuation_gap_ft": "", "early_stop_classification": "correct_stop_at_signal_boundary"}
            else:
                cont = find_continuation(chain, road_groups, chain_used_ids.get(chain["logical_corridor_chain_id"], set()))
            cont_rows.append({**chain.to_dict(), **cont})
    log(f"Completed continuation checks; rows={len(cont_rows)}.")
    return chains, assignments, pd.DataFrame.from_records(cont_rows), pd.DataFrame.from_records(gap_rows)


def flush_chain(
    key_cols: list[str],
    key: tuple[Any, ...],
    rows: list[pd.Series],
    chain_seq: int,
    chain_rows: list[dict[str, Any]],
    assignment_rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
) -> int:
    df = pd.DataFrame(rows)
    key_map = dict(zip(key_cols, key))
    chain_id = "chain_" + hash_text("|".join(clean(key_map.get(c)) for c in key_cols) + f"|{chain_seq}")
    reviewed_measure = float(df["reviewed_signal_measure"].median())
    chain_from = float(df["segment_lo"].min())
    chain_to = float(df["segment_hi"].max())
    if clean(key_map.get("measure_side_class")) == "measure_increasing_from_signal":
        reach = max(0.0, (chain_to - reviewed_measure) * 5280.0)
    else:
        reach = max(0.0, (reviewed_measure - chain_from) * 5280.0)
    stop_reason = infer_stop_reason(df, reach)
    expected = stop_reason
    gap_count = int((df.sort_values("segment_lo")["segment_lo"].diff().fillna(0) > CHAIN_GAP_TOL_FT / 5280.0).sum())
    overlap_count = 0
    ordered = df.sort_values("segment_lo")
    prev_hi = None
    for _, row in ordered.iterrows():
        lo = float(row["segment_lo"])
        hi = float(row["segment_hi"])
        if prev_hi is not None and lo < prev_hi - 1e-9:
            overlap_count += 1
        prev_hi = hi if prev_hi is None else max(prev_hi, hi)
    chain_rows.append(
        {
            **key_map,
            "logical_corridor_chain_id": chain_id,
            "segment_row_count": int(len(df)),
            "source_travelway_row_count": int(df["stable_travelway_id"].nunique()),
            "chain_from_measure": chain_from,
            "chain_to_measure": chain_to,
            "reviewed_signal_measure": reviewed_measure,
            "chain_one_sided_reach_ft": reach,
            "summed_segment_length_ft": float(df["corridor_length_ft"].sum()),
            "gap_count": gap_count,
            "overlap_count": overlap_count,
            "endpoint_policy": compact_counts(df["endpoint_policy"]),
            "boundary_method_counts": compact_counts(df["boundary_method"]),
            "stop_reason": stop_reason,
            "expected_stop_reason": expected,
            "chain_completeness_status": chain_completeness_status(df, reach, stop_reason),
        }
    )
    for _, row in df.iterrows():
        assignment_rows.append(
            {
                "approach_corridor_id": clean(row.get("approach_corridor_id")),
                "logical_corridor_chain_id": chain_id,
                "stable_signal_id": clean(row.get("stable_signal_id")),
                "signal_approach_id": clean(row.get("signal_approach_id")),
                "stable_travelway_id": clean(row.get("stable_travelway_id")),
                "source_route_name": clean(row.get("source_route_name")),
                "measure_side_class": clean(row.get("measure_side_class")),
            }
        )
    return chain_seq + 1


def infer_stop_reason(df: pd.DataFrame, reach_ft: float) -> str:
    if df["clipped_by_signal_boundary_flag"].fillna(False).astype(bool).any():
        return "signal_boundary"
    if reach_ft >= MAX_REACH_FT - FLOAT_TOL_FT or df["clipped_by_2500_ft_flag"].fillna(False).astype(bool).any():
        return "2500ft_limit"
    if df["clipped_by_source_extent_flag"].fillna(False).astype(bool).any():
        return "source_extent"
    return "unclear_stop"


def chain_completeness_status(df: pd.DataFrame, reach_ft: float, stop_reason: str) -> str:
    if stop_reason == "signal_boundary":
        return "complete_to_supported_signal_boundary"
    if stop_reason == "2500ft_limit" or reach_ft >= MAX_REACH_FT - FLOAT_TOL_FT:
        return "complete_to_2500ft"
    if stop_reason == "source_extent":
        return "partial_source_extent_stop_needs_continuation_audit"
    return "partial_unclear_stop_needs_continuation_audit"


def row_semantics(corridors: pd.DataFrame, chains: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    rows = int(len(corridors))
    chains_n = int(len(chains))
    multi_segment_chains = int((chains["segment_row_count"] > 1).sum()) if not chains.empty else 0
    mean_segments = float(chains["segment_row_count"].mean()) if not chains.empty else 0.0
    max_segments = int(chains["segment_row_count"].max()) if not chains.empty else 0
    if chains_n == 0:
        finding = "insufficient_evidence"
    elif mean_segments <= 1.15 and multi_segment_chains / max(chains_n, 1) < 0.10:
        finding = "likely_logical_branch_rows"
    elif mean_segments >= 1.5 or multi_segment_chains / max(chains_n, 1) > 0.25:
        finding = "likely_source_row_segment_rows"
    else:
        finding = "mixed_branch_and_segment_rows"
    return pd.DataFrame(
        [
            {
                "row_semantics_finding": finding,
                "corridor_rows": rows,
                "provisional_logical_chains": chains_n,
                "multi_segment_chain_count": multi_segment_chains,
                "mean_segments_per_chain": mean_segments,
                "max_segments_per_chain": max_segments,
                "interpretation": "Grouping by approach, neutral side, route, carriageway token, and configuration produced little segment chaining." if finding == "likely_logical_branch_rows" else "Multiple source-row segments combine into provisional logical chains.",
            }
        ]
    ), finding


def distance_support(reach_ft: float, early_stop_class: str) -> str:
    if pd.isna(reach_ft) or reach_ft <= 0:
        return "no_usable_support"
    if reach_ft >= MAX_REACH_FT - FLOAT_TOL_FT or early_stop_class == "correct_stop_at_2500":
        return "full_one_sided_0_2500_support"
    if early_stop_class == "correct_stop_at_signal_boundary":
        return "partial_signal_boundary_clipped"
    if early_stop_class == "correct_stop_at_source_extent":
        return "partial_source_extent_clipped"
    if early_stop_class == "route_measure_gap_blocks_extension":
        return "partial_route_measure_gap"
    if early_stop_class == "geometry_gap_blocks_extension":
        return "partial_geometry_gap"
    return "partial_unclear_possible_early_stop"


def build_density_and_support(
    approaches: pd.DataFrame,
    corridors: pd.DataFrame,
    chains: pd.DataFrame,
    continuation: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    chain_support = continuation.copy()
    if not chain_support.empty:
        chain_support["distance_band_readiness_status"] = chain_support.apply(lambda r: distance_support(float(r["chain_one_sided_reach_ft"]), clean(r["early_stop_classification"])), axis=1)
        for start, end in [(0, 250), (250, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 2500)]:
            chain_support[f"supports_{start}_{end}ft"] = chain_support["chain_one_sided_reach_ft"] >= end - FLOAT_TOL_FT
    else:
        chain_support["distance_band_readiness_status"] = []
    raw_app = corridors.groupby("signal_approach_id").size().reset_index(name="raw_corridor_rows")
    chain_app = chains.groupby("signal_approach_id").agg(
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
        segment_rows_per_logical_branch_mean=("segment_row_count", "mean"),
        segment_rows_per_logical_branch_max=("segment_row_count", "max"),
        max_chain_reach_ft=("chain_one_sided_reach_ft", "max"),
    ).reset_index()
    app = approaches[["stable_signal_id", "signal_approach_id", "corridor_build_gate"]].merge(raw_app, on="signal_approach_id", how="left").merge(chain_app, on="signal_approach_id", how="left")
    app[["raw_corridor_rows", "logical_chain_count", "segment_rows_per_logical_branch_mean", "segment_rows_per_logical_branch_max", "max_chain_reach_ft"]] = app[["raw_corridor_rows", "logical_chain_count", "segment_rows_per_logical_branch_mean", "segment_rows_per_logical_branch_max", "max_chain_reach_ft"]].fillna(0)
    raw_sig = corridors.groupby("stable_signal_id").size().reset_index(name="raw_corridor_rows")
    chain_sig = chains.groupby("stable_signal_id").agg(
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
        approach_count_with_chains=("signal_approach_id", "nunique"),
        segment_rows_per_logical_branch_mean=("segment_row_count", "mean"),
        max_chain_reach_ft=("chain_one_sided_reach_ft", "max"),
    ).reset_index()
    sig_approach = approaches.groupby("stable_signal_id").size().reset_index(name="signal_approach_count")
    sig = sig_approach.merge(raw_sig, on="stable_signal_id", how="left").merge(chain_sig, on="stable_signal_id", how="left")
    sig[["raw_corridor_rows", "logical_chain_count", "approach_count_with_chains", "segment_rows_per_logical_branch_mean", "max_chain_reach_ft"]] = sig[["raw_corridor_rows", "logical_chain_count", "approach_count_with_chains", "segment_rows_per_logical_branch_mean", "max_chain_reach_ft"]].fillna(0)
    return {"chain_support": chain_support, "by_approach": app, "by_signal": sig}


def one_row_risk(chains: pd.DataFrame, continuation: pd.DataFrame) -> pd.DataFrame:
    one = continuation[continuation["segment_row_count"].eq(1)].copy()
    if one.empty:
        return one
    def classify(row: pd.Series) -> str:
        early = clean(row.get("early_stop_classification"))
        if early == "correct_stop_at_2500":
            return "one_row_correct_long_source_row_clipped"
        if early == "correct_stop_at_signal_boundary":
            return "one_row_correct_signal_boundary"
        if early == "correct_stop_at_source_extent":
            return "one_row_correct_source_extent"
        if early == "likely_early_stop_neighbor_available":
            return "one_row_suspect_neighbor_available"
        return "one_row_uncertain"
    one["one_row_risk_class"] = one.apply(classify, axis=1)
    return one


def write_outputs(
    checks: list[dict[str, Any]],
    semantics_df: pd.DataFrame,
    semantics: str,
    assignments: pd.DataFrame,
    chains: pd.DataFrame,
    continuation: pd.DataFrame,
    gap_rows: pd.DataFrame,
    densities: dict[str, pd.DataFrame],
    one_row: pd.DataFrame,
) -> str:
    support = densities["chain_support"]
    by_app = densities["by_approach"]
    by_sig = densities["by_signal"]
    likely_miss = continuation[continuation["early_stop_classification"].eq("likely_early_stop_neighbor_available")].copy()
    possible_miss = continuation[continuation["early_stop_classification"].eq("possible_early_stop_but_uncertain")].copy()
    high_branch = by_app[by_app["logical_chain_count"] >= 3].sort_values(["logical_chain_count", "raw_corridor_rows"], ascending=False)
    high_frag = chains[chains["segment_row_count"] >= 2].sort_values(["segment_row_count", "chain_one_sided_reach_ft"], ascending=False)

    hard_fail = any(row.get("status") == "fail" for row in checks)
    if hard_fail:
        decision = "approach_corridors_needs_branch_level_rebuild"
    elif len(likely_miss) > 0:
        decision = "approach_corridors_needs_neighbor_extension_patch"
    elif semantics in {"likely_source_row_segment_rows", "mixed_branch_and_segment_rows"} or len(high_frag) > 0:
        decision = "approach_corridors_needs_chain_id_status_patch"
    else:
        decision = "approach_corridors_ready_for_bin_context"

    write_csv("structural_baseline_check.csv", checks)
    write_csv("row_semantics_classification.csv", semantics_df.to_dict("records"))
    write_csv("provisional_corridor_chain_groups.csv", assignments.to_dict("records"))
    write_csv("chain_level_summary.csv", chains.to_dict("records"))
    write_csv("raw_rows_vs_logical_chains_by_approach.csv", by_app.to_dict("records"))
    write_csv("raw_rows_vs_logical_chains_by_signal.csv", by_sig.to_dict("records"))
    app_branch_dist = by_app["logical_chain_count"].value_counts().sort_index().reset_index(name="approach_count").rename(columns={"logical_chain_count": "logical_chain_count"})
    sig_branch_dist = by_sig["logical_chain_count"].value_counts().sort_index().reset_index(name="signal_count").rename(columns={"logical_chain_count": "logical_chain_count"})
    branch_dist = pd.concat(
        [
            app_branch_dist.assign(grain="approach").rename(columns={"approach_count": "object_count"}),
            sig_branch_dist.assign(grain="signal").rename(columns={"signal_count": "object_count"}),
        ],
        ignore_index=True,
    )
    write_csv("branch_density_distribution.csv", branch_dist.to_dict("records"))
    write_csv("continuation_early_stop_audit.csv", continuation.to_dict("records"))
    write_csv("likely_early_stop_neighbor_available.csv", likely_miss.to_dict("records"))
    write_csv("one_row_only_risk_audit.csv", one_row.to_dict("records"))
    write_csv("chain_gap_overlap_audit.csv", gap_rows.to_dict("records"))
    write_csv("distance_band_readiness_by_chain.csv", support.to_dict("records"))
    approach_support = support.groupby("signal_approach_id")["distance_band_readiness_status"].apply(compact_counts).reset_index(name="chain_distance_band_status_mix") if not support.empty else pd.DataFrame(columns=["signal_approach_id", "chain_distance_band_status_mix"])
    write_csv("distance_band_readiness_by_approach.csv", by_app.merge(approach_support, on="signal_approach_id", how="left").fillna("").to_dict("records"))
    write_csv("high_branch_density_review.csv", high_branch.head(500).to_dict("records"))
    write_csv("high_segment_fragmentation_review.csv", high_frag.head(500).to_dict("records"))
    write_csv("patch_or_rebuild_recommendation.csv", [
        {
            "recommendation": decision,
            "likely_neighbor_extension_misses": int(len(likely_miss)),
            "possible_neighbor_extension_misses": int(len(possible_miss)),
            "multi_segment_chains": int((chains["segment_row_count"] > 1).sum()) if not chains.empty else 0,
            "rationale": "Patch neighbor extension before bin_context if likely same-corridor neighbors exist; otherwise add chain ids/status if segment grouping is meaningful.",
        }
    ])
    write_csv("readiness_decision.csv", [{"final_decision": decision, "reason": "chain completeness audit completed"}])
    write_csv("recommended_next_actions.csv", [
        {"rank": 1, "action": "review_likely_early_stop_neighbor_available", "rationale": "These chains appear to stop at source-row extent while same-route compatible neighbor rows continue."},
        {"rank": 2, "action": "patch_neighbor_extension_or_chain_status_before_bin_context_if_accepted", "rationale": "Bin generation should use complete logical one-sided branches, not isolated early-stop segments."},
    ])

    chain_count_mean = float(by_app["logical_chain_count"].mean()) if not by_app.empty else 0.0
    chain_count_median = float(by_app["logical_chain_count"].median()) if not by_app.empty else 0.0
    sig_chain_mean = float(by_sig["logical_chain_count"].mean()) if not by_sig.empty else 0.0
    segment_mean = float(chains["segment_row_count"].mean()) if not chains.empty else 0.0
    early_counts = continuation["early_stop_classification"].value_counts().sort_index().reset_index(name="chain_count") if not continuation.empty else pd.DataFrame(columns=["early_stop_classification", "chain_count"])
    one_row_counts = one_row["one_row_risk_class"].value_counts().sort_index().reset_index(name="chain_count") if not one_row.empty else pd.DataFrame(columns=["one_row_risk_class", "chain_count"])
    support_counts = support["distance_band_readiness_status"].value_counts().sort_index().reset_index(name="chain_count") if not support.empty else pd.DataFrame(columns=["distance_band_readiness_status", "chain_count"])
    findings = f"""# Approach Corridor Chain Completeness Audit

## Row Semantics
Finding: `{semantics}`. The audit grouped {len(assignments):,} corridor rows into {len(chains):,} provisional logical chains. Mean segment rows per chain: {segment_mean:.2f}.

The mean 3.75 raw rows per approach is concerning only if those rows are source-fragment segments. The provisional grouping shows whether rows collapse into fewer logical chains or remain branch/subbranch rows.

## Logical Branch Density
Mean logical chains per approach: {chain_count_mean:.2f}; median: {chain_count_median:.2f}. Mean logical chains per signal: {sig_chain_mean:.2f}.

## Early Stops
Early-stop classifications:

{early_counts.to_string(index=False)}

Likely same-corridor neighbor-extension misses: {len(likely_miss):,}. Possible uncertain misses: {len(possible_miss):,}.

## One-Row Chains
One-row risk classes:

{one_row_counts.to_string(index=False)}

## Distance-Band Readiness
Chain-level distance-band readiness:

{support_counts.to_string(index=False)}

## Best QA Flags
Best QA flags are logical chain count per approach, segment rows per chain, early-stop classification, continuation candidate count, one-row risk class, and chain distance-band readiness.

## Readiness
Final decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_at": now(),
        "script": rel(Path(__file__)),
        "output_dir": rel(OUT),
        "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS)],
        "method_evidence_only": [rel(REBUILD_REVIEW), rel(SIGNAL_QA_REVIEW), rel(SIDE_REACH_AUDIT), rel(GATE_PATCH_REVIEW), rel(BUILD_APPROACH_REVIEW)],
        "outputs": sorted(p.name for p in OUT.iterdir() if p.is_file()),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "created_at": now(),
        "corridor_rows": int(len(assignments)),
        "logical_chains": int(len(chains)),
        "mean_segments_per_chain": segment_mean,
        "mean_logical_chains_per_approach": chain_count_mean,
        "mean_logical_chains_per_signal": sig_chain_mean,
        "likely_early_stop_neighbor_available": int(len(likely_miss)),
        "possible_early_stop_but_uncertain": int(len(possible_miss)),
        "final_decision": decision,
    }
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    return decision


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text("", encoding="utf-8")
    log("Starting corridor chain completeness audit.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id"])
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
    attachments = pd.read_parquet(ATTACHMENT, columns=["attachment_id"])
    approaches = pd.read_parquet(
        APPROACHES,
        columns=["stable_signal_id", "signal_approach_id", "corridor_build_gate"],
    )
    corridors = pd.read_parquet(CORRIDORS)
    log(f"Loaded signals={len(signals)}, roads={len(roads)}, attachments={len(attachments)}, approaches={len(approaches)}, corridors={len(corridors)}.")
    checks, _ = structural_checks(approaches, corridors)
    chains, assignments, continuation, gap_rows = build_chains(corridors, roads)
    semantics_df, semantics = row_semantics(corridors, chains)
    densities = build_density_and_support(approaches, corridors, chains, continuation)
    one_row = one_row_risk(chains, continuation)
    decision = write_outputs(checks, semantics_df, semantics, assignments, chains, continuation, gap_rows, densities, one_row)
    log(f"Audit complete with decision {decision}.")


if __name__ == "__main__":
    main()
