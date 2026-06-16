"""Build source-signal to Travelway projection and corridor indexes.

This is an intermediate staged/cache support task. It projects normalized HMMS
signal points, including source-only endpoint signals, to normalized Travelway
rows and builds signal-bounded corridor intervals around stable analysis
signals. It does not assign upstream/downstream and does not mutate staged
bin_context or canonical products.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from shapely import wkb
    from shapely.strtree import STRtree
except Exception:  # pragma: no cover
    wkb = None
    STRtree = None


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
REVIEW_OUT = REPO_ROOT / "work/roadway_graph/review/source_signal_travelway_projection_index"
ARTIFACTS = REPO_ROOT / "artifacts/normalized"
CASE_OUT = REPO_ROOT / "work/roadway_graph/review/corridor_side_geometry_engine_case_tests"
GLOBAL_OUT = REPO_ROOT / "work/roadway_graph/review/global_corridor_side_geometry_directionality_proposal"

SIGNALS = ARTIFACTS / "signals.parquet"
ROADS = ARTIFACTS / "roads.parquet"
BIN_CONTEXT = STAGING / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
CONTINUATION_CORRIDORS = STAGING / "continuation_corridors.parquet"

PROJECTION_INDEX = STAGING / "source_signal_travelway_projection_index.parquet"
CORRIDOR_INDEX = STAGING / "signal_bounded_travelway_corridor_index.parquet"

SEARCH_RADIUS_FT = 300.0
FAILED_NEAREST_RADIUS_FT = 1000.0
HIGH_CONFIDENCE_FT = 100.0
MEDIUM_CONFIDENCE_FT = 300.0
MAX_CANDIDATES_PER_SIGNAL = 40
CORRIDOR_CUTOFF_MI = 2500.0 / 5280.0
MEASURE_EPS = 1.0e-7

CASE_TESTS = {
    "case_2": {
        "stable_signal_id": "sig_05a2cb689cbc4f27814d",
        "reviewed_globalid": "{9000F2BF-82ED-4794-A473-6238A81A4109}",
        "routes": ["R-VA   SR00208NB", "R-VA   SR00208SB"],
        "endpoints": ["{307C6C57-B13A-4EFD-946D-10335A09E755}", "{A6F2E5C6-29EE-4BBF-866E-8E4507E3FFB8}"],
        "requires_source_only_endpoint": False,
    },
    "case_3": {
        "stable_signal_id": "sig_439930214d7b1b49426f",
        "reviewed_globalid": "{275B403F-F8D7-44B7-9D2F-04875799C1FB}",
        "routes": ["R-VA   US00001SB", "R-VA   US00001NB"],
        "endpoints": ["{B78AFE2F-0550-41D3-B4D8-AEB06826C742}", "{E0FE127C-C5E8-428B-90E7-985CE9934776}"],
        "requires_source_only_endpoint": True,
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def log(message: str) -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    with (REVIEW_OUT / "progress_log.md").open("a", encoding="utf-8") as f:
        f.write(f"- {now_iso()} - {message}\n")


def write_csv(name: str, df: pd.DataFrame) -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(REVIEW_OUT / name, index=False)


def nonmissing(s: pd.Series) -> pd.Series:
    text = s.astype("string").str.strip()
    return s.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>"])


def parse_geom(value: Any):
    if value is None or pd.isna(value) or wkb is None:
        return None
    if hasattr(value, "geom_type"):
        return value
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return wkb.loads(bytes(value))
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


def norm_globalid(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip().upper()


def stable_hash(prefix: str, values: list[Any]) -> str:
    text = "|".join("" if pd.isna(v) else str(v) for v in values)
    return f"{prefix}_{hashlib.sha1(text.encode('utf-8')).hexdigest()[:20]}"


def confidence(distance_ft: Any) -> tuple[str, bool, str]:
    if pd.isna(distance_ft):
        return "failed", False, "missing_projection"
    dist = float(distance_ft)
    if dist <= HIGH_CONFIDENCE_FT:
        return "high", True, ""
    if dist <= MEDIUM_CONFIDENCE_FT:
        return "medium", True, ""
    return "low", False, "projection_too_far"


def side_values(df: pd.DataFrame) -> pd.Series:
    side = df["upstream_downstream"] if "upstream_downstream" in df.columns else pd.Series(pd.NA, index=df.index)
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonmissing(side), df["upstream_downstream_values"])
    return side


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
        "distance_band",
        "distance_band_v2",
        "signal_approach_id_v2",
        "continuation_corridor_id",
        "bin_row_origin",
        "generated_bin_flag",
        "upstream_downstream_values",
        "upstream_downstream",
        "directionality_status",
        "directionality_recovery_status",
    ]
    available = pd.read_parquet(BIN_CONTEXT, columns=None).columns
    return {
        "signals": pd.read_parquet(SIGNALS),
        "roads": pd.read_parquet(
            ROADS,
            columns=[
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
            ],
        ),
        "bin_context": pd.read_parquet(BIN_CONTEXT, columns=[c for c in bin_cols if c in available]),
        "signal_approaches": pd.read_parquet(SIGNAL_APPROACHES),
        "continuation_corridors": pd.read_parquet(CONTINUATION_CORRIDORS),
        "case_crosswalk": pd.read_csv(CASE_OUT / "signal_boundary_crosswalk.csv") if (CASE_OUT / "signal_boundary_crosswalk.csv").exists() else pd.DataFrame(),
        "global_validation": pd.read_csv(GLOBAL_OUT / "manual_case_global_validation.csv") if (GLOBAL_OUT / "manual_case_global_validation.csv").exists() else pd.DataFrame(),
    }


def validate_required_fields(signals: pd.DataFrame, roads: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    checks = [
        ("source_globalid_identified", "GLOBALID" in signals.columns, "signals.GLOBALID"),
        ("signal_geometry_available", "geometry" in signals.columns and signals["geometry"].notna().any(), "signals.geometry"),
        ("road_route_name_available", "RTE_NM" in roads.columns, "roads.RTE_NM"),
        ("road_measure_fields_available", {"FROM_MEASURE", "TO_MEASURE"}.issubset(roads.columns), "roads FROM/TO measure"),
        ("road_geometry_available", "geometry" in roads.columns and roads["geometry"].notna().any(), "roads.geometry"),
    ]
    for name, ok, detail in checks:
        rows.append({"qa_gate": name, "status": "pass" if ok else "fail", "detail": detail})
    return rows


def build_signal_identity(signals: pd.DataFrame, bin_context: pd.DataFrame, case_crosswalk: pd.DataFrame) -> pd.DataFrame:
    out = signals.copy()
    out["source_signal_globalid"] = out["GLOBALID"].astype(str)
    out["_globalid_norm"] = out["GLOBALID"].map(norm_globalid)

    source_map = bin_context[["source_signal_id", "stable_signal_id"]].dropna().drop_duplicates().copy()
    source_map["source_signal_id"] = source_map["source_signal_id"].astype(str).str.strip()
    id_cols = [c for c in ["REG_SIGNAL_ID", "ASSET_NUM", "SIGNAL_NO", "ASSET_ID", "INTNO", "INTNUM"] if c in signals.columns]
    long_ids = []
    for col in id_cols:
        x = signals[["GLOBALID", col]].rename(columns={col: "source_signal_id"}).copy()
        x["source_signal_id"] = x["source_signal_id"].astype(str).str.strip()
        x = x[x["source_signal_id"].ne("") & x["source_signal_id"].ne("nan")]
        x["signal_match_field"] = col
        long_ids.append(x)
    if long_ids:
        ids = pd.concat(long_ids, ignore_index=True)
        matched = ids.merge(source_map, on="source_signal_id", how="inner")
        stable_by_global = matched.groupby("GLOBALID").agg(
            stable_signal_id=("stable_signal_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
            stable_signal_id_count=("stable_signal_id", lambda s: len(set(s.dropna().astype(str)))),
            signal_identifier_values=("source_signal_id", lambda s: "|".join(sorted(set(s.dropna().astype(str))))),
        ).reset_index()
        out = out.merge(stable_by_global, on="GLOBALID", how="left")
    else:
        out["stable_signal_id"] = pd.NA
        out["stable_signal_id_count"] = 0
        out["signal_identifier_values"] = ""

    if not case_crosswalk.empty:
        case_map = case_crosswalk[["source_globalid", "stable_signal_id"]].copy()
        case_map["_globalid_norm"] = case_map["source_globalid"].map(norm_globalid)
        case_map = case_map[nonmissing(case_map["stable_signal_id"])].drop_duplicates("_globalid_norm")
        out = out.merge(case_map[["_globalid_norm", "stable_signal_id"]].rename(columns={"stable_signal_id": "case_stable_signal_id"}), on="_globalid_norm", how="left")
        out["stable_signal_id"] = out["stable_signal_id"].where(nonmissing(out["stable_signal_id"]), out["case_stable_signal_id"])
    else:
        out["case_stable_signal_id"] = pd.NA

    out["stable_signal_id_count"] = pd.to_numeric(out.get("stable_signal_id_count", 0), errors="coerce").fillna(0).astype(int)
    out["signal_role_hint"] = out["stable_signal_id"].where(nonmissing(out["stable_signal_id"]), "").map(lambda s: "analysis_signal" if str(s).strip() else "source_only_signal")
    out["geometry_available"] = out["geometry"].notna()
    return out


def prepare_roads(roads: pd.DataFrame) -> pd.DataFrame:
    out = roads.copy().reset_index(drop=False).rename(columns={"index": "road_source_row_index"})
    out["road_row_id"] = out.apply(lambda r: stable_hash("roadrow", [r["road_source_row_index"], r.get("RTE_NM"), r.get("FROM_MEASURE"), r.get("TO_MEASURE")]), axis=1)
    out["route_name"] = out["RTE_NM"].astype(str)
    out["route_base"] = out["route_name"].map(route_base)
    out["carriageway_direction_token"] = out["route_name"].map(route_token)
    out["road_geometry_object"] = out["geometry"].map(parse_geom)
    out["road_geometry_available"] = out["road_geometry_object"].notna()
    return out


def project_signal_to_road(point: Any, road: pd.Series) -> dict[str, Any]:
    line = road.get("road_geometry_object")
    if point is None or line is None or getattr(line, "length", 0) == 0:
        return {
            "projected_distance_along_geometry": pd.NA,
            "projected_fraction": pd.NA,
            "estimated_measure": pd.NA,
            "point_to_line_distance_ft": pd.NA,
            "projection_confidence": "failed",
            "usable_as_corridor_boundary": False,
            "no_projection_reason": "missing_signal_or_road_geometry",
        }
    try:
        along = float(line.project(point))
        frac = along / float(line.length)
        fm = float(road["FROM_MEASURE"])
        tm = float(road["TO_MEASURE"])
        est = fm + frac * (tm - fm)
        dist = float(point.distance(line))
    except Exception:
        return {
            "projected_distance_along_geometry": pd.NA,
            "projected_fraction": pd.NA,
            "estimated_measure": pd.NA,
            "point_to_line_distance_ft": pd.NA,
            "projection_confidence": "failed",
            "usable_as_corridor_boundary": False,
            "no_projection_reason": "projection_exception",
        }
    conf, usable, reason = confidence(dist)
    return {
        "projected_distance_along_geometry": along,
        "projected_fraction": frac,
        "estimated_measure": est,
        "point_to_line_distance_ft": dist,
        "projection_confidence": conf,
        "usable_as_corridor_boundary": usable,
        "no_projection_reason": reason,
    }


def build_projection_index(signals: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    if STRtree is None:
        raise RuntimeError("Shapely STRtree is unavailable; cannot build projection index.")
    road_geoms = roads.loc[roads["road_geometry_available"], "road_geometry_object"].tolist()
    road_indices = roads.loc[roads["road_geometry_available"]].index.to_list()
    tree = STRtree(road_geoms)
    records = []
    total = len(signals)
    for i, (_, sig) in enumerate(signals.iterrows(), start=1):
        if i % 500 == 0:
            log(f"Projected {i:,} / {total:,} source signals.")
        point = parse_geom(sig.get("geometry"))
        base = {
            "source_signal_globalid": sig.get("source_signal_globalid"),
            "stable_signal_id": sig.get("stable_signal_id"),
            "signal_role_hint": sig.get("signal_role_hint"),
            "signal_identifier_values": sig.get("signal_identifier_values", ""),
            "signal_geometry_available": bool(sig.get("geometry_available")),
        }
        if point is None:
            records.append({
                **base,
                "road_row_id": pd.NA,
                "road_source_row_index": pd.NA,
                "route_name": pd.NA,
                "route_base": pd.NA,
                "carriageway_direction_token": pd.NA,
                "from_measure": pd.NA,
                "to_measure": pd.NA,
                "road_rte_id": pd.NA,
                "road_rte_common": pd.NA,
                "roadway_configuration": pd.NA,
                "projected_distance_along_geometry": pd.NA,
                "projected_fraction": pd.NA,
                "estimated_measure": pd.NA,
                "point_to_line_distance_ft": pd.NA,
                "projection_confidence": "failed",
                "candidate_rank_for_signal": pd.NA,
                "candidate_rank_for_route": pd.NA,
                "usable_as_corridor_boundary": False,
                "no_projection_reason": "missing_signal_geometry",
            })
            continue
        candidate_tree_idxs = list(tree.query(point.buffer(SEARCH_RADIUS_FT)))
        if not candidate_tree_idxs:
            nearest_idx = tree.nearest(point)
            candidate_tree_idxs = [int(nearest_idx)] if nearest_idx is not None else []
        candidates = []
        for tree_idx in candidate_tree_idxs:
            road_idx = road_indices[int(tree_idx)]
            road = roads.loc[road_idx]
            proj = project_signal_to_road(point, road)
            if pd.isna(proj["point_to_line_distance_ft"]):
                continue
            dist = float(proj["point_to_line_distance_ft"])
            if dist <= SEARCH_RADIUS_FT or (len(candidate_tree_idxs) == 1 and dist <= FAILED_NEAREST_RADIUS_FT):
                candidates.append((dist, road_idx, proj))
        if not candidates:
            records.append({
                **base,
                "road_row_id": pd.NA,
                "road_source_row_index": pd.NA,
                "route_name": pd.NA,
                "route_base": pd.NA,
                "carriageway_direction_token": pd.NA,
                "from_measure": pd.NA,
                "to_measure": pd.NA,
                "road_rte_id": pd.NA,
                "road_rte_common": pd.NA,
                "roadway_configuration": pd.NA,
                "projected_distance_along_geometry": pd.NA,
                "projected_fraction": pd.NA,
                "estimated_measure": pd.NA,
                "point_to_line_distance_ft": pd.NA,
                "projection_confidence": "failed",
                "candidate_rank_for_signal": pd.NA,
                "candidate_rank_for_route": pd.NA,
                "usable_as_corridor_boundary": False,
                "no_projection_reason": "no_road_candidate_within_search_radius",
            })
            continue
        candidates = sorted(candidates, key=lambda x: x[0])[:MAX_CANDIDATES_PER_SIGNAL]
        route_counts: dict[str, int] = {}
        for rank, (_, road_idx, proj) in enumerate(candidates, start=1):
            road = roads.loc[road_idx]
            route = str(road.get("route_name"))
            route_counts[route] = route_counts.get(route, 0) + 1
            records.append({
                **base,
                "road_row_id": road.get("road_row_id"),
                "road_source_row_index": road.get("road_source_row_index"),
                "route_name": route,
                "route_base": road.get("route_base"),
                "carriageway_direction_token": road.get("carriageway_direction_token"),
                "from_measure": road.get("FROM_MEASURE"),
                "to_measure": road.get("TO_MEASURE"),
                "road_rte_id": road.get("RTE_ID"),
                "road_rte_common": road.get("RTE_COMMON"),
                "roadway_configuration": road.get("RIM_FACILI"),
                **proj,
                "candidate_rank_for_signal": rank,
                "candidate_rank_for_route": route_counts[route],
            })
    return pd.DataFrame(records)


def modal_approach_map(bin_context: pd.DataFrame) -> pd.DataFrame:
    cols = ["stable_signal_id", "source_route_name", "signal_approach_id_v2"]
    x = bin_context[cols].dropna().copy()
    if x.empty:
        return pd.DataFrame(columns=["stable_signal_id", "route_name", "signal_approach_id_v2", "approach_candidate_count"])
    counts = x.groupby(cols).size().reset_index(name="n").sort_values("n", ascending=False)
    first = counts.drop_duplicates(["stable_signal_id", "source_route_name"]).rename(columns={"source_route_name": "route_name"})
    cand = counts.groupby(["stable_signal_id", "source_route_name"])["signal_approach_id_v2"].nunique().reset_index(name="approach_candidate_count").rename(columns={"source_route_name": "route_name"})
    return first[["stable_signal_id", "route_name", "signal_approach_id_v2"]].merge(cand, on=["stable_signal_id", "route_name"], how="left")


def build_corridor_index(projection: pd.DataFrame, roads: pd.DataFrame, approach_map: pd.DataFrame) -> pd.DataFrame:
    usable = projection[projection["usable_as_corridor_boundary"].astype(bool) & projection["route_name"].notna()].copy()
    reviewed = usable[nonmissing(usable["stable_signal_id"])].copy()
    route_groups = {route: group.sort_values("estimated_measure").copy() for route, group in usable.groupby("route_name", dropna=False)}
    records = []
    for i, (_, row) in enumerate(reviewed.iterrows(), start=1):
        if i % 5000 == 0:
            log(f"Built corridor records for {i:,} / {len(reviewed):,} stable signal projections.")
        route = row["route_name"]
        route_proj = route_groups.get(route)
        reviewed_measure = float(row["estimated_measure"])
        if route_proj is None or route_proj.empty:
            before = after = pd.DataFrame()
        else:
            others = route_proj[route_proj["source_signal_globalid"].astype(str).str.upper().ne(str(row["source_signal_globalid"]).upper())].copy()
            before = others[pd.to_numeric(others["estimated_measure"], errors="coerce") < reviewed_measure - MEASURE_EPS].tail(1)
            after = others[pd.to_numeric(others["estimated_measure"], errors="coerce") > reviewed_measure + MEASURE_EPS].head(1)

        road_from = float(row["from_measure"]) if pd.notna(row["from_measure"]) else math.nan
        road_to = float(row["to_measure"]) if pd.notna(row["to_measure"]) else math.nan
        low_row = min(road_from, road_to) if not math.isnan(road_from) and not math.isnan(road_to) else math.nan
        high_row = max(road_from, road_to) if not math.isnan(road_from) and not math.isnan(road_to) else math.nan
        before_ep = before.iloc[0] if not before.empty else None
        after_ep = after.iloc[0] if not after.empty else None
        before_measure = float(before_ep["estimated_measure"]) if before_ep is not None else math.nan
        after_measure = float(after_ep["estimated_measure"]) if after_ep is not None else math.nan

        before_boundary = before_measure if not math.isnan(before_measure) else max(low_row, reviewed_measure - CORRIDOR_CUTOFF_MI) if not math.isnan(low_row) else math.nan
        after_boundary = after_measure if not math.isnan(after_measure) else min(high_row, reviewed_measure + CORRIDOR_CUTOFF_MI) if not math.isnan(high_row) else math.nan
        before_ok = not math.isnan(before_boundary) and before_boundary < reviewed_measure - MEASURE_EPS
        after_ok = not math.isnan(after_boundary) and after_boundary > reviewed_measure + MEASURE_EPS

        if before_ep is not None and after_ep is not None:
            method = "source_signal_to_source_signal"
        elif before_ok or after_ok:
            method = "source_signal_to_2500ft_cutoff"
            if (before_ep is None and not math.isnan(low_row) and abs(before_boundary - low_row) <= MEASURE_EPS) or (after_ep is None and not math.isnan(high_row) and abs(after_boundary - high_row) <= MEASURE_EPS):
                method = "source_signal_to_row_endpoint"
        else:
            method = "insufficient_boundary"

        before_stable = "" if before_ep is None or pd.isna(before_ep.get("stable_signal_id")) else str(before_ep.get("stable_signal_id"))
        after_stable = "" if after_ep is None or pd.isna(after_ep.get("stable_signal_id")) else str(after_ep.get("stable_signal_id"))
        endpoint_source_only = (before_ep is not None and not before_stable) or (after_ep is not None and not after_stable)
        confidence_value = "high" if row["projection_confidence"] == "high" and (before_ok or after_ok) else ("medium" if row["projection_confidence"] in {"high", "medium"} and (before_ok or after_ok) else "none")
        no_reason = "" if before_ok or after_ok else "insufficient_boundary"
        approach = approach_map[(approach_map["stable_signal_id"].astype(str).eq(str(row["stable_signal_id"]))) & (approach_map["route_name"].astype(str).eq(str(route)))]
        approach_id = approach.iloc[0]["signal_approach_id_v2"] if not approach.empty else ""
        corridor_id = stable_hash("corridor", [row["stable_signal_id"], row["source_signal_globalid"], route, row["road_row_id"], row["estimated_measure"]])
        records.append({
            "corridor_index_id": corridor_id,
            "stable_signal_id": row["stable_signal_id"],
            "reviewed_source_signal_globalid": row["source_signal_globalid"],
            "signal_approach_id_v2": approach_id,
            "route_base": row["route_base"],
            "carriageway_direction_token": row["carriageway_direction_token"],
            "road_row_id": row["road_row_id"],
            "road_source_row_index": row["road_source_row_index"],
            "route_name": route,
            "road_rte_id": row["road_rte_id"],
            "road_rte_common": row["road_rte_common"],
            "from_measure": row["from_measure"],
            "to_measure": row["to_measure"],
            "reviewed_signal_estimated_measure": reviewed_measure,
            "reviewed_signal_projection_confidence": row["projection_confidence"],
            "before_endpoint_globalid": before_ep["source_signal_globalid"] if before_ep is not None else "",
            "before_endpoint_stable_signal_id": before_stable,
            "before_endpoint_measure": before_measure if not math.isnan(before_measure) else pd.NA,
            "after_endpoint_globalid": after_ep["source_signal_globalid"] if after_ep is not None else "",
            "after_endpoint_stable_signal_id": after_stable,
            "after_endpoint_measure": after_measure if not math.isnan(after_measure) else pd.NA,
            "before_interval_from_measure": before_boundary if before_ok else pd.NA,
            "before_interval_to_measure": reviewed_measure if before_ok else pd.NA,
            "after_interval_from_measure": reviewed_measure if after_ok else pd.NA,
            "after_interval_to_measure": after_boundary if after_ok else pd.NA,
            "boundary_method": method,
            "endpoint_source_only_used": bool(endpoint_source_only),
            "corridor_confidence": confidence_value,
            "no_corridor_reason": no_reason,
        })
    return pd.DataFrame(records)


def unresolved_bins(bin_context: pd.DataFrame) -> pd.DataFrame:
    side = side_values(bin_context)
    status_text = (
        bin_context.get("directionality_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
        + "|"
        + bin_context.get("directionality_recovery_status", pd.Series("", index=bin_context.index)).astype("string").str.lower().fillna("")
    )
    unresolved = (~nonmissing(side)) | status_text.str.contains("not_recovered|unresolved", regex=True, na=False)
    out = bin_context[unresolved].copy()
    out["distance_band_out"] = out.get("distance_band_v2", out.get("distance_band"))
    return out


def link_unresolved_to_corridors(unresolved: pd.DataFrame, corridors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    usable_corridors = corridors[corridors["corridor_confidence"].isin(["high", "medium"])].copy()
    route_map = {k: v for k, v in usable_corridors.groupby(["stable_signal_id", "route_name"], dropna=False)}
    records = []
    for _, row in unresolved.iterrows():
        key = (row.get("stable_signal_id"), row.get("source_route_name"))
        cands = route_map.get(key)
        if cands is None or cands.empty:
            records.append({"link_status": "not_linked_no_corridor_for_signal_route", "stable_signal_id": row.get("stable_signal_id"), "signal_approach_id_v2": row.get("signal_approach_id_v2"), "source_route_name": row.get("source_route_name"), "distance_band": row.get("distance_band_out"), "generated_bin_flag": row.get("generated_bin_flag"), "bins": 1})
            continue
        measure = pd.to_numeric(pd.Series([row.get("source_measure_midpoint")]), errors="coerce").iloc[0]
        if pd.isna(measure):
            start = pd.to_numeric(pd.Series([row.get("source_measure_start")]), errors="coerce").iloc[0]
            end = pd.to_numeric(pd.Series([row.get("source_measure_end")]), errors="coerce").iloc[0]
            measure = (float(start) + float(end)) / 2.0 if pd.notna(start) and pd.notna(end) else math.nan
        if math.isnan(float(measure)) if pd.notna(measure) else True:
            records.append({"link_status": "not_linked_missing_bin_measure", "stable_signal_id": row.get("stable_signal_id"), "signal_approach_id_v2": row.get("signal_approach_id_v2"), "source_route_name": row.get("source_route_name"), "distance_band": row.get("distance_band_out"), "generated_bin_flag": row.get("generated_bin_flag"), "bins": 1})
            continue
        m = float(measure)
        linked = cands[
            (
                (pd.to_numeric(cands["before_interval_from_measure"], errors="coerce") <= m + MEASURE_EPS)
                & (pd.to_numeric(cands["before_interval_to_measure"], errors="coerce") >= m - MEASURE_EPS)
            )
            | (
                (pd.to_numeric(cands["after_interval_from_measure"], errors="coerce") <= m + MEASURE_EPS)
                & (pd.to_numeric(cands["after_interval_to_measure"], errors="coerce") >= m - MEASURE_EPS)
            )
        ]
        if len(linked) == 1:
            status = "linked_to_single_corridor_interval"
        elif len(linked) > 1:
            status = "not_linked_multiple_corridors"
        else:
            status = "not_linked_measure_outside_corridor_intervals"
        records.append({"link_status": status, "stable_signal_id": row.get("stable_signal_id"), "signal_approach_id_v2": row.get("signal_approach_id_v2"), "source_route_name": row.get("source_route_name"), "distance_band": row.get("distance_band_out"), "generated_bin_flag": row.get("generated_bin_flag"), "bins": 1})
    detail = pd.DataFrame(records)
    summary = detail.groupby(["link_status"], dropna=False)["bins"].sum().reset_index()
    return detail, summary


def acceptance_tests(projection: pd.DataFrame, corridors: pd.DataFrame, signal_identity: pd.DataFrame) -> pd.DataFrame:
    rows = []
    id_lookup = signal_identity.set_index(signal_identity["_globalid_norm"]) if "_globalid_norm" in signal_identity.columns else pd.DataFrame()
    for case_id, spec in CASE_TESTS.items():
        blockers = []
        stable = spec["stable_signal_id"]
        reviewed = norm_globalid(spec["reviewed_globalid"])
        endpoints = [norm_globalid(e) for e in spec["endpoints"]]
        routes = spec["routes"]
        reviewed_proj = projection[(projection["source_signal_globalid"].map(norm_globalid).eq(reviewed)) & (projection["route_name"].isin(routes)) & (projection["usable_as_corridor_boundary"].astype(bool))]
        endpoint_proj = projection[(projection["source_signal_globalid"].map(norm_globalid).isin(endpoints)) & (projection["route_name"].isin(routes)) & (projection["usable_as_corridor_boundary"].astype(bool))]
        corr = corridors[(corridors["stable_signal_id"].astype(str).eq(stable)) & (corridors["route_name"].isin(routes)) & (corridors["corridor_confidence"].isin(["high", "medium"]))]
        if reviewed_proj["route_name"].nunique() < len(routes):
            blockers.append("missing_reviewed_signal_projection_for_required_route")
        endpoint_route_counts = endpoint_proj.groupby("route_name")["source_signal_globalid"].nunique() if not endpoint_proj.empty else pd.Series(dtype=int)
        if any(endpoint_route_counts.get(route, 0) < len(endpoints) for route in routes):
            blockers.append("missing_endpoint_projection_for_required_route")
        if corr["route_name"].nunique() < len(routes):
            blockers.append("missing_signal_bounded_corridor_for_required_route")
        source_only_ok = True
        source_only_count = 0
        for endpoint in endpoints:
            if endpoint in id_lookup.index:
                stable_id = id_lookup.loc[endpoint].get("stable_signal_id")
                if isinstance(stable_id, pd.Series):
                    stable_id = stable_id.iloc[0]
                if pd.isna(stable_id) or str(stable_id).strip() == "":
                    source_only_count += 1
        if spec["requires_source_only_endpoint"]:
            source_only_used = corr["endpoint_source_only_used"].astype(bool).any()
            source_only_ok = source_only_count > 0 and source_only_used
            if not source_only_ok:
                blockers.append("source_only_endpoint_not_preserved_as_boundary")
        passed = not blockers
        rows.append({
            "case_id": case_id,
            "stable_signal_id": stable,
            "reviewed_globalid": spec["reviewed_globalid"],
            "required_routes": "|".join(routes),
            "endpoint_globalids": "|".join(spec["endpoints"]),
            "reviewed_projection_routes": int(reviewed_proj["route_name"].nunique()),
            "endpoint_projection_rows": int(len(endpoint_proj)),
            "corridor_routes": int(corr["route_name"].nunique()),
            "source_only_endpoint_count": int(source_only_count),
            "source_only_endpoint_boundary_used": bool(corr["endpoint_source_only_used"].astype(bool).any()) if not corr.empty else False,
            "acceptance_passed": bool(passed),
            "blocker_if_failed": "|".join(blockers),
        })
    return pd.DataFrame(rows)


def build_summaries(projection: pd.DataFrame, corridors: pd.DataFrame, signal_identity: pd.DataFrame, link_summary: pd.DataFrame, acceptance: pd.DataFrame) -> dict[str, pd.DataFrame]:
    summaries = {
        "signal_projection_summary": projection.groupby(["signal_role_hint", "projection_confidence", "usable_as_corridor_boundary"], dropna=False).size().reset_index(name="projection_rows"),
        "road_projection_candidate_summary": projection.groupby(["route_name", "projection_confidence"], dropna=False).size().reset_index(name="projection_rows").sort_values("projection_rows", ascending=False).head(500),
        "source_only_endpoint_signal_summary": signal_identity.groupby(["signal_role_hint", "geometry_available"], dropna=False).size().reset_index(name="signals"),
        "signal_bounded_corridor_summary": corridors.groupby(["boundary_method", "corridor_confidence", "endpoint_source_only_used"], dropna=False).size().reset_index(name="corridor_rows"),
        "unresolved_bin_to_corridor_link_summary": link_summary,
        "manual_case_projection_acceptance_tests": acceptance,
        "projection_failure_reasons": projection.groupby(["no_projection_reason"], dropna=False).size().reset_index(name="projection_rows").sort_values("projection_rows", ascending=False),
        "corridor_failure_reasons": corridors.groupby(["no_corridor_reason"], dropna=False).size().reset_index(name="corridor_rows").sort_values("corridor_rows", ascending=False),
    }
    return summaries


def recommendations(acceptance: pd.DataFrame, link_summary: pd.DataFrame, qa_rows: list[dict[str, Any]]) -> pd.DataFrame:
    failed_gates = [r for r in qa_rows if r["status"] == "fail"]
    failed_cases = acceptance[~acceptance["acceptance_passed"].astype(bool)]
    linked = int(link_summary.loc[link_summary["link_status"].eq("linked_to_single_corridor_interval"), "bins"].sum()) if not link_summary.empty else 0
    if failed_gates or not failed_cases.empty:
        rec = "fix_projection_index_acceptance_blockers_before_directionality_proposal"
    elif linked > 0:
        rec = "use_projection_and_corridor_index_for_next_review_only_directionality_proposal"
    else:
        rec = "improve_corridor_linkage_before_directionality_proposal"
    return pd.DataFrame([{
        "recommendation": rec,
        "acceptance_cases_passed": bool(failed_cases.empty),
        "linked_unresolved_bins": linked,
        "next_step": "Use the staged projection/corridor Parquet indexes as inputs to the next review-only corridor-side directionality proposal; do not mutate bin_context in this task.",
    }])


def write_findings(projection: pd.DataFrame, corridors: pd.DataFrame, signal_identity: pd.DataFrame, link_summary: pd.DataFrame, acceptance: pd.DataFrame, recs: pd.DataFrame) -> None:
    linked = int(link_summary.loc[link_summary["link_status"].eq("linked_to_single_corridor_interval"), "bins"].sum()) if not link_summary.empty else 0
    unlinked = int(link_summary.loc[~link_summary["link_status"].eq("linked_to_single_corridor_interval"), "bins"].sum()) if not link_summary.empty else 0
    case2 = acceptance[acceptance["case_id"].eq("case_2")].iloc[0]
    case3 = acceptance[acceptance["case_id"].eq("case_3")].iloc[0]
    source_only = int(signal_identity["signal_role_hint"].eq("source_only_signal").sum())
    source_only_with_geom = int((signal_identity["signal_role_hint"].eq("source_only_signal") & signal_identity["geometry_available"].astype(bool)).sum())
    text = f"""# Source Signal / Travelway Projection Index

