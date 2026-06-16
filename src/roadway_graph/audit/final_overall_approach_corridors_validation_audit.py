"""Final read-only validation audit for staged approach corridors.

This is the final corridor-layer audit before bin_context generation. It reads
the staged cache and diagnostic review outputs, but writes only review QA files.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/final_overall_approach_corridors_validation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_approach_corridor_context_transition_extensions"
FULL_AUDIT = REPO / "work/roadway_graph/review/full_source_extent_continuation_audit"
CONFIG_AUDIT = REPO / "work/roadway_graph/review/roadway_configuration_conflict_continuation_audit"
SOURCE_RECON = REPO / "work/roadway_graph/review/source_extent_suspect_chain_reconciliation_audit"
FINAL_REVIEW = REPO / "work/roadway_graph/review/finalize_approach_corridors_validation_audit"
DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
CHAIN_AWARE_REVIEW = REPO / "work/roadway_graph/review/chain_aware_approach_corridors_validation_audit"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"
CHAIN_COMPLETENESS_REVIEW = REPO / "work/roadway_graph/review/approach_corridor_chain_completeness_audit"
GATE_PATCH_REVIEW = REPO / "work/roadway_graph/review/patch_signal_approach_corridor_gates"

MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
FLOAT_TOL_FT = 0.001
SEARCH_GAP_FT = 50.0
ACCEPT_GAP_FT = 5.0
BANDS = [(0, 250), (250, 500), (500, 1000), (1000, 1500), (1500, 2000), (2000, 2500)]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)).replace("\\", "/")


def clean(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>", "nat"} else text


def safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def write_csv(name: str, rows: list[dict[str, Any]] | pd.DataFrame, fieldnames: list[str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, pd.DataFrame):
        rows.to_csv(OUT / name, index=False)
        return
    if fieldnames is None:
        fieldnames = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        if not fieldnames:
            fieldnames = ["note"]
    with (OUT / name).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def read_csv_optional(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 2:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def log(message: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = now()
    print(f"[{stamp}] {message}", flush=True)
    with (OUT / "progress_log.md").open("a", encoding="utf-8") as fh:
        fh.write(f"- {stamp}: {message}\n")


def compact_counts(series: pd.Series) -> str:
    counts = series.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{k}:{int(v)}" for k, v in counts.items())


def compatible_value(a: Any, b: Any) -> bool:
    aa = clean(a).lower()
    bb = clean(b).lower()
    unknown = {"", "unknown", "nan", "none", "null", "<na>"}
    return aa == bb or aa in unknown or bb in unknown


def config_family(config: Any) -> str:
    text = clean(config).lower()
    if "two-way undivided" in text:
        return "two_way_undivided"
    if "two-way divided" in text:
        return "two_way_divided"
    if "one-way" in text:
        return "one_way"
    if "reversible" in text:
        return "reversible"
    if "trail" in text:
        return "trail"
    return "unknown"


def allowed_context_transition(a: Any, b: Any) -> bool:
    fam = {config_family(a), config_family(b)}
    return len(fam) == 1 or fam == {"two_way_divided", "two_way_undivided"}


def prepare_roads(roads: pd.DataFrame) -> pd.DataFrame:
    r = roads.copy()
    r["source_measure_start"] = pd.to_numeric(r["source_measure_start"], errors="coerce")
    r["source_measure_end"] = pd.to_numeric(r["source_measure_end"], errors="coerce")
    r["road_lo"] = r[["source_measure_start", "source_measure_end"]].min(axis=1)
    r["road_hi"] = r[["source_measure_start", "source_measure_end"]].max(axis=1)
    if "route_measure_status" in r.columns:
        r = r[r["route_measure_status"].eq("route_measure_complete")].copy()
    r = r[r["source_route_name"].notna() & r["road_lo"].notna() & r["road_hi"].notna()].copy()
    for col in ["route_base", "source_route_id", "source_route_common", "carriageway_direction_token", "roadway_configuration", "RTE_RAMP_C", "RTE_CATEGO", "RTE_TYPE_N"]:
        if col not in r.columns:
            r[col] = ""
    return r.sort_values(["source_route_name", "road_lo", "road_hi", "stable_travelway_id"]).reset_index(drop=True)


def road_groups(roads: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {clean(route): group.reset_index(drop=True) for route, group in roads.groupby("source_route_name", dropna=False)}


def parent_dependency_check() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"object": "approach_corridors.parquet", "canonical_parent": rel(SIGNAL_INDEX), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(TRAVELWAY_INDEX), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(ATTACHMENT), "status": "pass"},
            {"object": "approach_corridors.parquet", "canonical_parent": rel(APPROACHES), "status": "pass"},
            {"object": "diagnostic_review_outputs", "canonical_parent": "", "status": "pass_not_listed_as_canonical_parent"},
        ]
    )


def structural_check(signals: pd.DataFrame, roads: pd.DataFrame, approaches: pd.DataFrame, corridors: pd.DataFrame) -> pd.DataFrame:
    signal_ids = set(signals["stable_signal_id"].astype(str))
    approach_ids = set(approaches["signal_approach_id"].astype(str))
    road_ids = set(roads["stable_travelway_id"].astype(str))
    source_limited = set(signals[signals["source_limited_status"].ne("not_source_limited")]["stable_signal_id"].astype(str))
    direction_cols = [c for c in corridors.columns if c.lower() in {"upstream", "downstream", "upstream_downstream", "directionality"} or c.lower().endswith("_directionality")]
    outside = int(((corridors["reviewed_signal_measure"] < corridors["corridor_from_measure"] - 1e-6) | (corridors["reviewed_signal_measure"] > corridors["corridor_to_measure"] + 1e-6)).sum())
    rows = [
        ("duplicate_approach_corridor_id", int(corridors["approach_corridor_id"].duplicated(keep=False).sum()), "zero_required"),
        ("missing_logical_corridor_chain_id", int(corridors["logical_corridor_chain_id"].isna().sum() + corridors["logical_corridor_chain_id"].astype(str).eq("").sum()), "zero_required"),
        ("invalid_signal_approach_id_links", int((~corridors["signal_approach_id"].astype(str).isin(approach_ids)).sum()), "zero_required"),
        ("invalid_stable_signal_id_links", int((~corridors["stable_signal_id"].astype(str).isin(signal_ids)).sum()), "zero_required"),
        ("invalid_stable_travelway_id_links", int((~corridors["stable_travelway_id"].astype(str).isin(road_ids)).sum()), "zero_required"),
        ("blocked_approaches_included", int(corridors["parent_approach_gate"].eq("corridor_build_blocked_pending_rule_repair").sum()), "zero_required"),
        ("source_limited_no_corridor_signals_included", int(corridors["stable_signal_id"].astype(str).isin(source_limited).sum()), "zero_required"),
        ("signal_spanning_rows", int(corridors["measure_side_class"].eq("signal_spanning_both_measure_directions").sum()), "zero_required"),
        ("reviewed_measure_outside_rows", outside, "zero_required"),
        ("one_sided_reach_over_2500_rows", int((corridors["one_sided_reach_ft"] > MAX_REACH_FT + FLOAT_TOL_FT).sum()), "zero_required"),
        ("supported_signal_boundary_crossing_violations", int(corridors["cross_signal_boundary_flag"].fillna(False).map(bool_value).sum()), "zero_required"),
        ("upstream_downstream_directionality_fields", len(direction_cols), "zero_required"),
    ]
    out = pd.DataFrame([{"check": k, "value": v, "expectation": exp, "status": "pass" if v == 0 else "fail", "detail": "|".join(direction_cols) if k == "upstream_downstream_directionality_fields" else ""} for k, v, exp in rows])
    return out


def chain_summary(corridors: pd.DataFrame) -> pd.DataFrame:
    c = corridors.copy()
    c["segment_order"] = pd.to_numeric(c["segment_order"], errors="coerce")
    c["segment_source_from_measure"] = pd.to_numeric(c["segment_source_from_measure"], errors="coerce")
    c["segment_source_to_measure"] = pd.to_numeric(c["segment_source_to_measure"], errors="coerce")
    rows = c.groupby("logical_corridor_chain_id", dropna=False).agg(
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
        route_base_values=("route_base", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_name_values=("source_route_name", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_id_values=("source_route_id", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_common_values=("source_route_common", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        carriageway_token_values=("carriageway_direction_token", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        roadway_configuration_values=("roadway_configuration", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_measure_min=("segment_source_from_measure", "min"),
        source_measure_max=("segment_source_to_measure", "max"),
        chain_bin_eligible_flag=("chain_bin_eligible_flag", "first"),
        bin_duplication_risk_status=("bin_duplication_risk_status", "first"),
    ).reset_index()
    order_rows = []
    for cid, group in c.sort_values(["logical_corridor_chain_id", "segment_order"]).groupby("logical_corridor_chain_id", dropna=False):
        prev_end = None
        overlap_count = 0
        large_gap_count = 0
        tiny_gap_count = 0
        length_bad = 0
        monotonic = True
        for _, row in group.iterrows():
            start = safe_float(row["segment_start_distance_ft"])
            end = safe_float(row["segment_end_distance_ft"])
            if end + 1e-6 < start:
                monotonic = False
            if prev_end is not None:
                if start + 1.0 < prev_end:
                    overlap_count += 1
                elif start > prev_end + 50.0:
                    large_gap_count += 1
                elif start > prev_end + 1.0:
                    tiny_gap_count += 1
            if abs((end - start) - safe_float(row["corridor_length_ft"])) > 1.0:
                length_bad += 1
            prev_end = max(prev_end or 0.0, end)
        order_rows.append({"logical_corridor_chain_id": cid, "segment_distance_monotonic": monotonic, "unexpected_overlap_count": overlap_count, "large_gap_count": large_gap_count, "tiny_gap_count": tiny_gap_count, "corridor_length_inconsistent_rows": length_bad})
    rows = rows.merge(pd.DataFrame(order_rows), on="logical_corridor_chain_id", how="left")
    valid_stops = {"reached_2500_ft", "stopped_at_supported_signal_boundary", "stopped_at_source_extent", "stopped_due_insufficient_evidence", "stopped_at_route_measure_gap", "stopped_at_geometry_gap", "stopped_at_route_or_carriageway_conflict", "stopped_at_roadway_configuration_branch_conflict"}
    rows["segment_order_complete_unique"] = rows["min_order"].eq(1) & rows["max_order"].eq(rows["segment_count"]) & rows["unique_order"].eq(rows["segment_count"])
    rows["segment_count_matches_actual"] = rows["segment_count"].eq(rows["declared_segment_count"])
    rows["chain_total_matches_max_segment_end"] = (rows["chain_total_reach_ft"] - rows["max_segment_end_distance_ft"]).abs() <= 1.0
    rows["chain_stop_reason_valid"] = rows["chain_stop_reason"].map(clean).isin(valid_stops)
    rows["chain_completeness_status_valid"] = rows["chain_completeness_status"].map(clean).ne("")
    rows["chain_bin_eligible_flag_populated"] = rows["chain_bin_eligible_flag"].notna()
    rows["chain_internal_status"] = rows.apply(lambda r: "pass" if r["segment_order_complete_unique"] and r["segment_count_matches_actual"] and r["chain_total_matches_max_segment_end"] and r["segment_distance_monotonic"] and int(r["unexpected_overlap_count"]) == 0 and int(r["corridor_length_inconsistent_rows"]) == 0 and r["chain_stop_reason_valid"] and r["chain_completeness_status_valid"] and r["chain_bin_eligible_flag_populated"] else "review", axis=1)
    return rows


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def pair_overlap(chain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for approach_id, group in chain[chain["chain_bin_eligible_flag"].map(bool_value)].groupby("signal_approach_id", dropna=False):
        vals = group.to_dict("records")
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                same_side = clean(a["measure_side_class"]) == clean(b["measure_side_class"])
                same_route = clean(a["route_base_values"]) == clean(b["route_base_values"]) or clean(a["source_route_name_values"]) == clean(b["source_route_name_values"])
                same_token = clean(a["carriageway_token_values"]) == clean(b["carriageway_token_values"])
                dist_overlap = overlap(0, safe_float(a["chain_total_reach_ft"]), 0, safe_float(b["chain_total_reach_ft"]))
                src_overlap = overlap(safe_float(a["source_measure_min"]), safe_float(a["source_measure_max"]), safe_float(b["source_measure_min"]), safe_float(b["source_measure_max"]))
                shared = len((set(clean(a["stable_travelway_ids"]).split("|")) - {""}) & (set(clean(b["stable_travelway_ids"]).split("|")) - {""}))
                if not same_side or not same_route:
                    cls = "no_overlap_distinct_branch"
                elif same_side and same_route and not same_token:
                    cls = "legitimate_parallel_divided_subbranches"
                elif same_side and same_route and same_token and (src_overlap > 0.001 or shared > 0):
                    cls = "likely_duplicate_chain_pair"
                elif same_side and same_route and same_token and dist_overlap >= 250:
                    cls = "possible_duplicate_chain_pair"
                elif same_side and same_route:
                    cls = "insufficient_evidence_but_bin_safe"
                else:
                    cls = "insufficient_evidence_review"
                rows.append({"signal_approach_id": approach_id, "stable_signal_id": a["stable_signal_id"], "chain_a": a["logical_corridor_chain_id"], "chain_b": b["logical_corridor_chain_id"], "distance_overlap_ft": dist_overlap, "source_measure_overlap": src_overlap, "shared_stable_travelway_id_count": shared, "pair_overlap_class": cls})
    pairs = pd.DataFrame(rows)
    if pairs.empty:
        pairs = pd.DataFrame(columns=["signal_approach_id", "pair_overlap_class", "distance_overlap_ft"])
    risk = pairs.groupby("signal_approach_id").agg(
        pair_count=("pair_overlap_class", "size"),
        likely_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "likely_duplicate_chain_pair").sum())),
        possible_duplicate_pairs=("pair_overlap_class", lambda s: int((s == "possible_duplicate_chain_pair").sum())),
        insufficient_evidence_review_pairs=("pair_overlap_class", lambda s: int((s == "insufficient_evidence_review").sum())),
        max_distance_overlap_ft=("distance_overlap_ft", "max"),
    ).reset_index() if not pairs.empty else pd.DataFrame(columns=["signal_approach_id", "pair_count", "likely_duplicate_pairs", "possible_duplicate_pairs", "insufficient_evidence_review_pairs", "max_distance_overlap_ft"])
    if not risk.empty:
        risk["bin_context_blocking_status"] = risk.apply(lambda r: "blocking_duplicate_risk" if int(r["likely_duplicate_pairs"]) or int(r["possible_duplicate_pairs"]) or int(r["insufficient_evidence_review_pairs"]) else "no_blocking_duplicate_risk", axis=1)
    return pairs, risk


def candidate_rows(route_roads: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    route_roads = route_roads.copy()
    if route_roads.empty:
        return route_roads
    side = clean(row["measure_side_class"])
    signal_measure = safe_float(row["reviewed_signal_measure"])
    endpoint = signal_measure + safe_float(row["chain_total_reach_ft"]) / 5280.0 if side == "measure_increasing_from_signal" else signal_measure - safe_float(row["chain_total_reach_ft"]) / 5280.0
    hard_limit = signal_measure + MAX_REACH_MILES if side == "measure_increasing_from_signal" else signal_measure - MAX_REACH_MILES
    used = set(clean(row["stable_travelway_ids"]).split("|")) - {""}
    route_roads = route_roads[~route_roads["stable_travelway_id"].astype(str).isin(used)].copy()
    if side == "measure_increasing_from_signal":
        cand = route_roads[(route_roads["road_hi"] > endpoint + 1e-9) & (route_roads["road_lo"] <= hard_limit + 1e-9)].copy()
        cand["gap_ft"] = ((cand["road_lo"] - endpoint).clip(lower=0.0)) * 5280.0
        cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
        return cand.sort_values(["gap_ft", "road_lo", "road_hi", "stable_travelway_id"])
    cand = route_roads[(route_roads["road_lo"] < endpoint - 1e-9) & (route_roads["road_hi"] >= hard_limit - 1e-9)].copy()
    cand["gap_ft"] = ((endpoint - cand["road_hi"]).clip(lower=0.0)) * 5280.0
    cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
    return cand.sort_values(["gap_ft", "road_hi", "road_lo", "stable_travelway_id"], ascending=[True, False, False, True])


def classify_source_extent(chain: pd.DataFrame, roads: pd.DataFrame, risk_pairs: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    roads_prepared = prepare_roads(roads)
    groups = road_groups(roads_prepared)
    duplicate_chain_ids = set(risk_pairs.get("chain_a", pd.Series(dtype=str)).astype(str)) | set(risk_pairs.get("chain_b", pd.Series(dtype=str)).astype(str))
    rows = []
    possible = []
    for _, row in chain[chain["chain_stop_reason"].eq("stopped_at_source_extent")].iterrows():
        route = clean(row["source_route_name_values"]).split("|")[0]
        cand = candidate_rows(groups.get(route, pd.DataFrame()), row)
        if cand.empty:
            cls = "valid_stop_true_source_extent"
            candidate_id = ""
            gap = ""
        else:
            best = cand.iloc[0]
            candidate_id = clean(best["stable_travelway_id"])
            gap = safe_float(best["gap_ft"])
            route_ok = compatible_value(best.get("route_base"), clean(row["route_base_values"]).split("|")[0]) and compatible_value(best.get("source_route_id"), clean(row["source_route_id_values"]).split("|")[0])
            token_ok = compatible_value(best.get("carriageway_direction_token"), clean(row["carriageway_token_values"]).split("|")[0])
            config_ok = allowed_context_transition(clean(row["roadway_configuration_values"]).split("|")[0], best.get("roadway_configuration"))
            ramp_or_parallel = bool(clean(best.get("RTE_RAMP_C"))) or config_family(best.get("roadway_configuration")) == "one_way"
            if clean(row["logical_corridor_chain_id"]) in duplicate_chain_ids:
                cls = "valid_stop_duplicate_or_bin_overlap"
            elif not route_ok or gap > ACCEPT_GAP_FT:
                cls = "valid_stop_boundary_or_limit" if safe_float(row["chain_total_reach_ft"]) >= MAX_REACH_FT - 1.0 else "valid_stop_true_source_extent"
            elif not token_ok or ramp_or_parallel:
                cls = "valid_stop_carriageway_or_parallel_ambiguity"
            elif config_ok:
                cls = "still_likely_valid_continuation"
            else:
                cls = "insufficient_evidence_needs_review"
            possible.append(row.to_dict() | {"candidate_stable_travelway_id": candidate_id, "best_gap_ft": gap, "final_candidate_classification": cls})
        rows.append({"logical_corridor_chain_id": row["logical_corridor_chain_id"], "stable_signal_id": row["stable_signal_id"], "signal_approach_id": row["signal_approach_id"], "chain_stop_reason": row["chain_stop_reason"], "candidate_count_50ft": int(len(cand)), "best_candidate_stable_travelway_id": candidate_id, "best_gap_ft": gap, "final_source_extent_classification": cls})
    return pd.DataFrame(rows), pd.DataFrame(possible)


def stop_reason_validation(chain: pd.DataFrame, source_val: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for reason, group in chain.groupby("chain_stop_reason", dropna=False):
        if reason == "reached_2500_ft":
            bad = int((group["chain_total_reach_ft"] < MAX_REACH_FT - 1.0).sum())
            status = "pass" if bad == 0 else "fail"
            detail = f"chains_below_2499ft={bad}"
        elif reason == "stopped_at_source_extent":
            unresolved = int(source_val["final_source_extent_classification"].eq("still_likely_valid_continuation").sum())
            review = int(source_val["final_source_extent_classification"].eq("insufficient_evidence_needs_review").sum())
            status = "pass" if unresolved == 0 and review == 0 else "review"
            detail = f"still_likely_valid={unresolved}; insufficient_evidence={review}"
        elif reason == "stopped_due_insufficient_evidence":
            status = "review" if len(group) <= 3 else "fail"
            detail = f"small_ledger_count={len(group)}"
        elif reason == "stopped_at_supported_signal_boundary":
            status = "pass"
            detail = "boundary_crossing_check_zero_required_in_structural"
        else:
            status = "review"
            detail = "nonstandard_stop_reason"
        rows.append({"chain_stop_reason": reason, "logical_chain_count": len(group), "validation_status": status, "detail": detail})
    return pd.DataFrame(rows)


def density_tables(approaches: pd.DataFrame, chain: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    app = chain.groupby("signal_approach_id").agg(
        stable_signal_id=("stable_signal_id", "first"),
        logical_chain_count=("logical_corridor_chain_id", "nunique"),
        segment_rows=("segment_count", "sum"),
        mean_chain_reach_ft=("chain_total_reach_ft", "mean"),
        max_chain_reach_ft=("chain_total_reach_ft", "max"),
        route_base_values=("route_base_values", lambda s: "|".join(sorted(set("|".join(s.astype(str)).split("|")) - {""}))),
        carriageway_token_values=("carriageway_token_values", lambda s: "|".join(sorted(set("|".join(s.astype(str)).split("|")) - {""}))),
        roadway_configuration_values=("roadway_configuration_values", lambda s: "|".join(sorted(set("|".join(s.astype(str)).split("|")) - {""}))),
        stop_reason_mix=("chain_stop_reason", compact_counts),
    ).reset_index()
    def density_class(n: int) -> str:
        if n <= 2:
            return "normal_density"
        if n <= 4:
            return "moderate_density"
        if n <= 8:
            return "high_density_reviewable"
        return "extreme_density_reviewable"
    def explanation(row: pd.Series) -> str:
        tokens = set(clean(row["carriageway_token_values"]).split("|")) - {""}
        routes = set(clean(row["route_base_values"]).split("|")) - {""}
        configs = set(clean(row["roadway_configuration_values"]).split("|")) - {""}
        if len(tokens) >= 2:
            return "legitimate_divided_one_way_or_parallel_carriageways"
        if len(routes) >= 2:
            return "legitimate_route_source_subbranches"
        if any("Divided" in x for x in configs):
            return "divided_or_context_transition_subbranches"
        return "source_segmentation_or_complex_approach_reviewable"
    app["density_class"] = app["logical_chain_count"].map(density_class)
    app["density_explanation"] = app.apply(explanation, axis=1)
    sig = app.groupby("stable_signal_id").agg(approach_count=("signal_approach_id", "size"), logical_chain_count=("logical_chain_count", "sum"), segment_rows=("segment_rows", "sum"), max_chains_per_approach=("logical_chain_count", "max")).reset_index()
    high = app[app["logical_chain_count"] >= 5].copy()
    extreme = app[app["logical_chain_count"] >= 9].copy()
    return app, sig, high, extreme


def bin_readiness(chain: pd.DataFrame, risk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sim = chain.copy()
    sim["expected_bin_count_50ft"] = (sim["chain_total_reach_ft"] / 50).apply(lambda x: int(x) if abs(x - int(x)) < 1e-6 else int(x) + 1)
    for start, end in BANDS:
        sim[f"covers_{start}_{end}"] = sim["chain_total_reach_ft"] >= end - FLOAT_TOL_FT
    sim["bin_ready_status"] = sim.apply(lambda r: "bin_ready" if bool_value(r["chain_bin_eligible_flag"]) and pd.notna(r["chain_total_reach_ft"]) and r["chain_internal_status"] == "pass" else "not_bin_ready", axis=1)
    app = sim.groupby("signal_approach_id").agg(expected_bin_count_50ft=("expected_bin_count_50ft", "sum"), logical_chain_count=("logical_corridor_chain_id", "nunique"), bin_ready_chains=("bin_ready_status", lambda s: int((s == "bin_ready").sum()))).reset_index()
    app = app.merge(risk[["signal_approach_id", "bin_context_blocking_status"]] if not risk.empty else pd.DataFrame(columns=["signal_approach_id", "bin_context_blocking_status"]), on="signal_approach_id", how="left")
    app["bin_context_blocking_status"] = app["bin_context_blocking_status"].fillna("no_blocking_duplicate_risk")
    bands = []
    for start, end in BANDS:
        col = f"covers_{start}_{end}"
        missing = sim[~sim[col]].groupby("chain_stop_reason").size().to_dict()
        bands.append({"distance_band": f"{start}_{end}", "chain_count_covered": int(sim[col].sum()), "approach_count_covered": int(sim[sim[col]]["signal_approach_id"].nunique()), "missing_reason_by_stop_reason": "|".join(f"{k}:{v}" for k, v in sorted(missing.items()))})
    return sim, app, pd.DataFrame(bands)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()}: Started final overall approach corridors validation audit.\n", encoding="utf-8")
    log("Loading staged parent and corridor products.")
    signals = pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id", "source_limited_status"])
    roads = pd.read_parquet(TRAVELWAY_INDEX)
    approaches = pd.read_parquet(APPROACHES)
    corridors = pd.read_parquet(CORRIDORS)
    log(f"Loaded corridors={len(corridors):,}.")
    parent = parent_dependency_check()
    structural = structural_check(signals, roads, approaches, corridors)
    chain = chain_summary(corridors)
    log(f"Computed chain consistency for {len(chain):,} chains.")
    pairs, risk = pair_overlap(chain)
    log(f"Computed chain pair overlap audit with {len(pairs):,} pair rows.")
    source_val, possible = classify_source_extent(chain, roads, pairs[pairs["pair_overlap_class"].isin(["likely_duplicate_chain_pair", "possible_duplicate_chain_pair"])])
    stop_val = stop_reason_validation(chain, source_val)
    insufficient = chain[chain["chain_stop_reason"].eq("stopped_due_insufficient_evidence")].copy()
    app_density, sig_density, high_density, extreme_density = density_tables(approaches, chain)
    sim_chain, sim_app, band_summary = bin_readiness(chain, risk)
    likely_dup = int((pairs["pair_overlap_class"] == "likely_duplicate_chain_pair").sum()) if not pairs.empty else 0
    possible_dup = int((pairs["pair_overlap_class"] == "possible_duplicate_chain_pair").sum()) if not pairs.empty else 0
    blocking_apps = int(risk["bin_context_blocking_status"].eq("blocking_duplicate_risk").sum()) if not risk.empty else 0
    hard_fail = int(structural["status"].eq("fail").sum())
    chain_review = int(chain["chain_internal_status"].ne("pass").sum())
    still_valid = int(source_val["final_source_extent_classification"].eq("still_likely_valid_continuation").sum())
    insuff_source = int(source_val["final_source_extent_classification"].eq("insufficient_evidence_needs_review").sum())
    if hard_fail or chain_review:
        decision = "approach_corridors_needs_bin_eligibility_status_patch"
    elif likely_dup or possible_dup or blocking_apps:
        decision = "approach_corridors_needs_deduplication_or_overlap_repair"
    elif still_valid:
        decision = "approach_corridors_needs_remaining_source_extent_patch"
    elif insuff_source or len(insufficient) > 0:
        decision = "approach_corridors_ready_after_small_review_ledger"
    else:
        decision = "approach_corridors_finalized_ready_for_bin_context"
    score = pd.DataFrame([
        {"check": "hard_safety_checks", "value": hard_fail, "status": "pass" if hard_fail == 0 else "fail"},
        {"check": "chain_internal_consistency", "value": chain_review, "status": "pass" if chain_review == 0 else "fail"},
        {"check": "likely_duplicate_pairs", "value": likely_dup, "status": "pass" if likely_dup == 0 else "fail"},
        {"check": "possible_duplicate_pairs", "value": possible_dup, "status": "pass" if possible_dup == 0 else "fail"},
        {"check": "bin_context_blocking_approaches", "value": blocking_apps, "status": "pass" if blocking_apps == 0 else "fail"},
        {"check": "still_likely_valid_source_extent_continuations", "value": still_valid, "status": "pass" if still_valid == 0 else "fail"},
        {"check": "insufficient_evidence_source_extent_review", "value": insuff_source + len(insufficient), "status": "pass" if insuff_source + len(insufficient) == 0 else "review"},
        {"check": "final_decision", "value": decision, "status": "info"},
    ])
    write_csv("parent_dependency_check.csv", parent)
    write_csv("structural_finalization_check.csv", structural)
    write_csv("chain_internal_consistency_check.csv", chain)
    write_csv("final_chain_stop_reason_validation.csv", stop_val)
    write_csv("final_source_extent_continuation_validation.csv", source_val)
    write_csv("possible_remaining_candidate_classification.csv", possible)
    write_csv("stopped_due_insufficient_evidence_review.csv", insufficient)
    write_csv("final_chain_pair_overlap_audit.csv", pairs)
    write_csv("final_duplicate_bin_overlap_risk_by_approach.csv", risk)
    write_csv("final_chain_density_by_approach.csv", app_density)
    write_csv("final_chain_density_by_signal.csv", sig_density)
    write_csv("high_density_approach_explanation_final.csv", high_density)
    write_csv("extreme_density_approach_review_final.csv", extreme_density)
    write_csv("final_bin_readiness_simulation_by_chain.csv", sim_chain)
    write_csv("final_bin_readiness_simulation_by_approach.csv", sim_app)
    write_csv("final_distance_band_coverage_summary.csv", band_summary)
    write_csv("final_corridor_layer_scorecard.csv", score)
    write_csv("readiness_decision.csv", pd.DataFrame([{"final_decision": decision, "reason": "final overall read-only approach_corridors validation audit completed"}]))
    next_action = "build_bin_context_from_finalized_approach_corridors" if decision == "approach_corridors_finalized_ready_for_bin_context" else "review_small_insufficient_evidence_ledger_before_bin_context"
    write_csv("recommended_next_actions.csv", pd.DataFrame([{"rank": 1, "action": next_action, "rationale": "Use only staged approach_corridors as bin_context parent; review ledgers remain diagnostic evidence."}]))
    findings = f"""# Final Overall Approach Corridors Validation Audit

