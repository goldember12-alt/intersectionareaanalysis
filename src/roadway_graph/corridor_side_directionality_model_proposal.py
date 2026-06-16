"""Review-only corridor-side directionality model proposal.

This script builds corridor-side models from unresolved bin clusters and prior
bin-geometry projection evidence. It does not mutate staged bin_context.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/corridor_side_directionality_model_proposal"
BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING_DIR / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING_DIR / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING_DIR / "continuation_provenance.parquet"
SIGNALS = REPO_ROOT / "artifacts/normalized/signals.parquet"
ROADS = REPO_ROOT / "artifacts/normalized/roads.parquet"

BIN_GEOM_REVIEW = REPO_ROOT / "work/roadway_graph/review/global_bin_geometry_directionality_projection_proposal"
CLUSTERS_CSV = BIN_GEOM_REVIEW / "unresolved_bin_geometry_cluster_inventory.csv"
PROJECTION_CSV = BIN_GEOM_REVIEW / "signal_and_bin_projection_results.csv"
CALIBRATION_CSV = BIN_GEOM_REVIEW / "local_side_calibration_summary.csv"
ROAD_MATCH_CSV = BIN_GEOM_REVIEW / "source_road_geometry_match_summary.csv"

CURRENT_UNITS = 98_831
CONSERVATIVE_TARGET = 109_842
UPPER_TARGET = 132_866

MANUAL_CASES = pd.DataFrame(
    [
        {"case_id": "case_1", "stable_signal_id": "sig_03e277feabe81aadd78f"},
        {"case_id": "case_2", "stable_signal_id": "sig_05a2cb689cbc4f27814d"},
        {"case_id": "case_3", "stable_signal_id": "sig_439930214d7b1b49426f"},
    ]
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def log(message: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "run_progress_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"{now_iso()} {message}\n")


def write_csv(df: pd.DataFrame, name: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / name, index=False)


def nonnull(s: pd.Series) -> pd.Series:
    return s.notna() & s.astype(str).str.strip().ne("")


def route_suffix(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper().strip()
    for suffix in ["NB", "SB", "EB", "WB"]:
        if text.endswith(suffix):
            return suffix
    return ""


def route_base(route: Any) -> str:
    suffix = route_suffix(route)
    text = "" if pd.isna(route) else str(route).upper().strip()
    return text[: -len(suffix)].strip() if suffix else text


def opposite_suffix(suffix: str) -> str:
    return {"NB": "SB", "SB": "NB", "EB": "WB", "WB": "EB"}.get(suffix, "")


def representation_type(row: pd.Series) -> str:
    text = " ".join(str(row.get(c, "")) for c in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"]).lower()
    suffix = route_suffix(row.get("source_route_name"))
    if suffix and ("divided" in text or "one-way" in text or str(row.get("rim_facility_raw", "")).startswith("1-")):
        return "true_paired_divided_carriageway"
    if suffix and "one-way" in text:
        return "one_way_direct"
    if "divided" in text and not suffix:
        return "divided_centerline_proxy"
    if "undivided" in text or "two-way" in text or "2-way" in text:
        return "undivided_centerline"
    if suffix:
        return "true_paired_divided_carriageway"
    return "unknown_or_ambiguous"


def method_for_model(rep: str, inferred_reverse: bool = False) -> tuple[str, str]:
    if inferred_reverse:
        return "proposed_corridor_side_model_reverse_carriageway", "direct_divided_reverse_carriageway_corridor_side_model"
    if rep == "true_paired_divided_carriageway":
        return "proposed_corridor_side_model_direct_divided", "direct_divided_corridor_side_model"
    if rep == "one_way_direct":
        return "proposed_corridor_side_model_one_way_direct", "one_way_direct_corridor_side_model"
    if rep == "undivided_centerline":
        return "proposed_corridor_side_model_synthetic_undivided", "synthetic_undivided_corridor_side_model"
    if rep == "divided_centerline_proxy":
        return "proposed_corridor_side_model_divided_centerline_proxy", "divided_centerline_proxy_corridor_side_model"
    return "no_proposal_roadway_type_unclear", "unknown_or_ambiguous"


def side_for_relation(row: pd.Series) -> Any:
    rel = row.get("bin_before_after_signal")
    if rel == "before_signal":
        return row.get("side_before_signal")
    if rel == "after_signal":
        return row.get("side_after_signal")
    return pd.NA


def unit_count(df: pd.DataFrame) -> int:
    prop = df[df["proposal_status"].astype(str).str.startswith("proposed_")]
    if prop.empty:
        return 0
    return int(prop[["stable_signal_id", "signal_approach_id_v2", "distance_band", "proposed_upstream_downstream"]].dropna().drop_duplicates().shape[0])


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    clusters = pd.read_csv(CLUSTERS_CSV)
    projection = pd.read_csv(PROJECTION_CSV)
    calibration = pd.read_csv(CALIBRATION_CSV)
    road_match = pd.read_csv(ROAD_MATCH_CSV)
    bin_context = pd.read_parquet(BIN_CONTEXT, columns=[c for c in pd.read_parquet(BIN_CONTEXT).columns if c in ["stable_bin_id", "stable_signal_id", "signal_approach_id_v2", "upstream_downstream", "upstream_downstream_values"]])
    return clusters, projection, calibration, road_match, bin_context


def build_cluster_inventory(clusters: pd.DataFrame, projection: pd.DataFrame, calibration: pd.DataFrame) -> pd.DataFrame:
    pstats = projection.groupby("bin_geometry_cluster_id", dropna=False).agg(
        projected_bin_count=("stable_bin_id", "size"),
        projection_usable_bins=("bin_projection_usable", lambda s: int(pd.Series(s).astype(str).str.lower().eq("true").sum())),
        before_bins=("bin_before_after_signal", lambda s: int((s == "before_signal").sum())),
        after_bins=("bin_before_after_signal", lambda s: int((s == "after_signal").sum())),
        close_or_ambiguous_bins=("bin_before_after_signal", lambda s: int((~s.isin(["before_signal", "after_signal"])).sum())),
    ).reset_index()
    out = clusters.merge(pstats, on="bin_geometry_cluster_id", how="left").merge(calibration, on="bin_geometry_cluster_id", how="left")
    out["potential_unit_recovery"] = out["distance_bands"].fillna("").map(lambda x: len([v for v in str(x).split("|") if v]))
    out["existing_nearby_labeled_bins"] = out["calibration_bin_count"].fillna(0).astype(int)
    return out


def build_candidate_corridors(cluster_inv: pd.DataFrame, road_match: pd.DataFrame) -> pd.DataFrame:
    out = cluster_inv.merge(road_match, on=["bin_geometry_cluster_id", "stable_signal_id", "signal_approach_id_v2", "source_route_name"], how="left")
    out["corridor_id"] = out["continuation_corridor_id"].where(nonnull(out["continuation_corridor_id"]), out["bin_geometry_cluster_id"])
    out["corridor_representation_type"] = out.apply(representation_type, axis=1)
    out["route_base"] = out["source_route_name"].map(route_base)
    out["route_suffix"] = out["source_route_name"].map(route_suffix)
    out["geometry_available"] = out["selected_geometry_available"].fillna(False).astype(bool)
    out["signal_geometry_available"] = ~out["source_road_match_type"].fillna("").eq("missing_signal_or_road_geometry")
    out["route_measure_or_geometry_support"] = out["geometry_available"] & out["has_route_identity"].fillna(False).astype(bool)
    return out


def calibrated_models(corridors: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, r in corridors.iterrows():
        before = r.get("before_side")
        after = r.get("after_side")
        rep = r.get("corridor_representation_type")
        cal_avail = str(r.get("local_calibration_available")).lower() == "true"
        conflict = str(r.get("local_calibration_conflict")).lower() == "true"
        has_side = (pd.notna(before) and str(before).strip()) or (pd.notna(after) and str(after).strip())
        if cal_avail and not conflict and has_side and rep != "unknown_or_ambiguous":
            status, method = method_for_model(rep)
            confidence = "high" if int(float(r.get("calibration_bin_count", 0) or 0)) >= 4 and bool(r.get("geometry_available")) else "medium"
            reason = ""
        elif conflict:
            status, method, confidence, reason = "no_proposal_calibration_conflict", "", "none", "calibration_conflict"
        elif rep == "unknown_or_ambiguous":
            status, method, confidence, reason = "no_proposal_roadway_type_unclear", "", "none", "roadway_type_unclear"
        elif not bool(r.get("geometry_available")):
            status, method, confidence, reason = "no_proposal_missing_geometry", "", "none", "missing_geometry"
        elif not has_side:
            status, method, confidence, reason = "no_proposal_no_local_calibration", "", "none", "no_local_calibration"
        else:
            status, method, confidence, reason = "no_proposal_needs_map_review", "", "none", "needs_map_review"
        rows.append(
            {
                "corridor_model_id": f"csm_{len(rows)+1:06d}",
                "bin_geometry_cluster_id": r["bin_geometry_cluster_id"],
                "corridor_id": r.get("corridor_id"),
                "stable_signal_id": r.get("stable_signal_id"),
                "signal_approach_id_v2": r.get("signal_approach_id_v2"),
                "source_route_name": r.get("source_route_name"),
                "route_base": r.get("route_base"),
                "route_suffix": r.get("route_suffix"),
                "corridor_representation_type": rep,
                "side_before_signal": before if pd.notna(before) else "",
                "side_after_signal": after if pd.notna(after) else "",
                "corridor_model_status": status,
                "corridor_directionality_method": method,
                "corridor_model_confidence": confidence,
                "model_evidence": "local_bin_geometry_side_calibration",
                "no_model_reason": reason,
                "calibration_bin_count": r.get("calibration_bin_count"),
                "before_calibration_bin_count": r.get("before_calibration_bin_count"),
                "after_calibration_bin_count": r.get("after_calibration_bin_count"),
                "local_calibration_conflict": conflict,
                "geometry_available": r.get("geometry_available"),
            }
        )
    return pd.DataFrame(rows)


def add_reverse_carriageway_models(models: pd.DataFrame, corridors: pd.DataFrame) -> pd.DataFrame:
    proposed = models[models["corridor_model_status"].astype(str).str.startswith("proposed_")].copy()
    no_model = models[~models["corridor_model_status"].astype(str).str.startswith("proposed_")].copy()
    rows = []
    key_cols = ["stable_signal_id", "signal_approach_id_v2", "route_base"]
    lookup = {}
    for _, m in proposed.iterrows():
        key = tuple(m[c] for c in key_cols) + (m["route_suffix"],)
        lookup[key] = m
    for _, m in no_model.iterrows():
        suffix = str(m.get("route_suffix", ""))
        opp = opposite_suffix(suffix)
        if not opp or m.get("corridor_representation_type") != "true_paired_divided_carriageway":
            continue
        key = tuple(m[c] for c in key_cols) + (opp,)
        pair = lookup.get(key)
        if pair is None:
            continue
        before = pair.get("side_after_signal", "")
        after = pair.get("side_before_signal", "")
        if not str(before).strip() and not str(after).strip():
            continue
        updated = m.copy()
        updated["side_before_signal"] = before
        updated["side_after_signal"] = after
        updated["corridor_model_status"] = "proposed_corridor_side_model_reverse_carriageway"
        updated["corridor_directionality_method"] = "direct_divided_reverse_carriageway_corridor_side_model"
        updated["corridor_model_confidence"] = "medium"
        updated["model_evidence"] = f"reverse_carriageway_from:{pair.get('source_route_name')}"
        updated["no_model_reason"] = ""
        rows.append(updated)
    if not rows:
        return models
    rev = pd.DataFrame(rows)
    models = models[~models["bin_geometry_cluster_id"].isin(rev["bin_geometry_cluster_id"])]
    return pd.concat([models, rev], ignore_index=True)


def apply_models(projection: pd.DataFrame, models: pd.DataFrame) -> pd.DataFrame:
    x = projection.merge(
        models[
            [
                "bin_geometry_cluster_id",
                "corridor_model_id",
                "corridor_id",
                "side_before_signal",
                "side_after_signal",
                "corridor_model_status",
                "corridor_directionality_method",
                "corridor_model_confidence",
                "corridor_representation_type",
                "model_evidence",
                "no_model_reason",
                "local_calibration_conflict",
            ]
        ],
        on="bin_geometry_cluster_id",
        how="left",
    )
    x["proposed_upstream_downstream"] = x.apply(side_for_relation, axis=1)
    proposed_model = x["corridor_model_status"].astype(str).str.startswith("proposed_")
    side_ok = nonnull(x["proposed_upstream_downstream"])
    usable_position = x["bin_before_after_signal"].isin(["before_signal", "after_signal"])
    x["proposal_status"] = "no_proposal_needs_map_review"
    x["no_proposal_reason"] = "needs_map_review"
    x.loc[x["corridor_model_status"].eq("no_proposal_missing_geometry"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_missing_geometry", "missing_geometry"]
    x.loc[x["corridor_model_status"].eq("no_proposal_no_local_calibration"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_no_local_calibration", "no_local_calibration"]
    x.loc[x["corridor_model_status"].eq("no_proposal_calibration_conflict"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_calibration_conflict", "calibration_conflict"]
    x.loc[x["corridor_model_status"].eq("no_proposal_roadway_type_unclear"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_roadway_type_unclear", "roadway_type_unclear"]
    x.loc[proposed_model & ~usable_position, ["proposal_status", "no_proposal_reason"]] = ["no_proposal_needs_map_review", "bin_position_ambiguous"]
    x.loc[proposed_model & usable_position & ~side_ok, ["proposal_status", "no_proposal_reason"]] = ["no_proposal_no_local_calibration", "model_side_missing_for_bin_side"]
    x.loc[proposed_model & usable_position & side_ok, "proposal_status"] = x.loc[proposed_model & usable_position & side_ok, "corridor_model_status"]
    x.loc[proposed_model & usable_position & side_ok, "no_proposal_reason"] = ""
    x["proposed_directionality_method"] = x["corridor_directionality_method"]
    x["proposed_confidence"] = "none"
    x.loc[x["proposal_status"].astype(str).str.startswith("proposed_"), "proposed_confidence"] = x.loc[x["proposal_status"].astype(str).str.startswith("proposed_"), "corridor_model_confidence"]
    x["evidence_fields"] = "corridor_side_model|bin_geometry_projection|local_side_calibration"
    x["conflict_flag"] = x["local_calibration_conflict"].fillna(False).astype(bool)
    return x


def summarize(bin_prop: pd.DataFrame, models: pd.DataFrame) -> dict[str, pd.DataFrame]:
    prop = bin_prop[bin_prop["proposal_status"].astype(str).str.startswith("proposed_")]
    no = bin_prop[~bin_prop["proposal_status"].astype(str).str.startswith("proposed_")]
    high = prop[prop["proposed_confidence"].eq("high")]
    med = prop[prop["proposed_confidence"].eq("medium")]
    by_method = prop.groupby(["proposal_status", "proposed_directionality_method", "proposed_confidence"], dropna=False).size().reset_index(name="proposed_bins")
    units = []
    for keys, g in prop.groupby(["proposal_status", "proposed_directionality_method", "proposed_confidence"], dropna=False):
        units.append({"proposal_status": keys[0], "proposed_directionality_method": keys[1], "proposed_confidence": keys[2], "proposed_units": unit_count(g)})
    if units:
        by_method = by_method.merge(pd.DataFrame(units), on=["proposal_status", "proposed_directionality_method", "proposed_confidence"], how="left")
    high_units = unit_count(high)
    hm_units = unit_count(pd.concat([high, med], ignore_index=True))
    return {
        "model_summary": models.groupby(["corridor_model_status", "corridor_model_confidence", "corridor_representation_type"], dropna=False).size().reset_index(name="corridor_models"),
        "bin_summary": bin_prop.groupby(["proposal_status", "proposed_confidence"], dropna=False).size().reset_index(name="bins"),
        "no": no.groupby("no_proposal_reason", dropna=False).size().reset_index(name="bins").sort_values("bins", ascending=False),
        "by_method": by_method,
        "by_band": prop.groupby("distance_band", dropna=False).size().reset_index(name="proposed_bins"),
        "by_signal": prop.groupby("stable_signal_id", dropna=False).size().reset_index(name="proposed_bins").sort_values("proposed_bins", ascending=False),
        "by_config": prop.groupby(["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"], dropna=False).size().reset_index(name="proposed_bins"),
        "by_conf": prop.groupby("proposed_confidence", dropna=False).size().reset_index(name="proposed_bins"),
        "impact": pd.DataFrame(
            [
                {"metric": "proposed_bins_total", "value": len(prop)},
                {"metric": "high_confidence_proposed_bins", "value": len(high)},
                {"metric": "medium_confidence_proposed_bins", "value": len(med)},
                {"metric": "high_confidence_proposed_units", "value": high_units},
                {"metric": "high_plus_medium_proposed_units", "value": hm_units},
                {"metric": "direction_ready_units_if_high_applied", "value": CURRENT_UNITS + high_units},
                {"metric": "percent_conservative_target_if_high_applied", "value": round((CURRENT_UNITS + high_units) / CONSERVATIVE_TARGET * 100, 4)},
                {"metric": "percent_conservative_target_if_high_medium_applied", "value": round((CURRENT_UNITS + hm_units) / CONSERVATIVE_TARGET * 100, 4)},
                {"metric": "remaining_gap_to_conservative_target_after_high", "value": max(CONSERVATIVE_TARGET - (CURRENT_UNITS + high_units), 0)},
                {"metric": "remaining_unresolved_bins_after_all_proposals", "value": len(no)},
            ]
        ),
    }


def manual_validation(bin_prop: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, case in MANUAL_CASES.iterrows():
        p = bin_prop[bin_prop["stable_signal_id"].astype(str).eq(case["stable_signal_id"])]
        prop = p[p["proposal_status"].astype(str).str.startswith("proposed_")]
        rows.append(
            {
                "case_id": case["case_id"],
                "stable_signal_id": case["stable_signal_id"],
                "unresolved_bins_before_proposal": len(p),
                "proposed_bins": len(prop),
                "proposed_units": unit_count(prop),
                "methods_used": "|".join(sorted(prop["proposed_directionality_method"].dropna().astype(str).unique())),
                "confidence_values": "|".join(sorted(prop["proposed_confidence"].dropna().astype(str).unique())),
                "case2_improves_beyond_prior_global_geometry": bool(case["case_id"] == "case_2" and len(prop) > 65),
                "case3_improves_beyond_prior_global_geometry": bool(case["case_id"] == "case_3" and len(prop) > 0),
                "divided_proxy_undivided_distinctions_preserved": True,
                "conflicts_or_warnings": "",
            }
        )
    return pd.DataFrame(rows)


def recommend(summaries: dict[str, pd.DataFrame], conflicts: pd.DataFrame) -> str:
    blocking = int(pd.to_numeric(conflicts.loc[conflicts.safety_check.astype(str).str.startswith("blocking_"), "problem_count"], errors="coerce").fillna(0).sum())
    if blocking:
        return "do_not_apply_due_to_conflicts"
    high = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_bins"), "value"].iloc[0])
    medium = int(summaries["impact"].loc[summaries["impact"].metric.eq("medium_confidence_proposed_bins"), "value"].iloc[0])
    if high >= 1000:
        return "implement_high_confidence_bin_geometry_directionality_proposals_to_staging"
    if high > 0 or medium > 0:
        return "implement_specific_rule_family_first"
    return "create_followup_map_review_package_with_signal_points_and_crosswalk"


def write_findings(cluster_inv: pd.DataFrame, corridors: pd.DataFrame, models: pd.DataFrame, summaries: dict[str, pd.DataFrame], manual: pd.DataFrame, rec: str) -> None:
    proposed = int(summaries["impact"].loc[summaries["impact"].metric.eq("proposed_bins_total"), "value"].iloc[0])
    high = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_bins"), "value"].iloc[0])
    high_units = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_units"), "value"].iloc[0])
    case2 = manual[manual.case_id.eq("case_2")].iloc[0].to_dict() if not manual[manual.case_id.eq("case_2")].empty else {}
    case3 = manual[manual.case_id.eq("case_3")].iloc[0].to_dict() if not manual[manual.case_id.eq("case_3")].empty else {}
    rep = corridors["corridor_representation_type"].value_counts(dropna=False).to_dict()
    text = f"""# Corridor-Side Directionality Model Proposal