## What Intermediate Table Was Built

This task built `source_signal_travelway_projection_index.parquet` and `signal_bounded_travelway_corridor_index.parquet` under the staged refresh candidate cache. These are support indexes only; they do not assign directionality.

## Why Source-Only Endpoint Signals Are Supported

The projection universe starts from all normalized source signals, not only signals with `stable_signal_id`. Source-only signals with geometry are preserved as corridor boundary candidates. Source-only signals: {source_only}; source-only with geometry: {source_only_with_geom}.

## Projection Coverage

Projection index rows: {len(projection)}. Usable corridor-boundary projection rows: {int(projection['usable_as_corridor_boundary'].sum())}.

## Corridor Boundary Coverage

Corridor index rows: {len(corridors)}. Corridor rows using at least one source-only endpoint: {int(corridors['endpoint_source_only_used'].sum())}.

## Case 2 Acceptance Test Result

Case 2 passed: {bool(case2['acceptance_passed'])}. Blocker if failed: {case2['blocker_if_failed'] or ''}.

## Case 3 Acceptance Test Result

Case 3 passed: {bool(case3['acceptance_passed'])}. Blocker if failed: {case3['blocker_if_failed'] or ''}.

## Unresolved Directionality Bins Linked To Corridors

Unresolved bins linked to exactly one signal-bounded corridor interval: {linked}. Unresolved bins still not linkable: {unlinked}.