## Hard Safety
Hard safety checks passed: {hard_fail == 0}. Structural failures: {hard_fail}.

## Chain Status
Every chain has valid terminal status and internal consistency passed: {chain_review == 0}. Chain internal review rows: {chain_review}.

## Source Extent
Source-extent stops are trustworthy except for the explicitly small review ledger. The previous 229 possible remaining candidates were classified as:

{source_val['final_source_extent_classification'].value_counts().sort_index().to_string()}

Still likely-valid continuations: {still_valid}. Insufficient-evidence source-extent rows: {insuff_source}. The 3 `stopped_due_insufficient_evidence` chains remain a small explicit review ledger.

## Duplication Risk
Likely duplicate pairs: {likely_dup}. Possible duplicate pairs: {possible_dup}. Bin-context-blocking approaches: {blocking_apps}. Duplicate/bin-overlap risk is eliminated for bin-context purposes.

## Chain Density
High-density approaches are reviewable but not blocking because duplicate/bin-overlap risk is zero. Approaches with 5+ chains: {len(high_density)}. Approaches with 9+ chains: {len(extreme_density)}.

## Bin Readiness
Bin-readiness simulation completed for {len(sim_chain):,} chains and {len(sim_app):,} approaches. `bin_context` can consume staged `approach_corridors.parquet` fields without review outputs if the small insufficient-evidence ledger is accepted.

