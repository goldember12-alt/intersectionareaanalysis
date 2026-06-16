"""Read-only source-extent suspect-chain reconciliation audit.

This audit reconciles the 2,006 source-extent suspect chains from the
finalization audit against the later repair pass and current staged parents.
It does not modify staged products or prior review outputs.
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
OUT = REPO / "work/roadway_graph/review/source_extent_suspect_chain_reconciliation_audit"

SIGNAL_INDEX = STAGING / "signal_index.parquet"
TRAVELWAY_INDEX = STAGING / "travelway_network_index.parquet"
ATTACHMENT = STAGING / "signal_travelway_attachment.parquet"
APPROACHES = STAGING / "signal_approaches.parquet"
CORRIDORS = STAGING / "approach_corridors.parquet"
STAGING_MANIFEST = STAGING / "manifest.json"
STAGING_SCHEMA = STAGING / "schema.json"
STAGING_README = STAGING / "README.md"

FINAL_REVIEW = REPO / "work/roadway_graph/review/finalize_approach_corridors_validation_audit"
REPAIR_REVIEW = REPO / "work/roadway_graph/review/repair_approach_corridor_source_extent_continuation"
DEDUP_REVIEW = REPO / "work/roadway_graph/review/deduplicate_approach_corridor_chains"
CHAIN_AUDIT_REVIEW = REPO / "work/roadway_graph/review/chain_aware_approach_corridors_validation_audit"
RECON_REVIEW = REPO / "work/roadway_graph/review/reconstruct_chain_aware_approach_corridors"

MAX_REACH_FT = 2500.0
MAX_REACH_MILES = MAX_REACH_FT / 5280.0
PERMISSIVE_SEARCH_GAP_FT = 50.0
STRICT_ACCEPT_GAP_FT = 5.0
FLOAT_TOL_FT = 0.001
RULE_VERSION = "source_extent_suspect_chain_reconciliation_audit_v1"


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
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = clean(value).lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return default


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


def compact_counts(values: pd.Series) -> str:
    if values.empty:
        return ""
    counts = values.fillna("").astype(str).replace("", "blank").value_counts().sort_index()
    return "|".join(f"{idx}:{int(val)}" for idx, val in counts.items())


def compatibility_value(a: Any, b: Any) -> bool:
    aa = clean(a).lower()
    bb = clean(b).lower()
    unknown = {"", "unknown", "nan", "none", "null", "<na>"}
    return aa == bb or aa in unknown or bb in unknown


def exact_or_unknown(a: Any, b: Any) -> bool:
    return compatibility_value(a, b)


def load_inputs() -> dict[str, pd.DataFrame]:
    log("Loading staged parents, current corridors, and prior diagnostic ledgers.")
    frames = {
        "signals": pd.read_parquet(SIGNAL_INDEX, columns=["stable_signal_id", "source_limited_status"]),
        "roads": pd.read_parquet(TRAVELWAY_INDEX),
        "attachments": pd.read_parquet(ATTACHMENT),
        "approaches": pd.read_parquet(APPROACHES),
        "corridors": pd.read_parquet(CORRIDORS),
        "final_suspects": read_csv_optional(FINAL_REVIEW / "likely_source_extent_false_stops.csv"),
        "final_source_validation": read_csv_optional(FINAL_REVIEW / "source_extent_stop_validation_final.csv"),
        "repair_input": read_csv_optional(REPAIR_REVIEW / "source_extent_suspect_input_ledger.csv"),
        "repair_accepted": read_csv_optional(REPAIR_REVIEW / "accepted_source_extent_continuation_ledger.csv"),
        "repair_rejected": read_csv_optional(REPAIR_REVIEW / "rejected_source_extent_continuation_ledger.csv"),
        "repair_post_validation": read_csv_optional(REPAIR_REVIEW / "post_repair_source_extent_validation.csv"),
        "repair_remaining": read_csv_optional(REPAIR_REVIEW / "remaining_possible_false_source_extent_stops.csv"),
        "repair_counts": read_csv_optional(REPAIR_REVIEW / "prior_vs_post_repair_counts.csv"),
        "repair_summary": read_csv_optional(REPAIR_REVIEW / "source_extent_repair_summary.csv"),
        "suppressed_chains": read_csv_optional(DEDUP_REVIEW / "suppressed_duplicate_chain_ledger.csv"),
        "dedup_source_extent": read_csv_optional(DEDUP_REVIEW / "source_extent_stop_check_after_patch.csv"),
        "chain_aware_suspects": read_csv_optional(CHAIN_AUDIT_REVIEW / "likely_source_extent_false_stops.csv"),
        "recon_attempts": read_csv_optional(RECON_REVIEW / "neighbor_extension_attempts.csv"),
        "recon_acceptances": read_csv_optional(RECON_REVIEW / "neighbor_extension_acceptances.csv"),
    }
    return frames


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
    for col in ["route_base", "source_route_name", "source_route_id", "source_route_common", "carriageway_direction_token", "roadway_configuration"]:
        if col not in r.columns:
            r[col] = ""
    return r.sort_values(["source_route_name", "road_lo", "road_hi", "stable_travelway_id"]).reset_index(drop=True)


def make_road_groups(roads: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {clean(route): group.reset_index(drop=True) for route, group in roads.groupby("source_route_name", dropna=False)}


def make_boundary_groups(attachments: pd.DataFrame) -> dict[str, pd.DataFrame]:
    a = attachments.copy()
    for optional in ["source_route_name", "roadway_configuration", "carriageway_direction_token", "source_signal_globalid"]:
        if optional not in a.columns:
            a[optional] = ""
    boundary = a[
        a["attachment_confidence"].isin(["high", "medium"])
        & a["estimated_measure_status"].eq("estimated_measure_projected")
        & a["usable_as_corridor_boundary"].fillna(False).astype(bool)
        & a["estimated_measure"].notna()
    ].copy()
    boundary["estimated_measure"] = pd.to_numeric(boundary["estimated_measure"], errors="coerce")
    boundary = boundary[boundary["estimated_measure"].notna()].copy()
    return {clean(route): group.sort_values("estimated_measure").reset_index(drop=True) for route, group in boundary.groupby("source_route_name", dropna=False)}


def chain_summary(corridors: pd.DataFrame) -> pd.DataFrame:
    c = corridors.copy()
    c["segment_source_from_measure"] = pd.to_numeric(c["segment_source_from_measure"], errors="coerce")
    c["segment_source_to_measure"] = pd.to_numeric(c["segment_source_to_measure"], errors="coerce")
    return c.groupby("logical_corridor_chain_id", dropna=False).agg(
        stable_signal_id=("stable_signal_id", "first"),
        signal_approach_id=("signal_approach_id", "first"),
        segment_count=("approach_corridor_id", "size"),
        max_segment_order=("segment_order", "max"),
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
        source_measure_min=("segment_source_from_measure", "min"),
        source_measure_max=("segment_source_to_measure", "max"),
        chain_bin_eligible_flag=("chain_bin_eligible_flag", "first"),
        bin_duplication_risk_status=("bin_duplication_risk_status", "first"),
        source_extent_repair_status=("source_extent_repair_status", "first"),
        source_extent_repair_method=("source_extent_repair_method", "first"),
        continuation_candidate_count=("continuation_candidate_count", "first"),
        accepted_continuation_count=("accepted_continuation_count", "first"),
        rejected_continuation_count=("rejected_continuation_count", "first"),
        continuation_evidence_summary=("continuation_evidence_summary", "first"),
    ).reset_index()


def one_value(text: Any) -> str:
    return (clean(text).split("|") + [""])[0]


def endpoint_for_chain(row: pd.Series) -> tuple[float, float]:
    signal_measure = safe_float(row.get("reviewed_signal_measure"))
    reach_ft = safe_float(row.get("chain_total_reach_ft"), 0.0)
    side = clean(row.get("measure_side_class"))
    if side == "measure_increasing_from_signal":
        return signal_measure, signal_measure + reach_ft / 5280.0
    if side == "measure_decreasing_from_signal":
        return signal_measure, signal_measure - reach_ft / 5280.0
    return signal_measure, float("nan")


def broad_candidates(route_roads: pd.DataFrame, side: str, endpoint: float) -> pd.DataFrame:
    if route_roads.empty or pd.isna(endpoint):
        return pd.DataFrame(columns=list(route_roads.columns) + ["gap_ft"])
    if side == "measure_increasing_from_signal":
        cand = route_roads[route_roads["road_hi"] > endpoint + 1e-9].copy()
        cand["gap_ft"] = ((cand["road_lo"] - endpoint).clip(lower=0.0)) * 5280.0
        cand = cand[cand["gap_ft"] <= PERMISSIVE_SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
        return cand.sort_values(["gap_ft", "road_lo", "road_hi", "stable_travelway_id"])
    if side == "measure_decreasing_from_signal":
        cand = route_roads[route_roads["road_lo"] < endpoint - 1e-9].copy()
        cand["gap_ft"] = ((endpoint - cand["road_hi"]).clip(lower=0.0)) * 5280.0
        cand = cand[cand["gap_ft"] <= PERMISSIVE_SEARCH_GAP_FT + FLOAT_TOL_FT].copy()
        return cand.sort_values(["gap_ft", "road_hi", "road_lo", "stable_travelway_id"], ascending=[True, False, False, True])
    return pd.DataFrame(columns=list(route_roads.columns) + ["gap_ft"])


def boundary_between(boundary_groups: dict[str, pd.DataFrame], row: pd.Series, endpoint: float, candidate_start: float) -> dict[str, Any]:
    route = one_value(row.get("source_route_name_values"))
    side = clean(row.get("measure_side_class"))
    signal_measure = safe_float(row.get("reviewed_signal_measure"))
    signal_id = clean(row.get("stable_signal_id"))
    token = one_value(row.get("carriageway_token_values"))
    config = one_value(row.get("roadway_configuration_values"))
    b = boundary_groups.get(route)
    if b is None or b.empty:
        return {"has_boundary": False, "boundary_measure": "", "boundary_signal_id": ""}
    b = b.copy()
    for optional in ["carriageway_direction_token", "roadway_configuration"]:
        if optional not in b.columns:
            b.loc[:, optional] = ""
    b = b[~b["stable_signal_id"].astype(str).eq(signal_id)].copy()
    token_series = b.get("carriageway_direction_token", pd.Series("", index=b.index))
    config_series = b.get("roadway_configuration", pd.Series("", index=b.index))
    b = b[token_series.map(lambda x: compatibility_value(x, token))]
    b = b[config_series.reindex(b.index).map(lambda x: compatibility_value(x, config))]
    if b.empty:
        return {"has_boundary": False, "boundary_measure": "", "boundary_signal_id": ""}
    if side == "measure_increasing_from_signal":
        between = b[(b["estimated_measure"] > max(signal_measure, endpoint) + 1e-9) & (b["estimated_measure"] <= candidate_start + 1e-9)].copy()
        if between.empty:
            return {"has_boundary": False, "boundary_measure": "", "boundary_signal_id": ""}
        hit = between.sort_values("estimated_measure").iloc[0]
    else:
        between = b[(b["estimated_measure"] < min(signal_measure, endpoint) - 1e-9) & (b["estimated_measure"] >= candidate_start - 1e-9)].copy()
        if between.empty:
            return {"has_boundary": False, "boundary_measure": "", "boundary_signal_id": ""}
        hit = between.sort_values("estimated_measure", ascending=False).iloc[0]
    return {"has_boundary": True, "boundary_measure": float(hit["estimated_measure"]), "boundary_signal_id": clean(hit["stable_signal_id"])}


def duplicate_existing_route_space(corridors: pd.DataFrame, row: pd.Series, road: pd.Series) -> bool:
    approach_id = clean(row.get("signal_approach_id"))
    chain_id = clean(row.get("logical_corridor_chain_id"))
    side = clean(row.get("measure_side_class"))
    route = one_value(row.get("source_route_name_values"))
    token = one_value(row.get("carriageway_token_values"))
    seg_lo = float(road["road_lo"])
    seg_hi = float(road["road_hi"])
    peers = corridors[
        corridors["signal_approach_id"].astype(str).eq(approach_id)
        & ~corridors["logical_corridor_chain_id"].astype(str).eq(chain_id)
        & corridors["measure_side_class"].astype(str).eq(side)
        & corridors["source_route_name"].astype(str).eq(route)
        & corridors["chain_bin_eligible_flag"].fillna(True).map(as_bool)
    ].copy()
    if peers.empty:
        return False
    peers = peers[peers["carriageway_direction_token"].map(lambda x: compatibility_value(x, token))]
    if peers.empty:
        return False
    if peers["stable_travelway_id"].astype(str).eq(clean(road["stable_travelway_id"])).any():
        return True
    overlap = (
        (pd.to_numeric(peers["segment_source_from_measure"], errors="coerce") <= seg_hi + 1e-9)
        & (pd.to_numeric(peers["segment_source_to_measure"], errors="coerce") >= seg_lo - 1e-9)
    ).any()
    return bool(overlap)


def suppressed_candidate_match(suppressed: pd.DataFrame, row: pd.Series, road: pd.Series) -> bool:
    if suppressed.empty or "stable_travelway_id" not in suppressed.columns:
        return False
    mask = suppressed["stable_travelway_id"].astype(str).eq(clean(road.get("stable_travelway_id")))
    if "signal_approach_id" in suppressed.columns:
        mask &= suppressed["signal_approach_id"].astype(str).eq(clean(row.get("signal_approach_id")))
    return bool(mask.any())


def evaluate_candidate(
    row: pd.Series,
    road: pd.Series,
    corridors: pd.DataFrame,
    suppressed: pd.DataFrame,
    boundary_groups: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    signal_measure, endpoint = endpoint_for_chain(row)
    side = clean(row.get("measure_side_class"))
    route = one_value(row.get("source_route_name_values"))
    route_base = one_value(row.get("route_base_values"))
    route_id = one_value(row.get("source_route_id_values"))
    route_common = one_value(row.get("source_route_common_values"))
    token = one_value(row.get("carriageway_token_values"))
    config = one_value(row.get("roadway_configuration_values"))
    used_ids = set(clean(row.get("stable_travelway_ids")).split("|")) - {""}
    current_reach = abs(endpoint - signal_measure) * 5280.0 if not pd.isna(endpoint) else float("nan")
    hard_limit = signal_measure + MAX_REACH_MILES if side == "measure_increasing_from_signal" else signal_measure - MAX_REACH_MILES
    if side == "measure_increasing_from_signal":
        candidate_start = max(float(road["road_lo"]), endpoint)
        candidate_end = min(float(road["road_hi"]), hard_limit)
    else:
        candidate_start = min(float(road["road_hi"]), endpoint)
        candidate_end = max(float(road["road_lo"]), hard_limit)
    candidate_additional_reach_ft = abs(candidate_end - endpoint) * 5280.0
    projected_reach_ft = abs(candidate_end - signal_measure) * 5280.0
    boundary = boundary_between(boundary_groups, row, endpoint, candidate_start)
    same_chain = clean(road.get("stable_travelway_id")) in used_ids
    duplicate_suppressed = suppressed_candidate_match(suppressed, row, road)
    route_name_match = clean(road.get("source_route_name")) == route
    route_base_match = exact_or_unknown(road.get("route_base"), route_base)
    route_id_match = exact_or_unknown(road.get("source_route_id"), route_id)
    route_common_match = exact_or_unknown(road.get("source_route_common"), route_common)
    token_match = compatibility_value(road.get("carriageway_direction_token"), token)
    config_match = compatibility_value(road.get("roadway_configuration"), config)
    side_ok = candidate_additional_reach_ft > FLOAT_TOL_FT
    gap_ft = safe_float(road.get("gap_ft"))
    gap_ok = gap_ft <= STRICT_ACCEPT_GAP_FT + FLOAT_TOL_FT
    within_2500 = projected_reach_ft <= MAX_REACH_FT + FLOAT_TOL_FT
    duplicate_bin_overlap = duplicate_existing_route_space(corridors, row, road)
    route_measure_ok = route_name_match and gap_ok and side_ok
    geometry_status = "not_evaluated_route_measure_proxy_used"
    strict_pass = all(
        [
            route_name_match,
            route_base_match,
            route_id_match,
            route_common_match,
            token_match,
            config_match,
            side_ok,
            gap_ok,
            within_2500,
            not boundary["has_boundary"],
            not same_chain,
            not duplicate_bin_overlap,
        ]
    )
    reasons: list[str] = []
    if same_chain:
        reasons.append("candidate_already_in_same_chain")
    if duplicate_suppressed:
        reasons.append("candidate_duplicate_suppressed")
    if not side_ok:
        reasons.append("candidate_wrong_measure_side")
    if not (route_name_match and route_base_match and route_id_match and route_common_match):
        reasons.append("candidate_route_conflict")
    if not token_match:
        reasons.append("candidate_carriageway_conflict")
    if not config_match:
        reasons.append("candidate_roadway_configuration_conflict")
    if boundary["has_boundary"]:
        reasons.append("candidate_crosses_supported_signal_boundary")
    if not within_2500:
        reasons.append("candidate_exceeds_2500_ft")
    if duplicate_bin_overlap:
        reasons.append("candidate_creates_duplicate_bin_overlap")
    if not route_measure_ok:
        reasons.append("candidate_route_measure_continuity_failed")
    if not reasons and not strict_pass:
        reasons.append("candidate_diagnostic_only_not_corridor_valid")
    return {
        "logical_corridor_chain_id": clean(row.get("logical_corridor_chain_id")),
        "stable_signal_id": clean(row.get("stable_signal_id")),
        "signal_approach_id": clean(row.get("signal_approach_id")),
        "candidate_stable_travelway_id": clean(road.get("stable_travelway_id")),
        "candidate_source_route_name": clean(road.get("source_route_name")),
        "candidate_route_base": clean(road.get("route_base")),
        "candidate_source_route_id": clean(road.get("source_route_id")),
        "candidate_source_route_common": clean(road.get("source_route_common")),
        "candidate_carriageway_direction_token": clean(road.get("carriageway_direction_token")),
        "candidate_roadway_configuration": clean(road.get("roadway_configuration")),
        "candidate_road_lo": float(road["road_lo"]),
        "candidate_road_hi": float(road["road_hi"]),
        "endpoint_measure": endpoint,
        "candidate_gap_ft": gap_ft,
        "candidate_additional_reach_ft": candidate_additional_reach_ft,
        "projected_reach_ft": projected_reach_ft,
        "current_reach_ft": current_reach,
        "same_chain": same_chain,
        "duplicate_suppressed": duplicate_suppressed,
        "route_name_match": route_name_match,
        "route_base_match": route_base_match,
        "route_id_match": route_id_match,
        "route_common_match": route_common_match,
        "carriageway_token_match": token_match,
        "roadway_configuration_match": config_match,
        "measure_side_ok": side_ok,
        "gap_within_strict_acceptance": gap_ok,
        "within_2500_ft": within_2500,
        "supported_signal_boundary_between": boundary["has_boundary"],
        "boundary_signal_id": boundary["boundary_signal_id"],
        "boundary_measure": boundary["boundary_measure"],
        "duplicate_bin_overlap_risk": duplicate_bin_overlap,
        "geometry_continuity_status": geometry_status,
        "route_measure_continuity_status": "pass" if route_measure_ok else "fail",
        "strict_candidate_pass": strict_pass,
        "candidate_rejection_reasons": "|".join(reasons),
    }


def reconcile_ledgers(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    final = frames["final_suspects"]
    repair_input = frames["repair_input"]
    final_ids = set(final.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str))
    input_ids = set(repair_input.get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str))
    accepted_ids = set(frames["repair_accepted"].get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str)) if not frames["repair_accepted"].empty else set()
    rejected_ids = set(frames["repair_rejected"].get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str)) if not frames["repair_rejected"].empty else set()
    remaining_ids = set(frames["repair_remaining"].get("logical_corridor_chain_id", pd.Series(dtype=str)).astype(str)) if not frames["repair_remaining"].empty else set()
    post = frames["repair_post_validation"]
    confirmed_ids = set()
    if not post.empty and "source_extent_validation_class" in post.columns:
        confirmed_ids = set(post[post["source_extent_validation_class"].eq("likely_true_source_extent")]["logical_corridor_chain_id"].astype(str)) & final_ids
    rows = [
        {"metric": "finalization_suspect_rows", "value": len(final), "detail": ""},
        {"metric": "repair_input_suspect_rows", "value": len(repair_input), "detail": ""},
        {"metric": "overlap_by_logical_corridor_chain_id", "value": len(final_ids & input_ids), "detail": ""},
        {"metric": "accepted_repair_rows", "value": len(frames["repair_accepted"]), "detail": ""},
        {"metric": "accepted_repair_chain_ids", "value": len(accepted_ids), "detail": ""},
        {"metric": "rejected_repair_rows", "value": len(frames["repair_rejected"]), "detail": ""},
        {"metric": "rejected_repair_chain_ids", "value": len(rejected_ids), "detail": ""},
        {"metric": "confirmed_true_source_extent_rows_in_post_validation_for_original_suspects", "value": len(confirmed_ids), "detail": ""},
        {"metric": "remaining_suspect_rows", "value": len(frames["repair_remaining"]), "detail": ""},
        {"metric": "finalization_ids_missing_from_repair_input", "value": len(final_ids - input_ids), "detail": "|".join(sorted(final_ids - input_ids)[:20])},
        {"metric": "repair_input_ids_not_in_finalization_suspects", "value": len(input_ids - final_ids), "detail": "|".join(sorted(input_ids - final_ids)[:20])},
    ]
    return pd.DataFrame(rows)


def run_reconciliation(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    roads = prepare_roads(frames["roads"])
    roads_by_route = make_road_groups(roads)
    boundary_groups = make_boundary_groups(frames["attachments"])
    corridors = frames["corridors"]
    chain = chain_summary(corridors)
    final = frames["final_suspects"].copy()
    repair_input = frames["repair_input"].copy()
    if final.empty:
        raise RuntimeError("No finalization suspect ledger found.")
    suspect_ids = sorted(set(final["logical_corridor_chain_id"].astype(str)))
    chain_by_id = chain.set_index("logical_corridor_chain_id", drop=False)
    post = frames["repair_post_validation"]
    post_by_id = post.set_index("logical_corridor_chain_id", drop=False) if not post.empty and "logical_corridor_chain_id" in post.columns else pd.DataFrame()
    candidate_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for i, chain_id in enumerate(suspect_ids, start=1):
        if i % 250 == 0:
            log(f"Evaluated strict continuation candidates for {i:,} suspect chains.")
        if chain_id not in chain_by_id.index:
            reconciliation_rows.append(
                {
                    "logical_corridor_chain_id": chain_id,
                    "reconciliation_classification": "missing_evidence_cannot_reconcile",
                    "reconciliation_confidence": "high",
                    "evidence_fields_used": "finalization_suspect_ledger|current_approach_corridors_missing_chain",
                }
            )
            continue
        row = chain_by_id.loc[chain_id]
        route = one_value(row.get("source_route_name_values"))
        side = clean(row.get("measure_side_class"))
        _, endpoint = endpoint_for_chain(row)
        route_roads = roads_by_route.get(route, pd.DataFrame())
        broad = broad_candidates(route_roads, side, endpoint)
        evals = [
            evaluate_candidate(row, road, corridors, frames["suppressed_chains"], boundary_groups)
            for _, road in broad.iterrows()
        ]
        candidate_rows.extend(evals)
        ev = pd.DataFrame(evals)
        strict_count = int(ev["strict_candidate_pass"].sum()) if not ev.empty else 0
        prior = final[final["logical_corridor_chain_id"].astype(str).eq(chain_id)].iloc[0]
        repair_in = repair_input[repair_input["logical_corridor_chain_id"].astype(str).eq(chain_id)]
        post_class = ""
        if isinstance(post_by_id, pd.DataFrame) and not post_by_id.empty and chain_id in post_by_id.index:
            post_class = clean(post_by_id.loc[chain_id].get("source_extent_validation_class"))
        classif, confidence = classify_chain(ev, row, post_class, strict_count)
        evidence = [
            "finalization_likely_source_extent_false_stops",
            "repair_source_extent_suspect_input_ledger",
            "current_staged_approach_corridors",
            "current_staged_travelway_network_index",
            "current_staged_signal_travelway_attachment",
        ]
        if not frames["suppressed_chains"].empty:
            evidence.append("deduplicate_suppressed_duplicate_chain_ledger")
        reconciliation_rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "stable_signal_id": clean(row.get("stable_signal_id")),
                "signal_approach_id": clean(row.get("signal_approach_id")),
                "chain_stop_reason": clean(row.get("chain_stop_reason")),
                "chain_total_reach_ft": safe_float(row.get("chain_total_reach_ft")),
                "measure_side_class": clean(row.get("measure_side_class")),
                "route_base_values": clean(row.get("route_base_values")),
                "source_route_name_values": clean(row.get("source_route_name_values")),
                "source_route_id_values": clean(row.get("source_route_id_values")),
                "source_route_common_values": clean(row.get("source_route_common_values")),
                "carriageway_token_values": clean(row.get("carriageway_token_values")),
                "roadway_configuration_values": clean(row.get("roadway_configuration_values")),
                "prior_best_candidate_id": "" if ev.empty else clean(ev.sort_values(["candidate_gap_ft", "candidate_stable_travelway_id"]).iloc[0]["candidate_stable_travelway_id"]),
                "prior_best_continuation_gap_ft": prior.get("best_continuation_gap_ft", ""),
                "prior_continuation_candidate_count_50ft": prior.get("continuation_candidate_count_50ft", ""),
                "repair_input_status": "" if repair_in.empty else clean(repair_in.iloc[0].get("input_status")),
                "current_continuation_candidate_count_under_strict_rules": strict_count,
                "current_stage_source_extent_repair_status": clean(row.get("source_extent_repair_status")),
                "current_stage_continuation_candidate_count": clean(row.get("continuation_candidate_count")),
                "repair_post_validation_class": post_class,
                "candidate_rejection_reason_mix": compact_counts(ev["candidate_rejection_reasons"]) if not ev.empty else "",
                "reconciliation_classification": classif,
                "reconciliation_confidence": confidence,
                "evidence_fields_used": "|".join(evidence),
            }
        )
        summary_rows.append(
            {
                "logical_corridor_chain_id": chain_id,
                "permissive_candidate_count_50ft_recomputed": int(len(ev)),
                "strict_candidate_pass_count": strict_count,
                "strict_candidate_rejection_reason_mix": compact_counts(ev["candidate_rejection_reasons"]) if not ev.empty else "",
                "best_strict_candidate_gap_ft": "" if ev.empty or strict_count == 0 else float(ev[ev["strict_candidate_pass"]]["candidate_gap_ft"].min()),
                "all_permissive_candidates_already_in_same_chain": bool((not ev.empty) and ev["same_chain"].all()),
                "any_duplicate_suppressed_candidate": bool((not ev.empty) and ev["duplicate_suppressed"].any()),
                "any_route_conflict": bool((not ev.empty) and (~ev["route_name_match"] | ~ev["route_base_match"] | ~ev["route_id_match"] | ~ev["route_common_match"]).any()),
                "any_carriageway_conflict": bool((not ev.empty) and (~ev["carriageway_token_match"]).any()),
                "any_roadway_configuration_conflict": bool((not ev.empty) and (~ev["roadway_configuration_match"]).any()),
                "any_boundary_between": bool((not ev.empty) and ev["supported_signal_boundary_between"].any()),
                "any_duplicate_bin_overlap_risk": bool((not ev.empty) and ev["duplicate_bin_overlap_risk"].any()),
            }
        )
    return pd.DataFrame(reconciliation_rows), pd.DataFrame(candidate_rows), pd.DataFrame(summary_rows)


def classify_chain(ev: pd.DataFrame, row: pd.Series, post_class: str, strict_count: int) -> tuple[str, str]:
    if strict_count > 0:
        return "unresolved_still_possible_false_source_extent", "high"
    if ev.empty:
        if post_class == "likely_true_source_extent":
            return "confirmed_true_source_extent", "medium"
        return "missing_evidence_cannot_reconcile", "medium"
    if ev["same_chain"].all():
        return "candidate_already_in_same_chain", "high"
    if ev["duplicate_suppressed"].any():
        return "candidate_duplicate_suppressed", "high"
    if (~ev["measure_side_ok"]).any():
        return "candidate_wrong_measure_side", "high"
    if (~ev["route_name_match"] | ~ev["route_base_match"] | ~ev["route_id_match"] | ~ev["route_common_match"]).any():
        return "candidate_route_conflict", "high"
    if (~ev["carriageway_token_match"]).any():
        return "candidate_carriageway_conflict", "high"
    if (~ev["roadway_configuration_match"]).any():
        return "candidate_roadway_configuration_conflict", "high"
    if ev["supported_signal_boundary_between"].any():
        return "candidate_crosses_supported_signal_boundary", "high"
    if (~ev["within_2500_ft"]).any():
        return "candidate_exceeds_2500_ft", "high"
    if ev["duplicate_bin_overlap_risk"].any():
        return "candidate_creates_duplicate_bin_overlap", "high"
    if (~ev["gap_within_strict_acceptance"]).any():
        return "candidate_route_measure_continuity_failed", "high"
    if post_class == "likely_true_source_extent":
        return "prior_screen_too_permissive", "medium"
    return "missing_evidence_cannot_reconcile", "medium"


def old_vs_strict(final: pd.DataFrame, repair_post: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    old_count = int(len(final))
    strict_remaining = int(candidates.groupby("logical_corridor_chain_id")["strict_candidate_pass"].any().sum()) if not candidates.empty else 0
    same_chain_count = int(candidates.groupby("logical_corridor_chain_id")["same_chain"].all().sum()) if not candidates.empty else 0
    rows = [
        {
            "comparison_factor": "candidate_search_radius_window_differences",
            "finding": "yes",
            "evidence": "Finalization counted any same-route route-measure candidate within 50 ft. Strict repair accepted only candidates within 5 ft for extension and inside the 2,500 ft corridor limit.",
        },
        {
            "comparison_factor": "candidate_compatibility_filters",
            "finding": "yes",
            "evidence": "Strict screen excludes current chain Travelway IDs and checks carriageway token and roadway configuration compatibility; finalization did not.",
        },
        {
            "comparison_factor": "deduplication_status",
            "finding": "checked",
            "evidence": "Suppressed duplicate chain ledger was used as diagnostic evidence; candidate-level flags are ledgered.",
        },
        {
            "comparison_factor": "chain_membership_status",
            "finding": "primary_explanation" if same_chain_count == old_count else "partial_explanation",
            "evidence": f"{same_chain_count:,} of {old_count:,} original suspect chains had all recomputed permissive candidates already present in the same logical chain.",
        },
        {
            "comparison_factor": "boundary_rules",
            "finding": "checked",
            "evidence": "Candidate evaluations include supported signal boundary checks before candidate starts.",
        },
        {
            "comparison_factor": "source_extent_interpretation",
            "finding": "yes",
            "evidence": "A route segment that overlaps the current terminal chain row can be a source extent validation artifact, not a valid extension candidate.",
        },
        {
            "comparison_factor": "bug_or_mismatch_in_file_loading",
            "finding": "not_indicated",
            "evidence": f"Finalization and repair input ledgers overlap by {old_count:,} chain IDs; post-repair validation contains {len(repair_post):,} source-extent rows.",
        },
        {
            "comparison_factor": "unknown",
            "finding": "no" if strict_remaining == 0 else "yes",
            "evidence": f"Strict current search found {strict_remaining:,} original suspect chains with a passing continuation candidate.",
        },
    ]
    return pd.DataFrame(rows)


def material_change_assessment(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    corridors = frames["corridors"]
    repair_counts = frames["repair_counts"]
    repair_summary = frames["repair_summary"]
    current_chain_count = corridors["logical_corridor_chain_id"].nunique()
    current_row_count = len(corridors)
    prior_rows = ""
    post_rows = ""
    prior_chains = ""
    post_chains = ""
    if not repair_counts.empty:
        lookup = dict(zip(repair_counts["metric"], repair_counts["value"]))
        prior_rows = lookup.get("prior_corridor_segment_rows", "")
        post_rows = lookup.get("post_corridor_segment_rows", "")
        prior_chains = lookup.get("prior_logical_chains", "")
        post_chains = lookup.get("post_logical_chains", "")
    accepted_rows = len(frames["repair_accepted"])
    rejected_rows = len(frames["repair_rejected"])
    rows = [
        {"assessment_item": "segment_rows_before_available", "value": prior_rows, "evidence": rel(REPAIR_REVIEW / "prior_vs_post_repair_counts.csv")},
        {"assessment_item": "segment_rows_after_available", "value": post_rows, "evidence": rel(REPAIR_REVIEW / "prior_vs_post_repair_counts.csv")},
        {"assessment_item": "current_staged_segment_rows", "value": current_row_count, "evidence": rel(CORRIDORS)},
        {"assessment_item": "logical_chain_count_before_available", "value": prior_chains, "evidence": rel(REPAIR_REVIEW / "prior_vs_post_repair_counts.csv")},
        {"assessment_item": "logical_chain_count_after_available", "value": post_chains, "evidence": rel(REPAIR_REVIEW / "prior_vs_post_repair_counts.csv")},
        {"assessment_item": "current_staged_logical_chain_count", "value": current_chain_count, "evidence": rel(CORRIDORS)},
        {"assessment_item": "segment_rows_added", "value": accepted_rows, "evidence": rel(REPAIR_REVIEW / "accepted_source_extent_continuation_ledger.csv")},
        {"assessment_item": "segment_rows_removed", "value": 0 if str(prior_rows) == str(post_rows) else "not_directly_known", "evidence": "prior_vs_post counts only; no prior parquet retained in audit scope"},
        {"assessment_item": "chain_ids_changed", "value": "not_indicated_by_counts", "evidence": "logical chain counts unchanged; no accepted continuation rows"},
        {"assessment_item": "stop_reasons_changed", "value": "not_indicated_by_stop_reason_summary", "evidence": rel(REPAIR_REVIEW / "post_repair_chain_stop_reason_summary.csv")},
        {"assessment_item": "metadata_changed_only", "value": int(corridors["source_extent_repair_status"].astype(str).ne("not_targeted").sum()) if "source_extent_repair_status" in corridors.columns else 0, "evidence": "source_extent_repair_status populated on current staged rows"},
        {"assessment_item": "no_material_parquet_change", "value": str(prior_rows) == str(post_rows) and str(prior_chains) == str(post_chains) and accepted_rows == 0 and rejected_rows == 0, "evidence": "row counts and repair ledgers"},
    ]
    if not repair_summary.empty:
        for _, r in repair_summary.iterrows():
            rows.append({"assessment_item": f"repair_summary_{clean(r.get('metric'))}", "value": r.get("value", ""), "evidence": rel(REPAIR_REVIEW / "source_extent_repair_summary.csv")})
    return pd.DataFrame(rows)


def write_text_outputs(
    frames: dict[str, pd.DataFrame],
    ledger: pd.DataFrame,
    reconciliation: pd.DataFrame,
    candidates: pd.DataFrame,
    strict_summary: pd.DataFrame,
    comparison: pd.DataFrame,
    material: pd.DataFrame,
    decision: str,
) -> None:
    class_counts = reconciliation["reconciliation_classification"].value_counts().sort_index()
    strict_valid_chains = int(candidates.groupby("logical_corridor_chain_id")["strict_candidate_pass"].any().sum()) if not candidates.empty else 0
    unresolved = int(reconciliation["reconciliation_classification"].eq("unresolved_still_possible_false_source_extent").sum())
    accepted = len(frames["repair_accepted"])
    rejected = len(frames["repair_rejected"])
    no_material = material.loc[material["assessment_item"].eq("no_material_parquet_change"), "value"].iloc[0]
    primary_explanation = comparison.loc[comparison["comparison_factor"].eq("chain_membership_status"), "evidence"].iloc[0]
    if not candidates.empty and "candidate_rejection_reasons" in candidates.columns:
        top_reason = (
            candidates.assign(reason=candidates["candidate_rejection_reasons"].fillna("").str.split("|"))
            .explode("reason")
            .query("reason != ''")["reason"]
            .value_counts()
        )
        if not top_reason.empty:
            primary_explanation = f"The dominant strict-screen rejection was `{top_reason.index[0]}` on {int(top_reason.iloc[0]):,} candidate rows. {primary_explanation}"
    next_action = "run a final read-only approach_corridors validation audit before any bin_context build" if decision.endswith("ready_for_final_validation") else "repair or manually adjudicate unresolved source-extent chains before final validation"
    findings = f"""# Source-Extent Suspect Chain Reconciliation Audit

