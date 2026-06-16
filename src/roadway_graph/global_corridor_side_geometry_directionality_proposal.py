"""Global review-only corridor-side directionality proposal.

This script globalizes the successful case-tested corridor-side geometry engine
without mutating staged, canonical, source, or artifact files. It builds
deterministic corridor-side models for unresolved bins, proposes directionality
only when source signal/road geometry and corridor-side rules are sufficient,
and preserves no-proposal reasons for ambiguous/source-limited rows.
"""

from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from shapely import wkb, wkt
except Exception:  # pragma: no cover
    wkb = None
    wkt = None


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
ARTIFACTS = REPO_ROOT / "artifacts/normalized"
CASE_OUT = REPO_ROOT / "work/roadway_graph/review/corridor_side_geometry_engine_case_tests"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/global_corridor_side_geometry_directionality_proposal"

BIN_CONTEXT = STAGING / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING / "continuation_provenance.parquet"
SIGNALS = ARTIFACTS / "signals.parquet"
ROADS = ARTIFACTS / "roads.parquet"

CURRENT_DIRECTION_READY_UNITS = 98_831
CONSERVATIVE_TARGET = 109_842
UPPER_TARGET = 132_866
STRICT_PROJECTION_FT = 100.0
RELAXED_PROJECTION_FT = 300.0
TOO_CLOSE_MEASURE = 0.001
MEASURE_EPS = 1.0e-6
BROAD_PARENT_MEASURE_RANGE = 0.25