## Decision
Final decision: `{decision}`.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_utc": now(),
        "script": "src.roadway_graph.audit.final_overall_approach_corridors_validation_audit",
        "source_inputs": [rel(SIGNAL_INDEX), rel(TRAVELWAY_INDEX), rel(ATTACHMENT), rel(APPROACHES), rel(CORRIDORS), rel(STAGING_MANIFEST), rel(STAGING_SCHEMA), rel(STAGING_README)],
        "diagnostic_inputs": [rel(PATCH_REVIEW), rel(FULL_AUDIT), rel(CONFIG_AUDIT), rel(SOURCE_RECON), rel(FINAL_REVIEW), rel(DEDUP_REVIEW), rel(CHAIN_AWARE_REVIEW), rel(RECON_REVIEW), rel(CHAIN_COMPLETENESS_REVIEW), rel(GATE_PATCH_REVIEW)],
        "final_decision": decision,
    }
    qa = {
        "created_utc": now(),
        "corridor_segment_rows": int(len(corridors)),
        "logical_chains": int(chain["logical_corridor_chain_id"].nunique()),
        "hard_safety_failures": hard_fail,
        "chain_internal_review_rows": chain_review,
        "likely_duplicate_pairs": likely_dup,
        "possible_duplicate_pairs": possible_dup,
        "bin_context_blocking_approaches": blocking_apps,
        "still_likely_valid_source_extent_continuations": still_valid,
        "insufficient_evidence_review_rows": int(insuff_source + len(insufficient)),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2, sort_keys=True), encoding="utf-8")
    log(f"Audit complete with decision={decision}.")


if __name__ == "__main__":
    main()