## Ready For Next Directionality Proposal

The index is ready to support the next review-only directionality proposal if both hard acceptance cases pass and QA gates remain clean. Current recommendation: `{recs.iloc[0]['recommendation']}`.

## Recommended Next Step

Use these staged indexes as the intermediate source-signal/Travelway projection layer for the next corridor-side directionality proposal. Keep any mutation as a separate, explicitly approved task.
"""
    (REVIEW_OUT / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    REVIEW_OUT.mkdir(parents=True, exist_ok=True)
    (REVIEW_OUT / "progress_log.md").write_text("# Progress Log\n", encoding="utf-8")
    log("Loading normalized source artifacts, staged cache tables, and prior review outputs.")
    data = load_inputs()
    qa_rows = validate_required_fields(data["signals"], data["roads"])
    if any(r["status"] == "fail" for r in qa_rows):
        log("Required source fields are missing; writing blocked QA outputs.")

    log("Building source signal identity universe.")
    signal_identity = build_signal_identity(data["signals"], data["bin_context"], data["case_crosswalk"])
    roads = prepare_roads(data["roads"])

    log("Building source signal to Travelway projection index.")
    projection = build_projection_index(signal_identity, roads)
    projection.to_parquet(PROJECTION_INDEX, index=False)
    log(f"Wrote staged projection index: {rel(PROJECTION_INDEX)} ({len(projection):,} rows).")

    log("Building signal-bounded Travelway corridor index.")
    approach_map = modal_approach_map(data["bin_context"])
    corridors = build_corridor_index(projection, roads, approach_map)
    corridors.to_parquet(CORRIDOR_INDEX, index=False)
    log(f"Wrote staged corridor index: {rel(CORRIDOR_INDEX)} ({len(corridors):,} rows).")

    log("Linking unresolved bins to corridor intervals for QA only.")
    unresolved = unresolved_bins(data["bin_context"])
    _link_detail, link_summary = link_unresolved_to_corridors(unresolved, corridors)

    log("Running manual acceptance tests and writing review outputs.")
    acceptance = acceptance_tests(projection, corridors, signal_identity)
    if not PROJECTION_INDEX.exists():
        qa_rows.append({"qa_gate": "projection_parquet_exists", "status": "fail", "detail": rel(PROJECTION_INDEX)})
    else:
        qa_rows.append({"qa_gate": "projection_parquet_exists", "status": "pass", "detail": rel(PROJECTION_INDEX)})
    if not CORRIDOR_INDEX.exists():
        qa_rows.append({"qa_gate": "corridor_parquet_exists", "status": "fail", "detail": rel(CORRIDOR_INDEX)})
    else:
        qa_rows.append({"qa_gate": "corridor_parquet_exists", "status": "pass", "detail": rel(CORRIDOR_INDEX)})
    qa_rows.append({"qa_gate": "no_directionality_assignment", "status": "pass", "detail": "No upstream/downstream columns are written to the staged index Parquets."})
    if not bool(acceptance["acceptance_passed"].all()):
        qa_rows.append({"qa_gate": "manual_case_acceptance", "status": "fail", "detail": "|".join(acceptance.loc[~acceptance["acceptance_passed"], "case_id"].astype(str))})
    else:
        qa_rows.append({"qa_gate": "manual_case_acceptance", "status": "pass", "detail": "case_2 and case_3 passed"})

    summaries = build_summaries(projection, corridors, signal_identity, link_summary, acceptance)
    recs = recommendations(acceptance, link_summary, qa_rows)
    for name, df in summaries.items():
        write_csv(f"{name}.csv", df)
    write_csv("recommended_next_actions.csv", recs)
    write_findings(projection, corridors, signal_identity, link_summary, acceptance, recs)

    manifest = {
        "created_utc": now_iso(),
        "bounded_question": "Build source-signal/Travelway projection and signal-bounded corridor indexes without assigning directionality.",
        "source_inputs": [rel(p) for p in [SIGNALS, ROADS, BIN_CONTEXT, SIGNAL_APPROACHES, CONTINUATION_CORRIDORS]],
        "prior_review_inputs": [rel(CASE_OUT), rel(GLOBAL_OUT)],
        "staged_outputs": [rel(PROJECTION_INDEX), rel(CORRIDOR_INDEX)],
        "review_output_dir": rel(REVIEW_OUT),
        "projection_index_rows": int(len(projection)),
        "corridor_index_rows": int(len(corridors)),
        "source_only_signal_count": int(signal_identity["signal_role_hint"].eq("source_only_signal").sum()),
        "source_only_boundary_projection_rows": int(projection[(projection["signal_role_hint"].eq("source_only_signal")) & (projection["usable_as_corridor_boundary"].astype(bool))].shape[0]),
        "unresolved_bins_considered_for_linkage": int(len(unresolved)),
        "unresolved_link_summary": link_summary.to_dict("records"),
        "no_directionality_assignment": True,
    }
    qa_manifest = {
        "created_utc": now_iso(),
        "qa_gates": qa_rows,
        "manual_case_acceptance": acceptance.to_dict("records"),
        "projection_index_exists": PROJECTION_INDEX.exists(),
        "corridor_index_exists": CORRIDOR_INDEX.exists(),
        "recommendation": recs.iloc[0]["recommendation"],
    }
    (REVIEW_OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (REVIEW_OUT / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    log("Completed source signal / Travelway projection and corridor index build.")


if __name__ == "__main__":
    main()