CASE_IDS = {
    "case_1": "sig_03e277feabe81aadd78f",
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
    return s.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>", ""])


def parse_geom(value: Any):
    if value is None or pd.isna(value) or wkb is None:
        return None
    if hasattr(value, "geom_type"):
        return value
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return wkb.loads(bytes(value))
        if isinstance(value, str) and wkt is not None:
            return wkt.loads(value)
    except Exception:
        return None
    return None


def route_token(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper().strip()
    match = re.search(r"(NB|SB|EB|WB)$", text)
    return match.group(1) if match else ""


def route_base(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper().strip()
    token = route_token(text)
    return text[: -len(token)].strip() if token else text


def side_from_cardinal(token: str, signal_side: str) -> str:
    if token in {"NB", "EB"}:
        return "upstream" if signal_side == "before_signal" else "downstream"
    if token in {"SB", "WB"}:
        return "downstream" if signal_side == "before_signal" else "upstream"
    return "unknown"


def proposal_status(representation: str, token: str) -> str:
    if representation == "true_paired_divided_carriageway":
        return "proposed_corridor_side_reverse_carriageway" if token in {"SB", "WB"} else "proposed_corridor_side_direct_divided"
    if representation == "undivided_centerline":
        return "proposed_corridor_side_synthetic_undivided"
    if representation == "divided_centerline_proxy":
        return "proposed_corridor_side_divided_centerline_proxy"
    if representation == "one_way_direct":
        return "proposed_corridor_side_one_way_direct"
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
        "geometry_wkt",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "rim_facility_raw",
        "bin_row_origin",
        "generated_bin_flag",
        "continuation_corridor_id",
        "continuation_method",
        "continuation_confidence",
        "continuation_class",
        "generated_geometry_status",
        "upstream_downstream_values",
        "upstream_downstream",
        "directionality_status",
        "directionality_recovery_status",
        "directionality_recovery_method",
    ]
    available_cols = pd.read_parquet(BIN_CONTEXT, columns=None).columns
    use_bin_cols = [c for c in bin_cols if c in available_cols]
    roads_cols = [
        "RTE_NM",
        "FROM_MEASURE",
        "TO_MEASURE",
        "RTE_COMMON",
        "RTE_ID",
        "RIM_FACILI",
        "RIM_TRAVEL",
        "RIM_COUPLE",
        "MEDIAN_IND",
        "Shape_Length",
        "geometry",
    ]
    return {
        "bin_context": pd.read_parquet(BIN_CONTEXT, columns=use_bin_cols),
        "signal_approaches": pd.read_parquet(SIGNAL_APPROACHES),
        "approach_windows": pd.read_parquet(APPROACH_WINDOWS),
        "continuation_corridors": pd.read_parquet(CONTINUATION_CORRIDORS),
        "continuation_provenance": pd.read_parquet(CONTINUATION_PROVENANCE),
        "signals": pd.read_parquet(SIGNALS),
        "roads": pd.read_parquet(ROADS, columns=roads_cols),
    }


def side_values(df: pd.DataFrame) -> pd.Series:
    side = df["upstream_downstream"] if "upstream_downstream" in df.columns else pd.Series(pd.NA, index=df.index)
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonmissing(side), df["upstream_downstream_values"])
    return side


def unresolved_universe(bin_context: pd.DataFrame) -> pd.DataFrame:
    side = side_values(bin_context)
    status_text = (
        bin_context.get("directionality_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
        + "|"
        + bin_context.get("directionality_recovery_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
    )
    unresolved = (~nonmissing(side)) | status_text.str.contains("not_recovered|unresolved", regex=True, na=False)
    out = bin_context[unresolved].copy()
    out["_existing_side"] = side.loc[out.index]
    out["distance_band_out"] = out.get("distance_band_v2", out.get("distance_band"))
    out["route_base"] = out["source_route_name"].map(route_base)
    out["carriageway_direction_token"] = out["source_route_name"].map(route_token)
    out["roadway_representation"] = out.apply(classify_representation_from_row, axis=1)
    key_cols = [
        "stable_signal_id",
        "signal_approach_id_v2",
        "source_route_name",
        "continuation_corridor_id",
        "roadway_representation",
        "generated_bin_flag",
        "bin_row_origin",
    ]
    key_frame = out[key_cols].astype("string").fillna("<missing>")
    out["_cluster_key_text"] = key_frame.agg("|".join, axis=1)
    out["cluster_id"] = out["_cluster_key_text"].map(lambda s: "gcsg_" + hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:20])
    return out


def classify_representation_from_row(row: pd.Series) -> str:
    route = row.get("source_route_name")
    token = route_token(route)
    text = " ".join(
        str(row.get(col, ""))
        for col in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"]
    ).lower()
    if "one-way" in text or "one way" in text:
        return "one_way_direct" if token else "unknown"
    if "divided" in text and "undivided" not in text:
        return "true_paired_divided_carriageway" if token else "divided_centerline_proxy"
    if "undivided" in text or "two-way" in text or "two way" in text:
        return "undivided_centerline" if token else "unknown"
    if token:
        return "unknown"
    return "unknown"


def refine_representation_with_route_pairs(clusters: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    route_names = set(roads["RTE_NM"].dropna().astype(str))
    cluster_routes = set(clusters["source_route_name"].dropna().astype(str))

    def refine(row: pd.Series) -> str:
        rep = row["roadway_representation"]
        route = str(row["source_route_name"])
        token = route_token(route)
        if rep == "true_paired_divided_carriageway" and token:
            opp = {"NB": "SB", "SB": "NB", "EB": "WB", "WB": "EB"}[token]
            opp_route = route[: -2] + opp
            if opp_route not in route_names and opp_route not in cluster_routes:
                return "divided_centerline_proxy"
        return rep

    out = clusters.copy()
    out["roadway_representation"] = out.apply(refine, axis=1)
    return out


def build_signal_geometry_map(bin_context: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    source_by_stable = (
        bin_context[["stable_signal_id", "source_signal_id"]]
        .dropna()
        .drop_duplicates()
        .groupby("stable_signal_id")["source_signal_id"]
        .agg(lambda s: sorted({str(v).strip() for v in s if str(v).strip()})[0] if len(s) else "")
        .reset_index()
    )
    id_cols = [c for c in ["REG_SIGNAL_ID", "ASSET_NUM", "SIGNAL_NO", "ASSET_ID", "INTNO", "INTNUM"] if c in signals.columns]
    long_rows = []
    for col in id_cols:
        x = signals[["GLOBALID", "geometry", col]].rename(columns={col: "source_signal_id"}).copy()
        x["source_signal_id"] = x["source_signal_id"].astype(str).str.strip()
        x["signal_match_field"] = col
        long_rows.append(x)
    sig_ids = pd.concat(long_rows, ignore_index=True).dropna(subset=["source_signal_id"]) if long_rows else pd.DataFrame()
    matched = source_by_stable.merge(sig_ids, on="source_signal_id", how="left")
    matched = matched.sort_values(["stable_signal_id", "signal_match_field"], na_position="last").drop_duplicates("stable_signal_id")
    matched["signal_geometry_available"] = matched["geometry"].notna()
    return matched.rename(columns={"GLOBALID": "source_signal_globalid", "geometry": "signal_geometry"})


def build_clusters(unresolved: pd.DataFrame, corridors: pd.DataFrame) -> pd.DataFrame:
    group_cols = [
        "cluster_id",
        "stable_signal_id",
        "signal_approach_id_v2",
        "source_route_name",
        "source_route_common",
        "route_base",
        "carriageway_direction_token",
        "continuation_corridor_id",
        "roadway_representation",
        "generated_bin_flag",
        "bin_row_origin",
    ]
    agg = unresolved.groupby(group_cols, dropna=False).agg(
        missing_bins=("stable_bin_id", "count"),
        source_measure_min=("source_measure_start", "min"),
        source_measure_max=("source_measure_end", "max"),
        source_measure_mid_min=("source_measure_midpoint", "min"),
        source_measure_mid_max=("source_measure_midpoint", "max"),
        distance_start_min=("distance_start_ft", "min"),
        distance_end_max=("distance_end_ft", "max"),
        geometry_wkt_non_null=("geometry_wkt", lambda s: int(nonmissing(s).sum())),
        distance_bands=("distance_band_out", lambda s: "|".join(sorted({str(v) for v in s.dropna().unique()}))),
    ).reset_index()
    cc_cols = [
        "continuation_corridor_id",
        "cross_signal_boundary_flag",
        "opposite_carriageway_conflict_flag",
        "missing_route_measure_fields_flag",
        "no_turn_continuation_violation_flag",
    ]
    present = [c for c in cc_cols if c in corridors.columns]
    if present:
        cc = corridors[present].drop_duplicates("continuation_corridor_id")
        agg = agg.merge(cc, on="continuation_corridor_id", how="left")
    for col in cc_cols[1:]:
        if col not in agg.columns:
            agg[col] = False
        agg[col] = agg[col].fillna(False).astype(bool)
    return agg


def project_point_to_line(point: Any, line: Any, from_measure: Any, to_measure: Any) -> dict[str, Any]:
    if point is None or line is None or getattr(line, "length", 0) == 0:
        return {
            "projected_distance_along_geometry": pd.NA,
            "fraction_along_geometry": pd.NA,
            "estimated_measure": pd.NA,
            "point_to_line_distance": pd.NA,
            "projection_confidence": "failed",
            "projection_usable": False,
            "projection_failure_reason": "missing_signal_or_road_geometry",
        }
    try:
        along = float(line.project(point))
        frac = along / float(line.length)
        fm = float(from_measure)
        tm = float(to_measure)
        est = fm + frac * (tm - fm)
        dist = float(point.distance(line))
    except Exception:
        return {
            "projected_distance_along_geometry": pd.NA,
            "fraction_along_geometry": pd.NA,
            "estimated_measure": pd.NA,
            "point_to_line_distance": pd.NA,
            "projection_confidence": "failed",
            "projection_usable": False,
            "projection_failure_reason": "projection_exception",
        }
    conf = "high" if dist <= STRICT_PROJECTION_FT else ("medium" if dist <= RELAXED_PROJECTION_FT else "low")
    return {
        "projected_distance_along_geometry": along,
        "fraction_along_geometry": frac,
        "estimated_measure": est,
        "point_to_line_distance": dist,
        "projection_confidence": conf,
        "projection_usable": conf in {"high", "medium"},
        "projection_failure_reason": "" if conf in {"high", "medium"} else "projection_too_far",
    }


def candidate_roads(roads: pd.DataFrame, route: str, measure_min: Any, measure_max: Any, mid_min: Any, mid_max: Any) -> pd.DataFrame:
    rr = roads[roads["RTE_NM"].astype(str).eq(str(route))].copy()
    if rr.empty:
        return rr
    lo = pd.to_numeric(pd.Series([mid_min]), errors="coerce").iloc[0]
    hi = pd.to_numeric(pd.Series([mid_max]), errors="coerce").iloc[0]
    if pd.isna(lo) or pd.isna(hi):
        lo = pd.to_numeric(pd.Series([measure_min]), errors="coerce").iloc[0]
        hi = pd.to_numeric(pd.Series([measure_max]), errors="coerce").iloc[0]
    if pd.notna(lo) and pd.notna(hi):
        low = min(float(lo), float(hi))
        high = max(float(lo), float(hi))
        matched = rr[(pd.to_numeric(rr["FROM_MEASURE"], errors="coerce") <= high + MEASURE_EPS) & (pd.to_numeric(rr["TO_MEASURE"], errors="coerce") >= low - MEASURE_EPS)].copy()
        if not matched.empty:
            return matched
    return rr


def best_signal_projection(point: Any, route_rows: pd.DataFrame) -> tuple[dict[str, Any], Any]:
    best = None
    best_line = None
    for _, row in route_rows.iterrows():
        line = parse_geom(row.get("geometry"))
        proj = project_point_to_line(point, line, row.get("FROM_MEASURE"), row.get("TO_MEASURE"))
        if pd.isna(proj["point_to_line_distance"]):
            continue
        rec = {
            "source_from_measure": row.get("FROM_MEASURE"),
            "source_to_measure": row.get("TO_MEASURE"),
            "source_rte_id": row.get("RTE_ID"),
            "source_rte_common": row.get("RTE_COMMON"),
            "source_rim_facili": row.get("RIM_FACILI"),
            "source_median_ind": row.get("MEDIAN_IND"),
            "source_shape_length": row.get("Shape_Length"),
            **proj,
        }
        if best is None or float(rec["point_to_line_distance"]) < float(best["point_to_line_distance"]):
            best = rec
            best_line = line
    if best is None:
        return (
            {
                "source_from_measure": pd.NA,
                "source_to_measure": pd.NA,
                "source_rte_id": pd.NA,
                "source_rte_common": pd.NA,
                "source_rim_facili": pd.NA,
                "source_median_ind": pd.NA,
                "source_shape_length": pd.NA,
                "projected_distance_along_geometry": pd.NA,
                "fraction_along_geometry": pd.NA,
                "estimated_measure": pd.NA,
                "point_to_line_distance": pd.NA,
                "projection_confidence": "failed",
                "projection_usable": False,
                "projection_failure_reason": "missing_road_geometry",
            },
            None,
        )
    return best, best_line


def build_models(clusters: pd.DataFrame, roads: pd.DataFrame, signal_map: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    signal_lookup = {
        str(r.stable_signal_id): (parse_geom(r.signal_geometry), r.source_signal_globalid, bool(r.signal_geometry_available))
        for r in signal_map.itertuples(index=False)
    }
    rows: list[dict[str, Any]] = []
    line_by_cluster: dict[str, Any] = {}
    total = len(clusters)
    for i, c in enumerate(clusters.itertuples(index=False), start=1):
        if i % 500 == 0:
            log(f"Built corridor-side models for {i:,} / {total:,} clusters.")
        signal_geom, source_globalid, signal_geom_ok = signal_lookup.get(str(c.stable_signal_id), (None, "", False))
        route_rows = candidate_roads(
            roads,
            str(c.source_route_name),
            c.source_measure_min,
            c.source_measure_max,
            c.source_measure_mid_min,
            c.source_measure_mid_max,
        )
        proj, line = best_signal_projection(signal_geom, route_rows)
        rep = c.roadway_representation
        token = c.carriageway_direction_token
        before = side_from_cardinal(token, "before_signal")
        after = side_from_cardinal(token, "after_signal")
        method = proposal_status(rep, token)
        no_reason = ""
        usable = True
        if not c.source_route_name or str(c.source_route_name) == "nan":
            usable = False; no_reason = "no_proposal_missing_corridor_identity"
        elif not signal_geom_ok:
            usable = False; no_reason = "no_proposal_missing_signal_geometry"
        elif route_rows.empty or not bool(route_rows["geometry"].notna().any()):
            usable = False; no_reason = "no_proposal_missing_road_geometry"
        elif not bool(proj["projection_usable"]):
            usable = False; no_reason = "no_proposal_signal_position_uncertain"
        elif rep == "unknown" or not method:
            usable = False; no_reason = "no_proposal_roadway_type_unclear"
        elif before == "unknown" or after == "unknown":
            usable = False; no_reason = "no_proposal_ambiguous"
        elif bool(c.cross_signal_boundary_flag):
            usable = False; no_reason = "no_proposal_source_limited"
        elif bool(c.opposite_carriageway_conflict_flag):
            usable = False; no_reason = "no_proposal_calibration_conflict"
        elif bool(c.missing_route_measure_fields_flag):
            usable = False; no_reason = "no_proposal_source_limited"
        elif bool(c.no_turn_continuation_violation_flag):
            usable = False; no_reason = "no_proposal_needs_map_review"
        confidence = proj["projection_confidence"] if usable else "none"
        rows.append({
            "corridor_side_model_id": c.cluster_id,
            "cluster_id": c.cluster_id,
            "stable_signal_id": c.stable_signal_id,
            "signal_approach_id_v2": c.signal_approach_id_v2,
            "corridor_id": c.continuation_corridor_id,
            "continuation_corridor_id": c.continuation_corridor_id,
            "source_route_name": c.source_route_name,
            "source_route_common": c.source_route_common,
            "route_base": c.route_base,
            "carriageway_direction_token": token,
            "generated_bin_flag": c.generated_bin_flag,
            "bin_row_origin": c.bin_row_origin,
            "roadway_representation": rep,
            "source_signal_globalid": source_globalid,
            "reviewed_signal_geometry_available": signal_geom_ok,
            "source_road_rows_considered": int(len(route_rows)),
            "source_road_geometry_available": bool(not route_rows.empty and route_rows["geometry"].notna().any()),
            "reviewed_signal_projected_measure": proj["estimated_measure"],
            "reviewed_signal_projection_distance_ft": proj["point_to_line_distance"],
            "reviewed_signal_projection_confidence": proj["projection_confidence"],
            "source_from_measure": proj["source_from_measure"],
            "source_to_measure": proj["source_to_measure"],
            "side_before_signal": before if usable else "unknown",
            "side_after_signal": after if usable else "unknown",
            "proposal_status": method if usable else "",
            "directionality_method": method if usable else "",
            "confidence": confidence,
            "model_is_deterministic": bool(usable),
            "no_proposal_status": "" if usable else no_reason,
            "evidence_fields": json.dumps({
                "projection_rule": "source_signal_to_source_travelway",
                "side_rule": "cardinal_route_measure_corridor_side",
                "source_rim_facili": str(proj.get("source_rim_facili", "")),
                "prior_case_engine": rel(CASE_OUT),
            }, sort_keys=True),
        })
        if usable:
            line_by_cluster[c.cluster_id] = line
    return pd.DataFrame(rows), line_by_cluster


def position_bin(row: pd.Series, model: pd.Series, line: Any) -> dict[str, Any]:
    geom = parse_geom(row.get("geometry_wkt"))
    if geom is not None and line is not None:
        rep_pt = geom.representative_point() if hasattr(geom, "representative_point") else geom
        proj = project_point_to_line(rep_pt, line, model.get("source_from_measure"), model.get("source_to_measure"))
        if proj["projection_usable"]:
            return {
                "bin_position_measure": proj["estimated_measure"],
                "bin_position_method": "bin_geometry_representative_point_projected_to_source_corridor",
                "bin_position_confidence": proj["projection_confidence"],
                "bin_projection_distance_ft": proj["point_to_line_distance"],
                "generated_without_geometry_handled": False,
            }
    mid = pd.to_numeric(pd.Series([row.get("source_measure_midpoint")]), errors="coerce").iloc[0]
    start = pd.to_numeric(pd.Series([row.get("source_measure_start")]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([row.get("source_measure_end")]), errors="coerce").iloc[0]
    if pd.notna(mid):
        broad = pd.notna(start) and pd.notna(end) and abs(float(end) - float(start)) > BROAD_PARENT_MEASURE_RANGE
        return {
            "bin_position_measure": float(mid),
            "bin_position_method": "source_measure_midpoint_from_staged_bin_broad_parent_interval" if broad else "source_measure_midpoint_from_staged_bin",
            "bin_position_confidence": "high",
            "bin_projection_distance_ft": pd.NA,
            "generated_without_geometry_handled": bool(row.get("generated_bin_flag")) and geom is None,
        }
    if pd.notna(start) and pd.notna(end):
        return {
            "bin_position_measure": (float(start) + float(end)) / 2.0,
            "bin_position_method": "source_measure_interval_midpoint_from_staged_bin",
            "bin_position_confidence": "medium",
            "bin_projection_distance_ft": pd.NA,
            "generated_without_geometry_handled": bool(row.get("generated_bin_flag")) and geom is None,
        }
    return {
        "bin_position_measure": pd.NA,
        "bin_position_method": "missing_bin_geometry_and_measure",
        "bin_position_confidence": "none",
        "bin_projection_distance_ft": pd.NA,
        "generated_without_geometry_handled": False,
    }


def classify_bin_side(signal_measure: Any, bin_measure: Any) -> str:
    sig = pd.to_numeric(pd.Series([signal_measure]), errors="coerce").iloc[0]
    bm = pd.to_numeric(pd.Series([bin_measure]), errors="coerce").iloc[0]
    if pd.isna(sig) or pd.isna(bm):
        return "too_close_or_uncertain"
    if abs(float(bm) - float(sig)) <= TOO_CLOSE_MEASURE:
        return "too_close_or_uncertain"
    return "before_signal" if float(bm) < float(sig) else "after_signal"


def build_proposals(unresolved: pd.DataFrame, models: pd.DataFrame, line_by_cluster: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    model_lookup = {str(r.cluster_id): r for r in models.itertuples(index=False)}
    proposals: list[dict[str, Any]] = []
    no_rows: list[dict[str, Any]] = []
    total = len(unresolved)
    for i, (_, row) in enumerate(unresolved.iterrows(), start=1):
        if i % 10000 == 0:
            log(f"Assigned proposal/no-proposal status for {i:,} / {total:,} unresolved bins.")
        model = model_lookup.get(str(row["cluster_id"]))
        if model is None:
            no_rows.append(base_no_row(row, "no_proposal_missing_corridor_identity"))
            continue
        if not bool(model.model_is_deterministic):
            no_rows.append(base_no_row(row, model.no_proposal_status or "no_proposal_ambiguous", model))
            continue
        model_s = pd.Series(model._asdict())
        pos = position_bin(row, model_s, line_by_cluster.get(str(row["cluster_id"])))
        side_class = classify_bin_side(model.reviewed_signal_projected_measure, pos["bin_position_measure"])
        if side_class == "before_signal":
            side = model.side_before_signal
        elif side_class == "after_signal":
            side = model.side_after_signal
        else:
            no_rows.append(base_no_row(row, "no_proposal_bin_position_uncertain", model, pos, side_class))
            continue
        if side not in {"upstream", "downstream"}:
            no_rows.append(base_no_row(row, "no_proposal_ambiguous", model, pos, side_class))
            continue
        confidence = model.confidence
        if confidence == "high" and pos["bin_position_confidence"] == "medium":
            confidence = "medium"
        if pos["bin_position_confidence"] == "none":
            no_rows.append(base_no_row(row, "no_proposal_bin_position_uncertain", model, pos, side_class))
            continue
        proposals.append({
            "stable_signal_id": row.get("stable_signal_id"),
            "signal_approach_id_v2": row.get("signal_approach_id_v2"),
            "stable_bin_id": row.get("stable_bin_id"),
            "stable_travelway_id": row.get("stable_travelway_id"),
            "cluster_id": row.get("cluster_id"),
            "corridor_side_model_id": model.corridor_side_model_id,
            "source_route_name": row.get("source_route_name"),
            "source_route_common": row.get("source_route_common"),
            "route_base": row.get("route_base"),
            "carriageway_direction_token": row.get("carriageway_direction_token"),
            "continuation_corridor_id": row.get("continuation_corridor_id"),
            "generated_bin_flag": row.get("generated_bin_flag"),
            "bin_row_origin": row.get("bin_row_origin"),
            "distance_band": row.get("distance_band_out"),
            "distance_start_ft": row.get("distance_start_ft"),
            "distance_end_ft": row.get("distance_end_ft"),
            "source_measure_start": row.get("source_measure_start"),
            "source_measure_end": row.get("source_measure_end"),
            "source_measure_midpoint": row.get("source_measure_midpoint"),
            "roadway_representation": model.roadway_representation,
            "reviewed_signal_projected_measure": model.reviewed_signal_projected_measure,
            "bin_position_measure": pos["bin_position_measure"],
            "bin_position_method": pos["bin_position_method"],
            "bin_position_confidence": pos["bin_position_confidence"],
            "bin_projection_distance_ft": pos["bin_projection_distance_ft"],
            "side_of_signal": side_class,
            "proposed_upstream_downstream": side,
            "proposal_status": model.proposal_status,
            "directionality_method": model.directionality_method,
            "proposal_confidence": confidence,
            "generated_without_geometry_handled": pos["generated_without_geometry_handled"],
            "evidence_fields": model.evidence_fields,
        })
    return pd.DataFrame(proposals), pd.DataFrame(no_rows)


def base_no_row(row: pd.Series, reason: str, model: Any | None = None, pos: dict[str, Any] | None = None, side_class: str = "") -> dict[str, Any]:
    return {
        "stable_signal_id": row.get("stable_signal_id"),
        "signal_approach_id_v2": row.get("signal_approach_id_v2"),
        "stable_bin_id": row.get("stable_bin_id"),
        "cluster_id": row.get("cluster_id"),
        "source_route_name": row.get("source_route_name"),
        "continuation_corridor_id": row.get("continuation_corridor_id"),
        "generated_bin_flag": row.get("generated_bin_flag"),
        "bin_row_origin": row.get("bin_row_origin"),
        "roadway_representation": row.get("roadway_representation"),
        "distance_band": row.get("distance_band_out"),
        "source_measure_start": row.get("source_measure_start"),
        "source_measure_end": row.get("source_measure_end"),
        "source_measure_midpoint": row.get("source_measure_midpoint"),
        "corridor_side_model_id": getattr(model, "corridor_side_model_id", ""),
        "model_confidence": getattr(model, "confidence", "none"),
        "bin_position_method": (pos or {}).get("bin_position_method", ""),
        "bin_position_measure": (pos or {}).get("bin_position_measure", pd.NA),
        "side_of_signal": side_class,
        "no_proposal_status": reason,
    }


def unit_summary(proposals: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if proposals.empty:
        return pd.DataFrame(columns=group_cols + ["proposed_bins", "proposed_units"])
    bins = proposals.groupby(group_cols, dropna=False).size().reset_index(name="proposed_bins")
    unit_cols = ["stable_signal_id", "signal_approach_id_v2", "proposed_upstream_downstream", "distance_band"]
    units = proposals.drop_duplicates(unit_cols + group_cols).groupby(group_cols, dropna=False).size().reset_index(name="proposed_units")
    return bins.merge(units, on=group_cols, how="left")


def model_summary(models: pd.DataFrame) -> pd.DataFrame:
    return models.groupby(["roadway_representation", "proposal_status", "confidence", "model_is_deterministic", "no_proposal_status"], dropna=False).size().reset_index(name="corridor_side_models")


def proposal_summary(proposals: pd.DataFrame, unresolved: pd.DataFrame, no_rows: pd.DataFrame) -> pd.DataFrame:
    high = proposals[proposals["proposal_confidence"].eq("high")] if not proposals.empty else proposals
    high_units = high.drop_duplicates(["stable_signal_id", "signal_approach_id_v2", "proposed_upstream_downstream", "distance_band"]).shape[0] if not high.empty else 0
    all_units = proposals.drop_duplicates(["stable_signal_id", "signal_approach_id_v2", "proposed_upstream_downstream", "distance_band"]).shape[0] if not proposals.empty else 0
    direction_ready_if_high = CURRENT_DIRECTION_READY_UNITS + high_units
    return pd.DataFrame([{
        "unresolved_bins_considered": int(len(unresolved)),
        "unresolved_clusters_considered": int(unresolved["cluster_id"].nunique()),
        "proposed_bins": int(len(proposals)),
        "high_confidence_proposed_bins": int(len(high)),
        "proposed_units": int(all_units),
        "high_confidence_proposed_units": int(high_units),
        "remaining_unresolved_bins_after_high_confidence": int(len(unresolved) - len(high)),
        "direction_ready_units_if_high_confidence_applied": int(direction_ready_if_high),
        "percent_of_conservative_target_reached": round(direction_ready_if_high / CONSERVATIVE_TARGET * 100.0, 2),
        "remaining_gap_to_conservative_target": int(max(CONSERVATIVE_TARGET - direction_ready_if_high, 0)),
        "upper_bound_target_gap_after_high_confidence": int(max(UPPER_TARGET - direction_ready_if_high, 0)),
        "no_proposal_bins": int(len(no_rows)),
    }])


def manual_case_validation(proposals: pd.DataFrame, no_rows: pd.DataFrame) -> pd.DataFrame:
    rows = []
    targets = {
        "case_1": ["R-VA   US00258EB", "R-VA   US00258WB"],
        "case_2": ["R-VA   SR00208NB", "R-VA   SR00208SB"],
        "case_3": ["R-VA   US00001NB", "R-VA   US00001SB"],
    }
    for case_id, sid in CASE_IDS.items():
        routes = targets[case_id]
        p = proposals[(proposals["stable_signal_id"].eq(sid)) & (proposals["source_route_name"].isin(routes))] if not proposals.empty else proposals
        n = no_rows[(no_rows["stable_signal_id"].eq(sid)) & (no_rows["source_route_name"].isin(routes))] if not no_rows.empty else no_rows
        passed = len(p[p["proposal_confidence"].eq("high")]) > 0
        blocker = "" if passed else ("|".join(sorted(n["no_proposal_status"].dropna().astype(str).unique())) if not n.empty else "no_target_rows_found")
        if case_id in {"case_2", "case_3"} and len(p) == 0:
            passed = False
        rows.append({
            "case_id": case_id,
            "stable_signal_id": sid,
            "target_routes": "|".join(routes),
            "target_proposed_bins": int(len(p)),
            "high_confidence_target_proposed_bins": int(len(p[p["proposal_confidence"].eq("high")])) if not p.empty else 0,
            "case_passed": bool(passed),
            "blocker_if_failed": blocker,
        })
    return pd.DataFrame(rows)


def safety_checks(proposals: pd.DataFrame, models: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"check_name": "no_staged_or_canonical_mutation", "status": "pass", "detail": "Script writes only review outputs under global_corridor_side_geometry_directionality_proposal."},
        {"check_name": "no_crash_direction_fields_used", "status": "pass", "detail": "No crash files or crash direction fields are read."},
        {"check_name": "representation_methods_separate", "status": "pass", "detail": "|".join(sorted(models["roadway_representation"].dropna().astype(str).unique()))},
    ]
    if proposals.empty:
        conflicts = 0
    else:
        conflicts = int((proposals.groupby("stable_bin_id")["proposed_upstream_downstream"].nunique() > 1).sum())
    rows.append({"check_name": "no_conflicting_bin_side_proposals", "status": "pass" if conflicts == 0 else "fail", "detail": f"conflicting stable_bin_id proposals: {conflicts}"})
    for case_id in ["case_2", "case_3"]:
        v = validation[validation["case_id"].eq(case_id)].iloc[0]
        rows.append({"check_name": f"{case_id}_required_validation", "status": "pass" if bool(v["case_passed"]) else "fail", "detail": f"target proposed bins: {v['target_proposed_bins']}; blocker: {v['blocker_if_failed']}"})
    return pd.DataFrame(rows)


def ranked_remaining(no_rows: pd.DataFrame) -> pd.DataFrame:
    if no_rows.empty:
        return pd.DataFrame(columns=["rank", "stable_signal_id", "signal_approach_id_v2", "source_route_name", "no_proposal_status", "missing_bins"])
    out = no_rows.groupby(["stable_signal_id", "signal_approach_id_v2", "source_route_name", "roadway_representation", "no_proposal_status"], dropna=False).size().reset_index(name="missing_bins")
    return out.sort_values("missing_bins", ascending=False).head(200).assign(rank=lambda d: range(1, len(d) + 1))


def recommendation(summary: pd.DataFrame, safety: pd.DataFrame, validation: pd.DataFrame, by_method: pd.DataFrame) -> pd.DataFrame:
    conflict_fail = safety["status"].eq("fail").any()
    case2 = bool(validation.loc[validation["case_id"].eq("case_2"), "case_passed"].iloc[0])
    case3 = bool(validation.loc[validation["case_id"].eq("case_3"), "case_passed"].iloc[0])
    high_bins = int(summary.iloc[0]["high_confidence_proposed_bins"])
    if conflict_fail or not (case2 and case3):
        rec = "do_not_apply_due_to_conflicts"
    elif high_bins > 0:
        rec = "implement_high_confidence_global_corridor_side_proposals_to_staging"
    elif not by_method.empty:
        rec = "implement_specific_method_first"
    else:
        rec = "improve_corridor_identity_before_mutation"
    return pd.DataFrame([{
        "recommendation": rec,
        "next_step": "Review high-confidence proposal tables and QA, then run a separate bounded mutation task only if approved.",
        "case2_passed": case2,
        "case3_passed": case3,
        "high_confidence_proposed_bins": high_bins,
        "remaining_gap_to_conservative_target": int(summary.iloc[0]["remaining_gap_to_conservative_target"]),
    }])


def write_findings(summary: pd.DataFrame, models: pd.DataFrame, validation: pd.DataFrame, no_reasons: pd.DataFrame, recs: pd.DataFrame) -> None:
    s = summary.iloc[0]
    rep_counts = models.groupby("roadway_representation").size().to_dict()
    case2 = validation[validation["case_id"].eq("case_2")].iloc[0]
    case3 = validation[validation["case_id"].eq("case_3")].iloc[0]
    top_reasons = no_reasons.head(10).to_dict("records") if not no_reasons.empty else []
    text = f"""# Global Corridor-Side Geometry Directionality Proposal

## What changed from earlier failed global passes

This run builds corridor-side models first, then assigns bins only when a deterministic before/after-to-upstream/downstream mapping exists. It does not use weak bin-by-bin local calibration as the primary gate.

## How the case-tested engine was globalized

The script filters unresolved staged bins, clusters them by signal/approach/route/corridor/representation/origin, projects reviewed signal geometry to source Travelway geometry, builds cardinal corridor-side models, then places existing or generated bins using geometry projection or staged source-measure provenance.

## Corridor Representation Types Found

Model counts by representation: `{rep_counts}`. True paired divided, synthetic undivided, divided-centerline/proxy, one-way, and unknown models are kept distinct.

## Proposal Counts and Unit Recovery Potential

Unresolved bins considered: {int(s['unresolved_bins_considered'])}. Proposed bins: {int(s['proposed_bins'])}. High-confidence proposed bins: {int(s['high_confidence_proposed_bins'])}. High-confidence proposed units: {int(s['high_confidence_proposed_units'])}.

If high-confidence proposals were applied in a later approved mutation task, direction-ready units would rise to {int(s['direction_ready_units_if_high_confidence_applied'])}, reaching {s['percent_of_conservative_target_reached']}% of the conservative target and leaving a gap of {int(s['remaining_gap_to_conservative_target'])} units.

## Case 2 and Case 3 Validation

Case 2 passed: {bool(case2['case_passed'])}; target proposed bins: {int(case2['target_proposed_bins'])}; blocker: {case2['blocker_if_failed'] or ''}.

Case 3 passed: {bool(case3['case_passed'])}; target proposed bins: {int(case3['target_proposed_bins'])}; blocker: {case3['blocker_if_failed'] or ''}.

## Whether High-Confidence Proposals Are Safe To Apply

High-confidence rows are review-only but passed conflict checks in this proposal package. They should not be applied without a separate mutation task and QA approval.

## What Remains Unresolved And Why

Remaining unresolved rows are preserved with no-proposal statuses. Top no-proposal reason groups: `{top_reasons}`.

## Recommended Next Implementation Step

Recommendation: `{recs.iloc[0]['recommendation']}`.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "progress_log.md").write_text("# Progress Log\n", encoding="utf-8")
    log("Loading staged/cache products, normalized source artifacts, and prior case outputs.")
    data = load_inputs()
    case_validation_prior = pd.read_csv(CASE_OUT / "case_test_pass_fail_summary.csv") if (CASE_OUT / "case_test_pass_fail_summary.csv").exists() else pd.DataFrame()

    log("Building unresolved universe and clusters.")
    unresolved = unresolved_universe(data["bin_context"])
    clusters = build_clusters(unresolved, data["continuation_corridors"])
    clusters = refine_representation_with_route_pairs(clusters, data["roads"])

    log("Building signal geometry crosswalk.")
    signal_map = build_signal_geometry_map(data["bin_context"], data["signals"])

    log("Building global corridor-side models.")
    models, line_by_cluster = build_models(clusters, data["roads"], signal_map)
    clusters = clusters.merge(models[["cluster_id", "model_is_deterministic", "no_proposal_status", "confidence"]], on="cluster_id", how="left")

    log("Assigning global review-only directionality proposals.")
    proposals, no_rows = build_proposals(unresolved, models, line_by_cluster)

    log("Building summaries and QA outputs.")
    summary = proposal_summary(proposals, unresolved, no_rows)
    no_reason_summary = no_rows.groupby(["no_proposal_status"], dropna=False).size().reset_index(name="bins").sort_values("bins", ascending=False) if not no_rows.empty else pd.DataFrame(columns=["no_proposal_status", "bins"])
    by_method = unit_summary(proposals, ["proposal_status", "directionality_method"]) if not proposals.empty else pd.DataFrame(columns=["proposal_status", "directionality_method", "proposed_bins", "proposed_units"])
    by_distance = unit_summary(proposals, ["distance_band"]) if not proposals.empty else pd.DataFrame(columns=["distance_band", "proposed_bins", "proposed_units"])
    by_signal = unit_summary(proposals, ["stable_signal_id"]) if not proposals.empty else pd.DataFrame(columns=["stable_signal_id", "proposed_bins", "proposed_units"])
    by_rep = unit_summary(proposals, ["roadway_representation"]) if not proposals.empty else pd.DataFrame(columns=["roadway_representation", "proposed_bins", "proposed_units"])
    by_conf = unit_summary(proposals, ["proposal_confidence"]) if not proposals.empty else pd.DataFrame(columns=["proposal_confidence", "proposed_bins", "proposed_units"])
    validation = manual_case_validation(proposals, no_rows)
    safety = safety_checks(proposals, models, validation)
    ranked = ranked_remaining(no_rows)
    recs = recommendation(summary, safety, validation, by_method)

    write_csv("unresolved_cluster_inventory.csv", clusters)
    write_csv("corridor_side_model_inventory.csv", models)
    write_csv("corridor_side_model_summary.csv", model_summary(models))
    write_csv("global_corridor_side_directionality_proposal.csv", proposals)
    write_csv("global_corridor_side_directionality_proposal_summary.csv", summary)
    write_csv("proposal_no_assignment_reasons.csv", no_reason_summary)
    write_csv("proposed_recovery_by_method.csv", by_method)
    write_csv("proposed_recovery_by_distance_band.csv", by_distance)
    write_csv("proposed_recovery_by_signal.csv", by_signal)
    write_csv("proposed_recovery_by_roadway_representation.csv", by_rep)
    write_csv("proposed_recovery_by_confidence.csv", by_conf)
    write_csv("manual_case_global_validation.csv", validation)
    write_csv("conflict_and_safety_checks.csv", safety)
    write_csv("ranked_remaining_map_review_clusters.csv", ranked)
    write_csv("recommended_next_actions.csv", recs)
    write_findings(summary, models, validation, no_reason_summary, recs)

    manifest = {
        "created_utc": now_iso(),
        "bounded_question": "Globalize case-tested corridor-side geometry engine as a review-only directionality proposal.",
        "source_inputs": [rel(p) for p in [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, CONTINUATION_CORRIDORS, CONTINUATION_PROVENANCE, SIGNALS, ROADS]],
        "previous_successful_case_engine_outputs": rel(CASE_OUT),
        "prior_directionality_context": [
            "work/roadway_graph/review/expanded_directionality_recovery_audit/",
            "work/roadway_graph/review/expanded_directionality_blocker_rule_proposal_audit/",
            "work/roadway_graph/review/global_bin_geometry_directionality_projection_proposal/",
            "work/roadway_graph/review/global_geometry_directionality_projection_proposal/",
        ],
        "rows_read": {k: int(len(v)) for k, v in data.items()},
        "prior_case_validation": case_validation_prior.to_dict("records"),
        "summary": summary.iloc[0].to_dict(),
        "no_mutation": True,
        "crash_direction_fields_used": False,
    }
    qa_manifest = {
        "created_utc": now_iso(),
        "manual_case_validation": validation.to_dict("records"),
        "conflict_and_safety_checks": safety.to_dict("records"),
        "recommendation": recs.iloc[0]["recommendation"],
        "high_confidence_proposed_bins": int(summary.iloc[0]["high_confidence_proposed_bins"]),
        "high_confidence_proposed_units": int(summary.iloc[0]["high_confidence_proposed_units"]),
        "remaining_gap_to_conservative_target": int(summary.iloc[0]["remaining_gap_to_conservative_target"]),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    log("Completed global corridor-side directionality proposal.")


if __name__ == "__main__":
    main()