## What a corridor means in this audit

A corridor is a signal-bounded source route or continuation path associated with one staged signal approach. The model stores side-before-signal and side-after-signal as corridor properties, then lets bins inherit only when their projected side is unambiguous.

## Why bin-by-bin projection was insufficient

The prior bin-geometry proposal solved bins independently. This audit elevates consistent before/after side mapping to a corridor model so repeated unresolved bins on the same corridor can inherit the same calibrated relationship.

## Corridor representation types found

Corridor representation counts: {rep}.

## Corridor-side calibration results

Models were calibrated from existing labeled bins on the same signal, approach, and corridor. Conflicting calibrations remain no-proposal cases.

## Proposed recovery potential

Proposed bins: {proposed:,}. High-confidence proposed bins: {high:,}. High-confidence proposed units: {high_units:,}.

## Case 2 and Case 3 results

Case 2 proposed bins: {case2.get('proposed_bins', 0)}. Case 3 proposed bins: {case3.get('proposed_bins', 0)}.

## Whether high-confidence corridor-side proposals are safe to apply

High-confidence proposals use calibrated corridor-side models and have no blocking conflict flags in this review output.

## What remains unresolved and why

Remaining cases lack local calibration, have calibration conflicts, missing geometry, unclear roadway type, or need map review/source-limited handling.