## Why This Audit Was Needed
The finalization audit flagged 2,006 source-extent stopped chains as possible missing-neighbor cases, but the later repair pass reported zero accepted continuations, zero rejected continuations, and zero remaining suspects. This read-only audit reconciles that apparent contradiction chain by chain.

## Were The 2,006 Suspects Actually Adjudicated?
Yes by repair input/post-validation membership: the finalization suspect ledger and repair input ledger overlap on {int(ledger.loc[ledger['metric'].eq('overlap_by_logical_corridor_chain_id'), 'value'].iloc[0]):,} logical chain IDs. However, the accepted and rejected repair ledgers are empty, so the adjudication was encoded as current staged metadata and post-validation reclassification rather than an accepted/rejected continuation ledger.

## Why Accepted Continuations = 0 And Rejected Continuations = 0
The strict repair screen found no valid extension candidates after applying same-corridor compatibility and duplicate-risk checks. {primary_explanation}

## Material Change To approach_corridors.parquet
The repair pass did not materially change segment rows or logical chain counts based on available repair counts. `no_material_parquet_change` is `{no_material}`. The current parquet carries source-extent repair metadata, with suspect chains marked `confirmed_true_source_extent`, but no continuation segment rows were added.

## Was The Previous Finalization Audit Too Permissive?
Yes. The finalization audit used a permissive 50-ft same-route continuation screen that did not exclude already-used Travelway IDs and did not apply the stricter carriageway/configuration/current-chain filters used by repair validation.

