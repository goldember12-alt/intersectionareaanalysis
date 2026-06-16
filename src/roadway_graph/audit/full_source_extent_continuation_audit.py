"""Read-only full source-extent continuation audit for approach corridors.

Audits every current stopped_at_source_extent logical corridor chain and
classifies possible same-corridor continuation candidates. This script does
not modify staged products or prior review outputs.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from shapely import wkb


REPO = Path(__file__).resolve().parents[3]
STAGING = REPO / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_rebuild_candidate"
OUT = REPO / "work/roadway_graph/review/full_source_extent_continuation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

CONFIG_AUDIT = REPO / "work/roadway_graph/review/roadway_configuration_conflict_continuation_audit"
SOURCE_RECON = REPO / "work/roadway_graph/review/source_extent_suspect_chain_reconciliation_audit"
FINAL_REVIEW = REPO / "work/roadway_graph/review/finalize_approach_corridors_validation_audit"
REPAIR_REVIEW = REPO / "work/roadway_graph/review/repair_approach_corridor_source_extent_continuation"
DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"

RULE_VERSION = "full_source_extent_continuation_audit_v1"
MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
SEARCH_GAP_FT = 50.0
ZERO_GAP_TOL_FT = 1.0
SMALL_GAP_TOL_FT = 5.0
GEOMETRY_NEAR_TOL_FT = 75.0


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


def load_inputs() -> dict[str, pd.DataFrame]:
    log("Loading staged products, staging metadata references, and diagnostic outputs.")
    return {
        "signals": pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id"]),
        "roads": pd.read_parquet(TRAVELWAY_INDEX),
        "attachments": pd.read_parquet(ATTACHMENT),
        "approaches": pd.read_parquet(APPROACHES, columns=["signal_approach_id", "stable_signal_id", "corridor_build_gate"]),
        "corridors": pd.read_parquet(CORRIDORS),
        "config_classification": read_csv_optional(CONFIG_AUDIT / "roadway_configuration_conflict_classification.csv"),
        "source_reconciliation": read_csv_optional(SOURCE_RECON / "suspect_chain_reconciliation.csv"),
        "source_candidates": read_csv_optional(SOURCE_RECON / "suspect_chain_candidate_evaluations.csv"),
        "finalization_suspects": read_csv_optional(FINAL_REVIEW / "likely_source_extent_false_stops.csv"),
        "repair_summary": read_csv_optional(REPAIR_REVIEW / "source_extent_repair_summary.csv"),
        "dedup_suppressed": read_csv_optional(DEDUP_REVIEW / "suppressed_duplicate_chain_ledger.csv"),
        "reconstruct_attempts": read_csv_optional(RECON_REVIEW / "neighbor_extension_attempts.csv"),
    }


def prepare_roads(roads: pd.DataFrame) -> pd.DataFrame:
    r = roads.copy()
    r["source_measure_start"] = pd.to_numeric(r["source_measure_start"], errors="coerce")
    r["source_measure_end"] = pd.to_numeric(r["source_measure_end"], errors="coerce")
    r["road_lo"] = r[["source_measure_start", "source_measure_end"]].min(axis=1)
    r["road_hi"] = r[["source_measure_start", "source_measure_end"]].max(axis=1)
    if "route_measure_status" in r.columns:
        r = r[r["route_measure_status"].eq("route_measure_complete")].copy()
    r = r[r["source_route_name"].notna() & r["road_lo"].notna() & r["road_hi"].notna()].copy()
    r = r[r["road_hi"] >= r["road_lo"]].copy()
    for col in [
        "stable_travelway_id",
        "route_base",
        "source_route_name",
        "source_route_id",
        "source_route_common",
        "carriageway_direction_token",
        "roadway_configuration",
        "RIM_MEDIAN",
        "RIM_ACCESS",
        "RIM_FACILITY",
        "RTE_CATEGO",
        "RTE_TYPE_N",
        "RTE_RAMP_C",
        "RIM_TRAVEL",
        "geometry",
    ]:
        if col not in r.columns:
            r[col] = ""
    return r.sort_values(["source_route_name", "road_lo", "road_hi", "stable_travelway_id"]).reset_index(drop=True)


def road_groups(roads: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {clean(route): group.reset_index(drop=True) for route, group in roads.groupby("source_route_name", dropna=False)}


def make_boundary_groups(attachments: pd.DataFrame) -> dict[str, pd.DataFrame]:
    a = attachments.copy()
    for optional in ["source_route_name", "carriageway_direction_token", "roadway_configuration", "source_signal_globalid"]:
        if optional not in a.columns:
            a[optional] = ""
    b = a[
        a["attachment_confidence"].isin(["high", "medium"])
        & a["estimated_measure_status"].eq("estimated_measure_projected")
        & a["usable_as_corridor_boundary"].fillna(False).astype(bool)
        & a["estimated_measure"].notna()
    ].copy()
    b["estimated_measure"] = pd.to_numeric(b["estimated_measure"], errors="coerce")
    b = b[b["estimated_measure"].notna()].copy()
    return {clean(route): group.sort_values("estimated_measure").reset_index(drop=True) for route, group in b.groupby("source_route_name", dropna=False)}


def config_family(config: Any) -> str:
    text = clean(config).lower()
    if "two-way undivided" in text:
        return "two_way_undivided"
    if "two-way divided" in text:
        return "two_way_divided"
    if "one-way divided" in text:
        return "one_way_divided"
    if "one-way undivided" in text:
        return "one_way_undivided"
    if "reversible" in text:
        return "reversible"
    if "trail" in text:
        return "trail"
    return "unknown"


def compatible_value(a: Any, b: Any) -> bool:
    aa = clean(a).lower()
    bb = clean(b).lower()
    unknown = {"", "unknown", "nan", "none", "null", "<na>"}
    return aa == bb or aa in unknown or bb in unknown


def ramp_like(values: dict[str, Any], prefix: str = "") -> bool:
    text = " ".join(
        clean(values.get(f"{prefix}{k}"))
        for k in ["RTE_RAMP_C", "RTE_CATEGO", "RTE_TYPE_N", "source_route_common", "roadway_configuration"]
    ).lower()
    return bool(clean(values.get(f"{prefix}RTE_RAMP_C"))) or "ramp" in text


def endpoint_distance(a: Any, b: Any) -> tuple[str, float | str]:
    try:
        ga = wkb.loads(a) if isinstance(a, (bytes, bytearray, memoryview)) else wkb.loads(bytes(a))
        gb = wkb.loads(b) if isinstance(b, (bytes, bytearray, memoryview)) else wkb.loads(bytes(b))
        a_coords = list(ga.coords) if hasattr(ga, "coords") else []
        b_coords = list(gb.coords) if hasattr(gb, "coords") else []
        if not a_coords or not b_coords:
            return "geometry_unavailable", ""
        endpoints_a = [a_coords[0], a_coords[-1]]
        endpoints_b = [b_coords[0], b_coords[-1]]
        best = min(math.dist(pa[:2], pb[:2]) for pa in endpoints_a for pb in endpoints_b)
        if best <= GEOMETRY_NEAR_TOL_FT:
            return "near_endpoint_continuity", best
        return "endpoint_distance_exceeds_tolerance", best
    except Exception:
        return "geometry_unavailable", ""


def chain_summary(corridors: pd.DataFrame) -> pd.DataFrame:
    c = corridors.copy()
    c["segment_order"] = pd.to_numeric(c["segment_order"], errors="coerce")
    c["segment_source_from_measure"] = pd.to_numeric(c["segment_source_from_measure"], errors="coerce")
    c["segment_source_to_measure"] = pd.to_numeric(c["segment_source_to_measure"], errors="coerce")
    grouped = c.groupby("logical_corridor_chain_id", dropna=False).agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        chain_stop_reason=("chain_stop_reason", "first"),
        chain_total_reach_ft=("chain_total_reach_ft", "first"),
        measure_side_class=("measure_side_class", "first"),
        reviewed_signal_measure=("reviewed_signal_measure", "first"),
        route_base_values=("route_base", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_name_values=("source_route_name", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_id_values=("source_route_id", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        source_route_common_values=("source_route_common", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        carriageway_token_values=("carriageway_direction_token", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        roadway_configuration_values=("roadway_configuration", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        stable_travelway_ids=("stable_travelway_id", lambda s: "|".join(sorted(set(map(clean, s)) - {""}))),
        chain_bin_eligible_flag=("chain_bin_eligible_flag", "first"),
        bin_duplication_risk_status=("bin_duplication_risk_status", "first"),
    ).reset_index()
    terminal = c.sort_values(["logical_corridor_chain_id", "segment_order", "segment_end_distance_ft"]).groupby("logical_corridor_chain_id", dropna=False).tail(1)
    terminal = terminal[["logical_corridor_chain_id", "stable_travelway_id", "geometry", "roadway_configuration"]].rename(
        columns={
            "stable_travelway_id": "terminal_stable_travelway_id",
            "geometry": "terminal_geometry",
            "roadway_configuration": "terminal_roadway_configuration",
        }
    )
    return grouped.merge(terminal, on="logical_corridor_chain_id", how="left")


def one_value(text: Any) -> str:
    return (clean(text).split("|") + [""])[0]


def endpoint_for(row: pd.Series) -> tuple[float, float, float]:
    signal_measure = safe_float(row.get("reviewed_signal_measure"))
    reach_ft = safe_float(row.get("chain_total_reach_ft"), 0.0)
    side = clean(row.get("measure_side_class"))
    if side == "measure_increasing_from_signal":
        return signal_measure, signal_measure + reach_ft / 5280.0, signal_measure + MAX_REACH_MILES
    if side == "measure_decreasing_from_signal":
        return signal_measure, signal_measure - reach_ft / 5280.0, signal_measure - MAX_REACH_MILES
    return signal_measure, float("nan"), float("nan")


def candidate_search(route_roads: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    signal_measure, endpoint, hard_limit = endpoint_for(row)
    side = clean(row.get("measure_side_class"))
    used = set(clean(row.get("stable_travelway_ids")).split("|")) - {""}
    if route_roads.empty or pd.isna(endpoint):
        return pd.DataFrame(columns=list(route_roads.columns) + ["gap_ft", "candidate_additional_reach_ft", "projected_reach_ft"])
    r = route_roads[~route_roads["stable_travelway_id"].astype(str).isin(used)].copy()
    if side == "measure_increasing_from_signal":
        cand = r[(r["road_hi"] > endpoint + 1e-9) & (r["road_lo"] <= hard_limit + 1e-9)].copy()
        cand["gap_ft"] = ((cand["road_lo"] - endpoint).clip(lower=0.0)) * 5280.0
        cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + 1e-6].copy()
        cand["candidate_start_measure"] = cand["road_lo"].clip(lower=endpoint)
        cand["candidate_end_measure"] = cand["road_hi"].clip(upper=hard_limit)
        cand["candidate_additional_reach_ft"] = (cand["candidate_end_measure"] - endpoint).clip(lower=0.0) * 5280.0
        cand["projected_reach_ft"] = (cand["candidate_end_measure"] - signal_measure).abs() * 5280.0
        return cand.sort_values(["gap_ft", "road_lo", "road_hi", "stable_travelway_id"])
    if side == "measure_decreasing_from_signal":
        cand = r[(r["road_lo"] < endpoint - 1e-9) & (r["road_hi"] >= hard_limit - 1e-9)].copy()
        cand["gap_ft"] = ((endpoint - cand["road_hi"]).clip(lower=0.0)) * 5280.0
        cand = cand[cand["gap_ft"] <= SEARCH_GAP_FT + 1e-6].copy()
        cand["candidate_start_measure"] = cand["road_hi"].clip(upper=endpoint)
        cand["candidate_end_measure"] = cand["road_lo"].clip(lower=hard_limit)
        cand["candidate_additional_reach_ft"] = (endpoint - cand["candidate_end_measure"]).clip(lower=0.0) * 5280.0
        cand["projected_reach_ft"] = (cand["candidate_end_measure"] - signal_measure).abs() * 5280.0
        return cand.sort_values(["gap_ft", "road_hi", "road_lo", "stable_travelway_id"], ascending=[True, False, False, True])
    return pd.DataFrame(columns=list(route_roads.columns) + ["gap_ft", "candidate_additional_reach_ft", "projected_reach_ft"])


def boundary_between(boundary_groups: dict[str, pd.DataFrame], row: pd.Series, candidate_start: float) -> dict[str, Any]:
    route = one_value(row.get("source_route_name_values"))
    side = clean(row.get("measure_side_class"))
    signal_measure, endpoint, _ = endpoint_for(row)
    signal_id = clean(row.get("stable_signal_id"))
    token = one_value(row.get("carriageway_token_values"))
    b = boundary_groups.get(route)
    if b is None or b.empty:
        return {"has_boundary": False, "boundary_signal_id": "", "boundary_measure": ""}
    b = b[~b["stable_signal_id"].astype(str).eq(signal_id)].copy()
    b = b[b["carriageway_direction_token"].map(lambda x: compatible_value(x, token))]
    if b.empty:
        return {"has_boundary": False, "boundary_signal_id": "", "boundary_measure": ""}
    if side == "measure_increasing_from_signal":
        between = b[(b["estimated_measure"] > max(signal_measure, endpoint) + 1e-9) & (b["estimated_measure"] <= candidate_start + 1e-9)]
        if between.empty:
            return {"has_boundary": False, "boundary_signal_id": "", "boundary_measure": ""}
        hit = between.sort_values("estimated_measure").iloc[0]
    else:
        between = b[(b["estimated_measure"] < min(signal_measure, endpoint) - 1e-9) & (b["estimated_measure"] >= candidate_start - 1e-9)]
        if between.empty:
            return {"has_boundary": False, "boundary_signal_id": "", "boundary_measure": ""}
        hit = between.sort_values("estimated_measure", ascending=False).iloc[0]
    return {"has_boundary": True, "boundary_signal_id": clean(hit.get("stable_signal_id")), "boundary_measure": float(hit["estimated_measure"])}


def duplicate_existing_route_space(corridors: pd.DataFrame, row: pd.Series, cand: pd.Series) -> bool:
    approach_id = clean(row.get("signal_approach_id"))
    chain_id = clean(row.get("logical_corridor_chain_id"))
    side = clean(row.get("measure_side_class"))
    route = one_value(row.get("source_route_name_values"))
    token = one_value(row.get("carriageway_token_values"))
    seg_lo = float(cand["road_lo"])
    seg_hi = float(cand["road_hi"])
    peers = corridors[
        corridors["signal_approach_id"].astype(str).eq(approach_id)
        & ~corridors["logical_corridor_chain_id"].astype(str).eq(chain_id)
        & corridors["measure_side_class"].astype(str).eq(side)
        & corridors["source_route_name"].astype(str).eq(route)
        & corridors["chain_bin_eligible_flag"].fillna(True).map(bool_value)
    ].copy()
    if peers.empty:
        return False
    peers = peers[peers["carriageway_direction_token"].map(lambda x: compatible_value(x, token))]
    if peers.empty:
        return False
    if peers["stable_travelway_id"].astype(str).eq(clean(cand.get("stable_travelway_id"))).any():
        return True
    overlap = (
        (pd.to_numeric(peers["segment_source_from_measure"], errors="coerce") <= seg_hi + 1e-9)
        & (pd.to_numeric(peers["segment_source_to_measure"], errors="coerce") >= seg_lo - 1e-9)
    ).any()
    return bool(overlap)


def suppressed_match(suppressed: pd.DataFrame, row: pd.Series, cand: pd.Series) -> bool:
    if suppressed.empty or "stable_travelway_id" not in suppressed.columns:
        return False
    mask = suppressed["stable_travelway_id"].astype(str).eq(clean(cand.get("stable_travelway_id")))
    if "signal_approach_id" in suppressed.columns:
        mask &= suppressed["signal_approach_id"].astype(str).eq(clean(row.get("signal_approach_id")))
    return bool(mask.any())


def classify_candidate(
    row: pd.Series,
    cand: pd.Series,
    corridors: pd.DataFrame,
    suppressed: pd.DataFrame,
    boundary_groups: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    current_config = clean(row.get("roadway_configuration_values")) or clean(row.get("terminal_roadway_configuration"))
    candidate_config = clean(cand.get("roadway_configuration"))
    current_family = config_family(current_config)
    candidate_family = config_family(candidate_config)
    route_ok = (
        clean(cand.get("source_route_name")) == one_value(row.get("source_route_name_values"))
        and compatible_value(cand.get("route_base"), one_value(row.get("route_base_values")))
        and compatible_value(cand.get("source_route_id"), one_value(row.get("source_route_id_values")))
        and compatible_value(cand.get("source_route_common"), one_value(row.get("source_route_common_values")))
    )
    token_ok = compatible_value(cand.get("carriageway_direction_token"), one_value(row.get("carriageway_token_values")))
    side_ok = clean(row.get("measure_side_class")) in {"measure_increasing_from_signal", "measure_decreasing_from_signal"}
    gap_ft = safe_float(cand.get("gap_ft"), 999999.0)
    measure_ok = gap_ft <= SMALL_GAP_TOL_FT
    geometry_status, endpoint_ft = endpoint_distance(row.get("terminal_geometry"), cand.get("geometry"))
    boundary = boundary_between(boundary_groups, row, safe_float(cand.get("candidate_start_measure")))
    duplicate_bin = duplicate_existing_route_space(corridors, row, cand)
    suppressed = suppressed_match(suppressed, row, cand)
    projected = safe_float(cand.get("projected_reach_ft"), safe_float(row.get("chain_total_reach_ft"), 0.0))
    exceeds = projected > MAX_REACH_FT + 1.0
    current_ramp = ramp_like(row.to_dict(), "")
    candidate_ramp = ramp_like({f"candidate_{k}": v for k, v in cand.to_dict().items()}, "candidate_")
    one_way_involved = current_family.startswith("one_way") or candidate_family.startswith("one_way")
    same_config = current_family == candidate_family
    divided_undivided = {current_family, candidate_family} == {"two_way_divided", "two_way_undivided"}
    context_transition_ok = (
        route_ok
        and token_ok
        and side_ok
        and measure_ok
        and not boundary["has_boundary"]
        and not duplicate_bin
        and not suppressed
        and not exceeds
        and not current_ramp
        and not candidate_ramp
        and geometry_status in {"near_endpoint_continuity", "geometry_unavailable"}
    )
    if boundary["has_boundary"]:
        final_class = "supported_signal_boundary_blocks_continuation"
        confidence = "high"
    elif suppressed:
        final_class = "duplicate_or_suppressed_candidate_stop_valid"
        confidence = "high"
    elif duplicate_bin:
        final_class = "continuation_would_create_bin_duplication"
        confidence = "high"
    elif exceeds:
        final_class = "candidate_exceeds_2500_ft"
        confidence = "high"
    elif not route_ok or not side_ok or not measure_ok:
        final_class = "route_or_measure_identity_conflict_stop_valid"
        confidence = "high"
    elif not token_ok or one_way_involved or current_ramp or candidate_ramp:
        final_class = "carriageway_or_parallel_road_ambiguity_stop_valid"
        confidence = "medium"
    elif same_config and context_transition_ok:
        final_class = "simple_context_transition_continuation_likely_valid"
        confidence = "high"
    elif divided_undivided and context_transition_ok:
        final_class = "configuration_transition_valid_but_needs_patch"
        confidence = "high"
    elif divided_undivided:
        final_class = "divided_undivided_transition_branch_aware_review"
        confidence = "medium"
    elif geometry_status == "endpoint_distance_exceeds_tolerance":
        final_class = "geometry_continuity_conflict_stop_valid"
        confidence = "medium"
    else:
        final_class = "insufficient_evidence_needs_review"
        confidence = "low"
    evidence = []
    if route_ok:
        evidence.append("same_route_base_name_id_common")
    if token_ok:
        evidence.append("compatible_carriageway_token")
    if measure_ok:
        evidence.append(f"gap_{gap_ft:.3f}ft")
    if same_config:
        evidence.append("same_roadway_configuration")
    if divided_undivided:
        evidence.append("divided_undivided_transition")
    if duplicate_bin:
        evidence.append("duplicate_bin_overlap")
    if suppressed:
        evidence.append("suppressed_duplicate_evidence")
    if one_way_involved or current_ramp or candidate_ramp:
        evidence.append("one_way_or_ramp_like")
    if boundary["has_boundary"]:
        evidence.append("supported_signal_boundary")
    evidence.append(geometry_status)
    band_improvement = expected_band_improvement(safe_float(row.get("chain_total_reach_ft"), 0.0), projected)
    return {
        "logical_corridor_chain_id": clean(row.get("logical_corridor_chain_id")),
        "stable_signal_id": clean(row.get("stable_signal_id")),
        "signal_approach_id": clean(row.get("signal_approach_id")),
        "measure_side_class": clean(row.get("measure_side_class")),
        "chain_stop_reason": clean(row.get("chain_stop_reason")),
        "chain_total_reach_ft": safe_float(row.get("chain_total_reach_ft"), 0.0),
        "current_route_base": clean(row.get("route_base_values")),
        "current_source_route_name": clean(row.get("source_route_name_values")),
        "current_source_route_id": clean(row.get("source_route_id_values")),
        "current_source_route_common": clean(row.get("source_route_common_values")),
        "current_carriageway_token": clean(row.get("carriageway_token_values")),
        "current_roadway_configuration": current_config,
        "terminal_stable_travelway_id": clean(row.get("terminal_stable_travelway_id")),
        "candidate_stable_travelway_id": clean(cand.get("stable_travelway_id")),
        "candidate_route_base": clean(cand.get("route_base")),
        "candidate_source_route_name": clean(cand.get("source_route_name")),
        "candidate_source_route_id": clean(cand.get("source_route_id")),
        "candidate_source_route_common": clean(cand.get("source_route_common")),
        "candidate_carriageway_token": clean(cand.get("carriageway_direction_token")),
        "candidate_roadway_configuration": candidate_config,
        "candidate_RIM_MEDIAN": clean(cand.get("RIM_MEDIAN")),
        "candidate_RIM_ACCESS": clean(cand.get("RIM_ACCESS")),
        "candidate_RIM_FACILITY": clean(cand.get("RIM_FACILITY")),
        "candidate_RTE_CATEGO": clean(cand.get("RTE_CATEGO")),
        "candidate_RTE_RAMP_C": clean(cand.get("RTE_RAMP_C")),
        "gap_or_overlap_distance_ft": gap_ft,
        "candidate_additional_reach_ft": safe_float(cand.get("candidate_additional_reach_ft"), 0.0),
        "projected_reach_ft_if_continued": projected,
        "route_identity_compatible": route_ok,
        "carriageway_token_compatible": token_ok,
        "measure_continuity_evidence": "zero_or_small_gap" if measure_ok else "gap_exceeds_small_gap_policy",
        "geometry_continuity_evidence": geometry_status,
        "geometry_endpoint_distance_ft": endpoint_ft,
        "supported_boundary_evidence": clean(boundary.get("boundary_signal_id")) if boundary["has_boundary"] else "",
        "duplicate_bin_overlap_evidence": duplicate_bin,
        "duplicate_suppressed_evidence": suppressed,
        "roadway_configuration_transition_family": f"{current_family}_to_{candidate_family}",
        "would_reach_full_2500ft_support": projected >= MAX_REACH_FT - 1.0,
        "expected_new_stop_reason_if_extended": expected_stop_reason(projected, boundary["has_boundary"]),
        "expected_added_reach_ft": safe_float(cand.get("candidate_additional_reach_ft"), 0.0),
        "expected_distance_band_improvement": band_improvement,
        "final_classification": final_class,
        "confidence": confidence,
        "patch_priority": patch_priority(final_class, confidence, band_improvement, safe_float(cand.get("candidate_additional_reach_ft"), 0.0)),
        "evidence_summary": "|".join(evidence),
    }


def expected_stop_reason(projected_reach: float, boundary: bool) -> str:
    if projected_reach >= MAX_REACH_FT - 1.0:
        return "reached_2500_ft"
    if boundary:
        return "stopped_at_supported_signal_boundary"
    return "stopped_at_source_extent_after_valid_continuation"


def expected_band_improvement(current: float, projected: float) -> str:
    bands = [250, 500, 1000, 1500, 2000, 2500]
    gained = [b for b in bands if current < b <= projected + 1.0]
    return "|".join(str(b) for b in gained) if gained else ""


def patch_priority(final_class: str, confidence: str, bands: str, added: float) -> str:
    if final_class not in {"simple_context_transition_continuation_likely_valid", "configuration_transition_valid_but_needs_patch"}:
        return ""
    if confidence == "high" and ("2500" in bands or added >= 1000):
        return "high"
    if confidence == "high":
        return "medium"
    return "review"


def build_audit(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    corridors = frames["corridors"]
    roads = prepare_roads(frames["roads"])
    roads_by_route = road_groups(roads)
    boundaries = make_boundary_groups(frames["attachments"])
    chains = chain_summary(corridors)
    source = chains[chains["chain_stop_reason"].eq("stopped_at_source_extent")].copy()
    eval_rows: list[dict[str, Any]] = []
    chain_rows: list[dict[str, Any]] = []
    for i, (_, row) in enumerate(source.sort_values("logical_corridor_chain_id").iterrows(), start=1):
        if i % 500 == 0:
            log(f"Audited {i:,} source-extent chains.")
        route = one_value(row.get("source_route_name_values"))
        candidates = candidate_search(roads_by_route.get(route, pd.DataFrame()), row)
        if candidates.empty:
            chain_rows.append(chain_classification_row(row, "true_source_extent_no_candidate", "", "", 0.0, 0.0, "high", "no same-route continuation candidate within search window"))
            continue
        candidate_evals = [
            classify_candidate(row, cand, corridors, frames["dedup_suppressed"], boundaries)
            for _, cand in candidates.iterrows()
        ]
        eval_rows.extend(candidate_evals)
        best = choose_best_candidate(candidate_evals)
        chain_rows.append(
            chain_classification_row(
                row,
                best["final_classification"],
                best["candidate_stable_travelway_id"],
                best["evidence_summary"],
                best["expected_added_reach_ft"],
                best["projected_reach_ft_if_continued"],
                best["confidence"],
                best["expected_distance_band_improvement"],
            )
        )
    return chains, pd.DataFrame(eval_rows), pd.DataFrame(chain_rows)


def choose_best_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    priority = {
        "configuration_transition_valid_but_needs_patch": 1,
        "simple_context_transition_continuation_likely_valid": 2,
        "divided_undivided_transition_branch_aware_review": 3,
        "insufficient_evidence_needs_review": 4,
        "carriageway_or_parallel_road_ambiguity_stop_valid": 5,
        "continuation_would_create_bin_duplication": 6,
        "duplicate_or_suppressed_candidate_stop_valid": 7,
        "supported_signal_boundary_blocks_continuation": 8,
        "candidate_exceeds_2500_ft": 9,
        "route_or_measure_identity_conflict_stop_valid": 10,
        "geometry_continuity_conflict_stop_valid": 11,
    }
    return sorted(rows, key=lambda r: (priority.get(r["final_classification"], 99), safe_float(r.get("gap_or_overlap_distance_ft"), 999), -safe_float(r.get("expected_added_reach_ft"), 0)))[0]


def chain_classification_row(row: pd.Series, final_class: str, candidate_id: str, evidence: str, added: float, projected: float, confidence: str, band_improvement: str) -> dict[str, Any]:
    return {
        "logical_corridor_chain_id": clean(row.get("logical_corridor_chain_id")),
        "stable_signal_id": clean(row.get("stable_signal_id")),
        "signal_approach_id": clean(row.get("signal_approach_id")),
        "chain_stop_reason": clean(row.get("chain_stop_reason")),
        "chain_total_reach_ft": safe_float(row.get("chain_total_reach_ft"), 0.0),
        "measure_side_class": clean(row.get("measure_side_class")),
        "route_base_values": clean(row.get("route_base_values")),
        "source_route_name_values": clean(row.get("source_route_name_values")),
        "carriageway_token_values": clean(row.get("carriageway_token_values")),
        "roadway_configuration_values": clean(row.get("roadway_configuration_values")),
        "best_candidate_stable_travelway_id": candidate_id,
        "best_candidate_expected_added_reach_ft": added,
        "best_candidate_projected_reach_ft": projected,
        "expected_distance_band_improvement": band_improvement,
        "final_classification": final_class,
        "confidence": confidence,
        "evidence_summary": evidence,
    }


def source_extent_universe_summary(chains: pd.DataFrame, chain_class: pd.DataFrame, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    source = chain_class.copy()
    prev = frames["config_classification"]
    prior_ids = set(prev.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str)) if not prev.empty else set()
    all_chains = chains.drop_duplicates("logical_corridor_chain_id")
    source_ids = set(source["logical_corridor_chain_id"].astype(str))
    rows = [
        {"metric": "total_logical_chains", "value": int(all_chains["logical_corridor_chain_id"].nunique()), "detail": ""},
        {"metric": "stopped_at_source_extent_chains", "value": int(len(source_ids)), "detail": ""},
        {"metric": "unique_approaches_affected", "value": int(source["signal_approach_id"].nunique()), "detail": ""},
        {"metric": "unique_signals_affected", "value": int(source["stable_signal_id"].nunique()), "detail": ""},
        {"metric": "source_extent_chains_already_audited_in_prior_subset", "value": int(len(source_ids & prior_ids)), "detail": ""},
        {"metric": "source_extent_chains_not_previously_audited", "value": int(len(source_ids - prior_ids)), "detail": ""},
    ]
    flag_counts = all_chains[all_chains["logical_corridor_chain_id"].isin(source_ids)]["chain_bin_eligible_flag"].fillna("").astype(str).value_counts().sort_index()
    for flag, count in flag_counts.items():
        rows.append({"metric": f"chain_bin_eligible_flag_{flag}", "value": int(count), "detail": ""})
    return pd.DataFrame(rows)


def split_ledgers(chain_class: pd.DataFrame, candidates: pd.DataFrame) -> dict[str, pd.DataFrame]:
    likely_classes = {"simple_context_transition_continuation_likely_valid", "configuration_transition_valid_but_needs_patch"}
    medium_classes = {"divided_undivided_transition_branch_aware_review", "insufficient_evidence_needs_review"}
    dup_classes = {"continuation_would_create_bin_duplication", "duplicate_or_suppressed_candidate_stop_valid"}
    ambiguity_classes = {"carriageway_or_parallel_road_ambiguity_stop_valid", "divided_undivided_transition_branch_aware_review", "insufficient_evidence_needs_review"}
    likely = candidates[candidates["final_classification"].isin(likely_classes)].copy()
    medium = candidates[candidates["final_classification"].isin(medium_classes)].copy()
    dup = candidates[candidates["final_classification"].isin(dup_classes)].copy()
    ambiguity = candidates[candidates["final_classification"].isin(ambiguity_classes)].copy()
    true_source = chain_class[chain_class["final_classification"].eq("true_source_extent_no_candidate")].copy()
    return {
        "likely_valid_source_extent_continuation_targets.csv": likely.sort_values(["patch_priority", "expected_added_reach_ft"], ascending=[True, False]),
        "medium_confidence_transition_targets.csv": medium.sort_values(["expected_added_reach_ft"], ascending=False),
        "duplicate_or_bin_overlap_exclusions.csv": dup.sort_values(["expected_added_reach_ft"], ascending=False),
        "branch_ambiguity_or_map_review_candidates.csv": ambiguity.sort_values(["expected_added_reach_ft"], ascending=False),
        "true_source_extent_chains.csv": true_source,
    }


def impact_estimate(chain_class: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    likely = candidates[candidates["final_classification"].isin(["simple_context_transition_continuation_likely_valid", "configuration_transition_valid_but_needs_patch"])].copy()
    dup = candidates[candidates["final_classification"].isin(["continuation_would_create_bin_duplication", "duplicate_or_suppressed_candidate_stop_valid"])].copy()
    ambiguity = candidates[candidates["final_classification"].isin(["carriageway_or_parallel_road_ambiguity_stop_valid", "divided_undivided_transition_branch_aware_review", "insufficient_evidence_needs_review"])].copy()
    true_branch = candidates[candidates["final_classification"].isin(["route_or_measure_identity_conflict_stop_valid", "geometry_continuity_conflict_stop_valid", "supported_signal_boundary_blocks_continuation", "candidate_exceeds_2500_ft"])].copy()
    rows = [
        {"metric": "likely_valid_continuation_candidate_rows", "value": int(len(likely)), "interpretation": ""},
        {"metric": "likely_valid_affected_chains", "value": int(likely["logical_corridor_chain_id"].nunique()), "interpretation": ""},
        {"metric": "likely_valid_affected_approaches", "value": int(likely["signal_approach_id"].nunique()), "interpretation": ""},
        {"metric": "likely_valid_affected_signals", "value": int(likely["stable_signal_id"].nunique()), "interpretation": ""},
        {"metric": "added_reach_upper_bound_ft", "value": float(likely["expected_added_reach_ft"].sum()) if not likely.empty else 0.0, "interpretation": ""},
        {"metric": "chains_improve_to_full_0_2500_support", "value": int(likely["would_reach_full_2500ft_support"].sum()) if not likely.empty else 0, "interpretation": ""},
        {"metric": "chains_improve_one_or_more_distance_bands", "value": int(likely["expected_distance_band_improvement"].fillna("").astype(str).ne("").sum()) if not likely.empty else 0, "interpretation": ""},
        {"metric": "duplicate_or_bin_overlap_invalid_chains", "value": int(dup["logical_corridor_chain_id"].nunique()), "interpretation": ""},
        {"metric": "true_branch_or_measure_conflict_invalid_chains", "value": int(true_branch["logical_corridor_chain_id"].nunique()), "interpretation": ""},
        {"metric": "ambiguous_or_map_review_chains", "value": int(ambiguity["logical_corridor_chain_id"].nunique()), "interpretation": ""},
        {"metric": "material_for_bin_context", "value": "yes" if int(likely["logical_corridor_chain_id"].nunique()) > 100 else "limited", "interpretation": ""},
    ]
    return pd.DataFrame(rows)


def prior_comparison(frames: dict[str, pd.DataFrame], candidates: pd.DataFrame) -> pd.DataFrame:
    prior = frames["config_classification"]
    prior_ids = set(prior.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str)) if not prior.empty else set()
    prior_likely_ids = set(
        prior[prior["final_classification"].eq("simple_context_transition_continuation_likely_valid")]["logical_corridor_chain_id"].astype(str)
    ) if not prior.empty and "final_classification" in prior.columns else set()
    likely = candidates[candidates["final_classification"].isin(["simple_context_transition_continuation_likely_valid", "configuration_transition_valid_but_needs_patch"])]
    likely_ids = set(likely["logical_corridor_chain_id"].astype(str))
    rows = [
        {"metric": "prior_subset_count", "value": len(prior_ids), "detail": "roadway_configuration_conflict_continuation_audit rows"},
        {"metric": "full_audit_source_extent_count", "value": int(frames["corridors"].drop_duplicates("logical_corridor_chain_id")["chain_stop_reason"].eq("stopped_at_source_extent").sum()), "detail": ""},
        {"metric": "likely_valid_continuations_already_in_prior_subset", "value": len(likely_ids & prior_ids), "detail": ""},
        {"metric": "newly_discovered_likely_valid_outside_prior_subset", "value": len(likely_ids - prior_ids), "detail": ""},
        {"metric": "prior_likely_valid_count", "value": len(prior_likely_ids), "detail": ""},
        {"metric": "prior_suspect_screen_incomplete", "value": len(likely_ids - prior_ids) > 0, "detail": ""},
        {"metric": "full_audit_changes_patch_scope", "value": len(likely_ids - prior_ids) > 0, "detail": "Patch target count same as prior likely-valid subset if false."},
    ]
    return pd.DataFrame(rows)


def priority_summary(targets: pd.DataFrame) -> pd.DataFrame:
    if targets.empty:
        return pd.DataFrame(columns=["patch_priority", "target_rows", "chains", "added_reach_ft"])
    return targets.groupby("patch_priority", dropna=False).agg(
        target_rows=("logical_corridor_chain_id", "size"),
        chains=("logical_corridor_chain_id", "nunique"),
        added_reach_ft=("expected_added_reach_ft", "sum"),
    ).reset_index()


def decision(chain_class: pd.DataFrame, candidates: pd.DataFrame) -> str:
    likely = candidates[candidates["final_classification"].isin(["simple_context_transition_continuation_likely_valid", "configuration_transition_valid_but_needs_patch"])]
    medium = candidates[candidates["final_classification"].isin(["divided_undivided_transition_branch_aware_review", "insufficient_evidence_needs_review"])]
    if likely["logical_corridor_chain_id"].nunique() > 100:
        return "patch_likely_valid_source_extent_continuations_before_bin_context"
    if likely["logical_corridor_chain_id"].nunique() > 0 and medium["logical_corridor_chain_id"].nunique() > 0:
        return "patch_high_confidence_only_and_review_medium_confidence"
    if medium["logical_corridor_chain_id"].nunique() > 0:
        return "create_source_extent_transition_map_review_sample"
    if chain_class["final_classification"].eq("insufficient_evidence_needs_review").any():
        return "evidence_insufficient_needs_more_audit"
    return "source_extent_stops_are_valid_finalize_corridors"


def write_text_outputs(frames: dict[str, pd.DataFrame], chain_class: pd.DataFrame, candidates: pd.DataFrame, impact: pd.DataFrame, prior: pd.DataFrame, final_decision: str) -> None:
    counts = chain_class["final_classification"].value_counts().sort_index()
    candidate_counts = candidates["final_classification"].value_counts().sort_index() if not candidates.empty else pd.Series(dtype=int)
    true_source = int(counts.get("true_source_extent_no_candidate", 0))
    likely = int(candidates[candidates["final_classification"].isin(["simple_context_transition_continuation_likely_valid", "configuration_transition_valid_but_needs_patch"])]["logical_corridor_chain_id"].nunique()) if not candidates.empty else 0
    new_likely = int(prior.loc[prior["metric"].eq("newly_discovered_likely_valid_outside_prior_subset"), "value"].iloc[0])
    dup = int(candidates[candidates["final_classification"].isin(["continuation_would_create_bin_duplication", "duplicate_or_suppressed_candidate_stop_valid"])]["logical_corridor_chain_id"].nunique()) if not candidates.empty else 0
    ambiguity = int(candidates[candidates["final_classification"].isin(["carriageway_or_parallel_road_ambiguity_stop_valid", "divided_undivided_transition_branch_aware_review", "insufficient_evidence_needs_review"])]["logical_corridor_chain_id"].nunique()) if not candidates.empty else 0
    material = impact.loc[impact["metric"].eq("material_for_bin_context"), "value"].iloc[0]
    findings = f"""# Full Source-Extent Continuation Audit