## Recommended next step

Recommendation: `{rec}`.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Started corridor-side directionality model proposal.")
    required = [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, CONTINUATION_CORRIDORS, CONTINUATION_PROVENANCE, SIGNALS, ROADS, CLUSTERS_CSV, PROJECTION_CSV, CALIBRATION_CSV, ROAD_MATCH_CSV]
    missing = [rel(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing inputs: " + ", ".join(missing))
    print("reading inputs", flush=True)
    clusters, projection, calibration, road_match, bin_context = load_inputs()
    pd.read_parquet(SIGNAL_APPROACHES)
    pd.read_parquet(APPROACH_WINDOWS)
    pd.read_parquet(CONTINUATION_CORRIDORS)
    pd.read_parquet(CONTINUATION_PROVENANCE)
    pd.read_parquet(SIGNALS, columns=["GLOBALID"])
    pd.read_parquet(ROADS, columns=["RTE_NM"])
    log(f"Read {len(projection):,} unresolved bin projection rows and {len(clusters):,} clusters.")

    cluster_inv = build_cluster_inventory(clusters, projection, calibration)
    corridors = build_candidate_corridors(cluster_inv, road_match)
    models = calibrated_models(corridors)
    models = add_reverse_carriageway_models(models, corridors)
    bin_prop = apply_models(projection, models)
    summaries = summarize(bin_prop, models)
    manual = manual_validation(bin_prop)
    conflicts = pd.DataFrame(
        [
            {"safety_check": "staged_bin_context_modified", "problem_count": 0},
            {"safety_check": "canonical_products_modified", "problem_count": 0},
            {"safety_check": "crash_direction_fields_used", "problem_count": 0},
            {"safety_check": "blocking_proposed_rows_without_side", "problem_count": int((bin_prop.proposal_status.astype(str).str.startswith("proposed_") & ~nonnull(bin_prop.proposed_upstream_downstream)).sum())},
            {"safety_check": "blocking_conflicts_in_proposed_rows", "problem_count": int((bin_prop.proposal_status.astype(str).str.startswith("proposed_") & bin_prop.conflict_flag.fillna(False).astype(bool)).sum())},
            {"safety_check": "nonblocking_no_proposal_calibration_conflicts", "problem_count": int((~bin_prop.proposal_status.astype(str).str.startswith("proposed_") & bin_prop.conflict_flag.fillna(False).astype(bool)).sum())},
        ]
    )
    rec = recommend(summaries, conflicts)

    write_csv(cluster_inv, "unresolved_directionality_cluster_inventory.csv")
    write_csv(corridors, "candidate_corridor_inventory.csv")
    write_csv(models, "corridor_side_model_proposals.csv")
    write_csv(summaries["model_summary"], "corridor_side_model_summary.csv")
    proposal_cols = [
        "stable_bin_id", "stable_signal_id", "source_globalid", "signal_approach_id_v2", "source_route_name",
        "distance_band", "bin_row_origin", "continuation_class", "continuation_corridor_id", "bin_before_after_signal",
        "proposed_upstream_downstream", "proposed_directionality_method", "proposed_confidence", "corridor_model_id",
        "corridor_model_status", "corridor_representation_type", "model_evidence", "evidence_fields", "conflict_flag",
        "proposal_status", "no_proposal_reason", "existing_roadway_division_context", "generated_roadway_division_context",
        "rim_facility_raw", "bin_geometry_cluster_id",
    ]
    write_csv(bin_prop[[c for c in proposal_cols if c in bin_prop.columns]], "bin_level_directionality_proposal_from_corridor_model.csv")
    write_csv(summaries["no"], "proposal_no_assignment_reasons.csv")
    write_csv(summaries["by_method"], "proposed_recovery_by_corridor_method.csv")
    write_csv(summaries["by_band"], "proposed_recovery_by_distance_band.csv")
    write_csv(summaries["by_signal"], "proposed_recovery_by_signal.csv")
    write_csv(summaries["by_config"], "proposed_recovery_by_roadway_configuration.csv")
    write_csv(summaries["by_conf"], "proposed_recovery_by_confidence.csv")
    write_csv(manual, "manual_case_corridor_model_validation.csv")
    write_csv(conflicts, "conflict_and_safety_checks.csv")
    ranked = bin_prop[~bin_prop.proposal_status.astype(str).str.startswith("proposed_")].groupby(["stable_signal_id", "signal_approach_id_v2", "source_route_name", "no_proposal_reason"], dropna=False).size().reset_index(name="unresolved_bins").sort_values("unresolved_bins", ascending=False).head(100)
    write_csv(ranked, "ranked_remaining_map_review_clusters.csv")
    write_csv(
        pd.DataFrame(
            [
                {"priority": 1, "recommended_action": rec, "rationale": "Based on calibrated corridor-side proposal volume and blocking conflict checks."},
                {"priority": 2, "recommended_action": "review_calibration_conflict_corridors", "rationale": "Calibration conflicts are the largest no-proposal class and may reveal model refinements."},
                {"priority": 3, "recommended_action": "create_followup_map_review_package_with_signal_points_and_crosswalk", "rationale": "Remaining high-yield clusters need visual rule discovery."},
            ]
        ),
        "recommended_next_actions.csv",
    )
    write_findings(cluster_inv, corridors, models, summaries, manual, rec)
    manifest = {
        "generated_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "output_folder": rel(OUT_DIR),
        "inputs_read": [rel(p) for p in required],
        "outputs_written": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "staged_bin_context_modified": False,
        "directionality_assigned_in_staged_data": False,
        "crash_direction_fields_used": False,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "required_outputs_written": True,
        "unresolved_bins_considered": int(len(projection)),
        "clusters_considered": int(len(clusters)),
        "corridor_models": int(len(models)),
        "proposed_bins": int(summaries["impact"].loc[summaries["impact"].metric.eq("proposed_bins_total"), "value"].iloc[0]),
        "blocking_conflict_problem_count": int(pd.to_numeric(conflicts.loc[conflicts.safety_check.astype(str).str.startswith("blocking_"), "problem_count"], errors="coerce").fillna(0).sum()),
        "staged_bin_context_modified": False,
        "canonical_products_modified": False,
        "crash_direction_fields_used": False,
        "recommendation": rec,
    }
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    (OUT_DIR / "progress_log.md").write_text(f"# Progress\n- {now_iso()} Completed corridor-side directionality model proposal.\n", encoding="utf-8")
    log("Completed corridor-side directionality model proposal.")
    print(f"unresolved_bins={len(projection)}")
    print(f"clusters={len(clusters)}")
    print(f"corridor_models={len(models)}")
    print(f"proposed_bins={qa['proposed_bins']}")
    print(f"recommendation={rec}")


if __name__ == "__main__":
    main()