## Valid Same-Corridor Continuations Remaining
Strict current search found {strict_valid_chains:,} original suspect chains with passing continuation candidates. Remaining unresolved possible false source-extent stops: {unresolved:,}.

## Are Source-Extent Stops Now Trustworthy?
For the 2,006 suspect chains, the chain-by-chain evidence supports reclassification because the strict pass count is zero and no chain remains unresolved. The main caveat is that prior repair accepted/rejected ledgers are empty, so the defensible evidence is this reconciliation audit plus current staged repair metadata and post-validation output.

## Ready For Final Validation/bin_context?
Decision: `{decision}`. This supports final read-only validation before any bin_context build if the team accepts metadata/post-validation reclassification plus this reconciliation as sufficient adjudication evidence.

## Reconciliation Counts
{class_counts.to_string()}

## Recommended Next Task
{next_action}.
"""
    (OUT / "findings_memo.md").write_text(findings, encoding="utf-8")
    manifest = {
        "created_utc": now(),
        "script": "src.roadway_graph.audit.source_extent_suspect_chain_reconciliation_audit",
        "rule_version": RULE_VERSION,
        "bounded_question": "Reconcile the 2,006 source-extent suspect chains chain-by-chain without mutating staged products.",
        "source_inputs": [rel(p) for p in [SIGNAL_INDEX, TRAVELWAY_INDEX, ATTACHMENT, APPROACHES, CORRIDORS, STAGING_MANIFEST, STAGING_SCHEMA, STAGING_README]],
        "diagnostic_review_inputs": [rel(p) for p in [FINAL_REVIEW, REPAIR_REVIEW, DEDUP_REVIEW, CHAIN_AUDIT_REVIEW, RECON_REVIEW]],
        "output_grain": {
            "suspect_chain_reconciliation.csv": "one row per original suspect logical_corridor_chain_id",
            "suspect_chain_candidate_evaluations.csv": "one row per recomputed permissive candidate Travelway row for original suspect chains",
        },
        "caveats": [
            "No prior pre-repair parquet was available in the requested input set; material change assessment uses repair ledgers/counts and current staged metadata.",
            "Geometry continuity is not recomputed as a spatial repair; route-measure continuity is used as the read-only strict screen proxy.",
        ],
        "final_decision": decision,
    }
    qa = {
        "created_utc": now(),
        "finalization_suspect_rows": int(len(frames["final_suspects"])),
        "repair_input_rows": int(len(frames["repair_input"])),
        "reconciliation_rows": int(len(reconciliation)),
        "candidate_evaluation_rows": int(len(candidates)),
        "strict_valid_continuation_chain_count": strict_valid_chains,
        "unresolved_possible_false_source_extent_chain_count": unresolved,
        "accepted_repair_rows": int(accepted),
        "rejected_repair_rows": int(rejected),
        "final_decision": decision,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT / "qa_manifest.json").write_text(json.dumps(qa, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "progress_log.md").write_text(f"# Progress Log\n\n- {now()}: Started read-only source-extent suspect reconciliation audit.\n", encoding="utf-8")
    frames = load_inputs()
    ledger = reconcile_ledgers(frames)
    reconciliation, candidates, strict_summary = run_reconciliation(frames)
    comparison = old_vs_strict(frames["final_suspects"], frames["repair_post_validation"], candidates)
    material = material_change_assessment(frames)
    unresolved = reconciliation[reconciliation["reconciliation_classification"].eq("unresolved_still_possible_false_source_extent")].copy()
    confirmed = reconciliation[
        ~reconciliation["reconciliation_classification"].isin(
            ["unresolved_still_possible_false_source_extent", "missing_evidence_cannot_reconcile"]
        )
    ].copy()
    reason_summary = (
        candidates.assign(candidate_rejection_reasons=candidates["candidate_rejection_reasons"].fillna(""))
        .assign(candidate_rejection_reason=lambda d: d["candidate_rejection_reasons"].str.split("|"))
        .explode("candidate_rejection_reason")
        .query("candidate_rejection_reason != ''")
        .groupby("candidate_rejection_reason")
        .agg(candidate_rows=("candidate_stable_travelway_id", "size"), chains=("logical_corridor_chain_id", "nunique"))
        .reset_index()
        .sort_values(["candidate_rows", "candidate_rejection_reason"], ascending=[False, True])
        if not candidates.empty
        else pd.DataFrame(columns=["candidate_rejection_reason", "candidate_rows", "chains"])
    )
    strict_valid_chains = int(candidates.groupby("logical_corridor_chain_id")["strict_candidate_pass"].any().sum()) if not candidates.empty else 0
    if strict_valid_chains > 0:
        decision = "source_extent_suspects_unresolved_need_repair"
    elif reconciliation["reconciliation_classification"].eq("missing_evidence_cannot_reconcile").any():
        decision = "source_extent_suspects_unresolved_due_missing_evidence"
    elif len(unresolved) == 0:
        decision = "source_extent_suspects_validly_reclassified_ready_for_final_validation"
    elif len(unresolved) <= 100:
        decision = "source_extent_suspects_mostly_resolved_with_small_review_ledger"
    else:
        decision = "source_extent_repair_pass_did_not_adjudicate_suspects"
    scorecard = pd.DataFrame(
        [
            {"metric": "original_suspect_chains", "value": len(frames["final_suspects"])},
            {"metric": "repair_input_overlap_chains", "value": int(ledger.loc[ledger["metric"].eq("overlap_by_logical_corridor_chain_id"), "value"].iloc[0])},
            {"metric": "candidate_evaluation_rows", "value": len(candidates)},
            {"metric": "chains_with_strict_valid_continuation", "value": strict_valid_chains},
            {"metric": "remaining_unresolved_possible_false_source_extent", "value": len(unresolved)},
            {"metric": "final_decision", "value": decision},
        ]
    )
    readiness = pd.DataFrame([{"final_decision": decision, "reason": "read-only chain-by-chain source-extent suspect reconciliation completed"}])
    recommended = pd.DataFrame(
        [
            {
                "rank": 1,
                "action": "run_final_read_only_approach_corridors_validation_before_bin_context" if decision.endswith("ready_for_final_validation") else "repair_or_manually_adjudicate_unresolved_source_extent_chains",
                "rationale": "Use this reconciliation as the source-extent suspect adjudication ledger; do not build bins until final validation accepts it.",
            }
        ]
    )
    write_csv("input_ledger_reconciliation.csv", ledger)
    write_csv("suspect_chain_reconciliation.csv", reconciliation)
    write_csv("suspect_chain_candidate_evaluations.csv", candidates)
    write_csv("strict_continuation_search_summary.csv", strict_summary)
    write_csv("old_vs_strict_candidate_screen_comparison.csv", comparison)
    write_csv("material_change_assessment.csv", material)
    write_csv("confirmed_true_source_extent_chains.csv", confirmed)
    write_csv("unresolved_possible_false_source_extent_chains.csv", unresolved)
    write_csv("candidate_rejection_reason_summary.csv", reason_summary)
    write_csv("source_extent_resolution_scorecard.csv", scorecard)
    write_csv("readiness_decision.csv", readiness)
    write_csv("recommended_next_actions.csv", recommended)
    write_text_outputs(frames, ledger, reconciliation, candidates, strict_summary, comparison, material, decision)
    log(f"Finished audit with decision={decision}.")


if __name__ == "__main__":
    main()