## Why This Full Audit Was Needed
The prior roadway-configuration conflict audit found 1,777 likely-valid continuations inside a previously suspect subset. That was material enough to audit every current `stopped_at_source_extent` chain before any bin_context build.

## Why Roadway Configuration Alone Must Not Block Continuation
`roadway_configuration` can change because median, divided/undivided, access, facility, or lane context changes along the same physical route-space branch. It should block continuation only when the change indicates a different route, carriageway, ramp, branch, supported signal boundary, or duplicate/bin-overlap risk.

## Full Source-Extent Results
Chain-level classification:
{counts.to_string()}

Candidate-level classification:
{candidate_counts.to_string()}

True source extent/no candidate chains: {true_source:,}. Likely valid same-corridor continuations: {likely:,}. Newly discovered likely-valid continuations outside the prior 1,979 subset: {new_likely:,}. Duplicate/bin-overlap exclusions: {dup:,}. Branch/carriageway/parallel ambiguity cases: {ambiguity:,}.

## bin_context Readiness
This materially affects bin_context readiness: `{material}`. A patch is needed before bin_context because likely-valid continuation targets can add source-extent reach and improve distance-band support.

## Map Review
Map review is not needed for high-confidence likely-valid same-route, same-token, zero/small-gap targets. Review should be limited to branch/carriageway/ramp/parallel ambiguity or medium-confidence transition cases.

## Recommended Next Task
Patch likely-valid source-extent continuations before bin_context, then rerun a final read-only corridor validation. Do not include duplicate/bin-overlap or ambiguity cases in automatic patching.

## Final Decision
`{final_decision}`
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_utc": now(),
        "script": "src.roadway_graph.audit.full_source_extent_continuation_audit",
        "rule_version": RULE_VERSION,
        "bounded_question": "Audit all stopped_at_source_extent chains for valid same-corridor continuation candidates.",
        "source_inputs": [rel(p) for p in [SIGNAL_INDEX, TRAVELWAY_INDEX, ATTACHMENT, APPROACHES, CORRIDORS, STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]],
        "diagnostic_inputs": [rel(p) for p in [CONFIG_AUDIT, SOURCE_RECON, FINAL_REVIEW, REPAIR_REVIEW, DEDUP_REVIEW, RECON_REVIEW]],
        "output_grain": {
            "source_extent_chain_classification.csv": "one row per current stopped_at_source_extent logical chain",
            "source_extent_continuation_candidate_evaluations.csv": "one row per searched continuation candidate",
        },
        "caveats": [
            "No staged products were modified.",
            "Continuation candidates are searched within a 50-ft route-measure window on the same source route.",
            "Geometry continuity is endpoint-distance evidence only; no map layer was generated.",
        ],
        "final_decision": final_decision,
    }
    qa = {
        "created_utc": now(),
        "source_extent_chain_rows": int(len(chain_class)),
        "candidate_evaluation_rows": int(len(candidates)),
        "chain_classification_counts": {str(k): int(v) for k, v in counts.items()},
        "candidate_classification_counts": {str(k): int(v) for k, v in candidate_counts.items()},
        "final_decision": final_decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()}: Started full source-extent continuation audit.\n", encoding="utf-8")
    frames = load_inputs()
    chains, candidates, chain_class = build_audit(frames)
    universe = source_extent_universe_summary(chains, chain_class, frames)
    ledgers = split_ledgers(chain_class, candidates)
    impact = impact_estimate(chain_class, candidates)
    prior = prior_comparison(frames, candidates)
    final_decision = decision(chain_class, candidates)
    targets = ledgers["likely_valid_source_extent_continuation_targets.csv"]
    priority = priority_summary(targets)
    decision_summary = pd.DataFrame(
        [
            {"metric": "final_decision", "value": final_decision},
            {"metric": "source_extent_chain_rows", "value": len(chain_class)},
            {"metric": "candidate_evaluation_rows", "value": len(candidates)},
            {"metric": "chain_classification_mix", "value": "|".join(f"{k}:{int(v)}" for k, v in chain_class["final_classification"].value_counts().sort_index().items())},
            {"metric": "candidate_classification_mix", "value": "|".join(f"{k}:{int(v)}" for k, v in candidates["final_classification"].value_counts().sort_index().items()) if not candidates.empty else ""},
        ]
    )
    readiness = pd.DataFrame([{"final_decision": final_decision, "reason": "read-only full source-extent continuation audit completed"}])
    recommended = pd.DataFrame(
        [
            {
                "rank": 1,
                "action": "patch_likely_valid_source_extent_continuations_before_bin_context",
                "rationale": "Likely-valid same-corridor continuations materially affect distance-band support.",
            },
            {
                "rank": 2,
                "action": "rerun_final_read_only_approach_corridors_validation",
                "rationale": "Validate row counts, stop reasons, source-extent status, duplicate risk, and bin readiness after any patch.",
            },
            {
                "rank": 3,
                "action": "review_branch_ambiguity_subset_only",
                "rationale": "Do not automatically continue one-way/ramp/parallel or duplicate/bin-overlap cases.",
            },
        ]
    )
    write_csv("source_extent_universe_summary.csv", universe)
    write_csv("source_extent_continuation_candidate_evaluations.csv", candidates)
    write_csv("source_extent_chain_classification.csv", chain_class)
    for name, df in ledgers.items():
        write_csv(name, df)
    write_csv("prior_subset_vs_full_audit_comparison.csv", prior)
    write_csv("distance_band_impact_estimate.csv", impact)
    write_csv("patch_target_priority_summary.csv", priority)
    write_csv("source_extent_decision_summary.csv", decision_summary)
    write_csv("readiness_decision.csv", readiness)
    write_csv("recommended_next_actions.csv", recommended)
    write_text_outputs(frames, chain_class, candidates, impact, prior, final_decision)
    log(f"Finished full source-extent continuation audit with decision={final_decision}.")


if __name__ == "__main__":
    main()
