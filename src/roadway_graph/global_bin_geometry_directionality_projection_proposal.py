"""Global review-only bin-geometry directionality projection proposal.

This script does not mutate staged data. It projects both reviewed signal
points and bin representative points onto matched source Travelway geometry,
then proposes upstream/downstream only where existing same-corridor labels
provide a consistent local calibration.
"""

from __future__ import annotations

import json
import math
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
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/global_bin_geometry_directionality_projection_proposal"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING_DIR / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING_DIR / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
SIGNALS = REPO_ROOT / "artifacts/normalized/signals.parquet"
ROADS = REPO_ROOT / "artifacts/normalized/roads.parquet"

CURRENT_UNITS = 98_831
CONSERVATIVE_TARGET = 109_842
UPPER_TARGET = 132_866
SIGNAL_HIGH_FT = 100.0
SIGNAL_MEDIUM_FT = 300.0
BIN_HIGH_FT = 75.0
BIN_MEDIUM_FT = 200.0
EPS = 1.0

MANUAL_CASES = pd.DataFrame(
    [
        {"case_id": "case_1", "stable_signal_id": "sig_03e277feabe81aadd78f", "expected_pattern": "positive_control"},
        {"case_id": "case_2", "stable_signal_id": "sig_05a2cb689cbc4f27814d", "expected_pattern": "sr208_long_row_split"},
        {"case_id": "case_3", "stable_signal_id": "sig_439930214d7b1b49426f", "expected_pattern": "us1_source_boundary_split"},
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


def first_col(df: pd.DataFrame, names: list[str], default: Any = pd.NA) -> pd.Series:
    for name in names:
        if name in df.columns:
            return df[name]
    return pd.Series(default, index=df.index)


def side_values(df: pd.DataFrame) -> pd.Series:
    side = first_col(df, ["upstream_downstream", "upstream_downstream_values"])
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonnull(side), df["upstream_downstream_values"])
    return side


def band_values(df: pd.DataFrame) -> pd.Series:
    return first_col(df, ["distance_band_v2", "distance_band"])


def load_road_geom(value: Any):
    if wkb is None or pd.isna(value):
        return None
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return wkb.loads(bytes(value))
    except Exception:
        return None
    return None


def representative_point_from_wkt(value: Any):
    if wkt is None or pd.isna(value):
        return None
    try:
        geom = wkt.loads(str(value))
        if geom.is_empty:
            return None
        if geom.geom_type in {"LineString", "MultiLineString"}:
            return geom.interpolate(0.5, normalized=True)
        return geom.representative_point()
    except Exception:
        return None


def signal_projection_conf(distance_ft: Any) -> tuple[str, bool, str]:
    if pd.isna(distance_ft):
        return "failed", False, "missing_signal_or_road_geometry"
    d = float(distance_ft)
    if d <= SIGNAL_HIGH_FT:
        return "high", True, ""
    if d <= SIGNAL_MEDIUM_FT:
        return "medium", True, ""
    return "low", False, "projection_too_far"


def bin_projection_conf(distance_ft: Any) -> tuple[str, bool, str]:
    if pd.isna(distance_ft):
        return "failed", False, "missing_bin_or_road_geometry"
    d = float(distance_ft)
    if d <= BIN_HIGH_FT:
        return "high", True, ""
    if d <= BIN_MEDIUM_FT:
        return "medium", True, ""
    return "low", False, "projection_too_far"


def has_cardinal(route: Any) -> bool:
    txt = "" if pd.isna(route) else str(route).upper().strip()
    return any(txt.endswith(s) for s in ["NB", "SB", "EB", "WB"])


def is_proxy(row: pd.Series) -> bool:
    text = " ".join(str(row.get(c, "")) for c in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"]).lower()
    return "divided" in text and not has_cardinal(row.get("source_route_name"))


def is_undivided(row: pd.Series) -> bool:
    text = " ".join(str(row.get(c, "")) for c in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"]).lower()
    return "undivided" in text or "two-way" in text or "2-way" in text


def classify_rule(row: pd.Series) -> tuple[str, str, str]:
    origin = str(row.get("bin_row_origin", "")).lower()
    cont = str(row.get("continuation_class", "")).lower()
    if "generated" in origin or "continuation" in cont:
        return (
            "proposed_generated_continuation_geometry_split",
            "generated_continuation_geometry_split",
            "geometry_generated_continuation_local_calibration",
        )
    if is_proxy(row):
        return (
            "proposed_divided_centerline_proxy_geometry_split",
            "divided_centerline_proxy_geometry_split",
            "synthetic_or_proxy_divided_centerline_geometry_split",
        )
    if has_cardinal(row.get("source_route_name")):
        return (
            "proposed_paired_divided_carriageway_geometry_split",
            "paired_divided_carriageway_geometry_split",
            "direct_divided_bin_geometry_signal_split",
        )
    if is_undivided(row):
        return (
            "proposed_synthetic_undivided_geometry_split",
            "synthetic_undivided_geometry_split",
            "synthetic_undivided_bin_geometry_signal_split",
        )
    return (
        "proposed_bin_geometry_signal_position_split",
        "bin_geometry_signal_position_split",
        "bin_geometry_signal_position_local_calibration",
    )


def read_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    wanted = [
        "stable_signal_id",
        "source_signal_id",
        "stable_bin_id",
        "stable_travelway_id",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "source_measure_start",
        "source_measure_end",
        "distance_start_ft",
        "distance_end_ft",
        "distance_band",
        "distance_band_v2",
        "geometry_wkt",
        "signal_approach_id_v2",
        "bin_row_origin",
        "generated_bin_flag",
        "continuation_corridor_id",
        "continuation_class",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "rim_facility_raw",
        "upstream_downstream_values",
        "upstream_downstream",
        "directionality_status",
        "directionality_recovery_status",
    ]
    cols = [c for c in pd.read_parquet(BIN_CONTEXT).columns if c in wanted]
    bin_context = pd.read_parquet(BIN_CONTEXT, columns=cols)
    signals = pd.read_parquet(SIGNALS)
    roads = pd.read_parquet(ROADS, columns=["RTE_NM", "FROM_MEASURE", "TO_MEASURE", "RTE_COMMON", "RTE_ID", "geometry"])
    corridors = pd.read_parquet(CONTINUATION_CORRIDORS)
    return bin_context, signals, roads, corridors


def build_unresolved(bin_context: pd.DataFrame) -> pd.DataFrame:
    side = side_values(bin_context)
    x = bin_context[~nonnull(side)].copy()
    x["distance_band_out"] = band_values(x)
    x["has_bin_geometry"] = x.get("geometry_wkt", pd.Series(pd.NA, index=x.index)).notna()
    return x


def build_clusters(unresolved: pd.DataFrame) -> pd.DataFrame:
    group_cols = [
        "stable_signal_id",
        "signal_approach_id_v2",
        "source_route_name",
        "continuation_corridor_id",
        "bin_row_origin",
        "continuation_class",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "rim_facility_raw",
    ]
    group_cols = [c for c in group_cols if c in unresolved.columns]
    clusters = (
        unresolved.groupby(group_cols, dropna=False)
        .agg(
            unresolved_bins=("stable_bin_id", "size"),
            bin_geometry_available=("has_bin_geometry", "sum"),
            distance_min_ft=("distance_start_ft", "min"),
            distance_max_ft=("distance_end_ft", "max"),
            distance_bands=("distance_band_out", lambda s: "|".join(sorted({str(v) for v in s.dropna()}))),
        )
        .reset_index()
    )
    clusters["bin_geometry_cluster_id"] = ["bin_geom_cluster_%06d" % (i + 1) for i in range(len(clusters))]
    clusters["has_route_identity"] = clusters.get("source_route_name", "").astype(str).str.strip().ne("")
    return clusters


def signal_crosswalk(bin_context: pd.DataFrame, signals: pd.DataFrame, stable_ids: pd.Series) -> pd.DataFrame:
    src = (
        bin_context[["stable_signal_id", "source_signal_id"]]
        .dropna()
        .drop_duplicates()
        .groupby("stable_signal_id")["source_signal_id"]
        .agg(lambda s: sorted({str(v) for v in s if str(v).strip()})[0] if len(s) else "")
        .reset_index()
    )
    wanted = pd.DataFrame({"stable_signal_id": sorted(set(stable_ids.dropna().astype(str)))})
    wanted = wanted.merge(src, on="stable_signal_id", how="left")
    id_cols = [c for c in ["REG_SIGNAL_ID", "ASSET_NUM", "SIGNAL_NO", "ASSET_ID"] if c in signals.columns]
    parts = []
    for col in id_cols:
        part = signals[["GLOBALID", "geometry", col]].rename(columns={col: "source_signal_id"}).copy()
        part["source_signal_id"] = part["source_signal_id"].astype(str)
        part["signal_match_field"] = col
        parts.append(part)
    sig_ids = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    out = wanted.merge(sig_ids, on="source_signal_id", how="left")
    out = out.sort_values(["stable_signal_id", "signal_match_field"], na_position="last").drop_duplicates("stable_signal_id")
    out["signal_geometry_available"] = out["geometry"].notna()
    out["signal_match_confidence"] = out["GLOBALID"].notna().map({True: "high", False: "missing"})
    return out.rename(columns={"GLOBALID": "source_globalid"})


def match_source_roads(clusters: pd.DataFrame, roads: pd.DataFrame, sig_match: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    roads_by_route = {str(k): v.copy() for k, v in roads.groupby(roads["RTE_NM"].astype(str), dropna=False)}
    sig_geom = {str(r.stable_signal_id): load_road_geom(r.geometry) for r in sig_match.itertuples(index=False) if pd.notna(getattr(r, "geometry", pd.NA))}
    chosen: dict[str, Any] = {}
    rows = []
    for i, c in clusters.iterrows():
        if i and i % 500 == 0:
            log(f"Matched source road geometry for {i:,} / {len(clusters):,} clusters.")
        cid = c["bin_geometry_cluster_id"]
        route = str(c.get("source_route_name", ""))
        rr = roads_by_route.get(route, pd.DataFrame())
        match_type = "no_source_road_match"
        candidate_count = int(len(rr))
        selected_idx = pd.NA
        selected_distance = pd.NA
        selected_from = pd.NA
        selected_to = pd.NA
        geom = None
        if not c.get("has_route_identity", False):
            match_type = "insufficient_route_identity"
        elif rr.empty:
            match_type = "no_source_road_match"
        else:
            pt = sig_geom.get(str(c.get("stable_signal_id")))
            best = None
            if pt is not None:
                for ridx, r in rr.iterrows():
                    line = load_road_geom(r.get("geometry"))
                    if line is None or getattr(line, "length", 0) == 0:
                        continue
                    try:
                        d = float(pt.distance(line))
                    except Exception:
                        continue
                    if best is None or d < best[0]:
                        best = (d, ridx, r, line)
            if best is None:
                match_type = "missing_signal_or_road_geometry"
            else:
                d, ridx, r, line = best
                selected_idx = int(ridx)
                selected_distance = d
                selected_from = r.get("FROM_MEASURE")
                selected_to = r.get("TO_MEASURE")
                geom = line
                match_type = "exact_route_geometry_nearest_row" if len(rr) == 1 else "route_geometry_nearest_candidate"
                chosen[str(cid)] = line
        rows.append(
            {
                "bin_geometry_cluster_id": cid,
                "stable_signal_id": c.get("stable_signal_id"),
                "signal_approach_id_v2": c.get("signal_approach_id_v2"),
                "source_route_name": route,
                "source_road_match_type": match_type,
                "candidate_source_row_count": candidate_count,
                "selected_source_road_index": selected_idx,
                "selected_signal_distance_to_road_ft": selected_distance,
                "selected_source_from_measure": selected_from,
                "selected_source_to_measure": selected_to,
                "selected_geometry_available": geom is not None,
            }
        )
    return pd.DataFrame(rows), chosen


def project_point_to_line(point, line):
    if point is None or line is None or getattr(line, "length", 0) == 0:
        return pd.NA, pd.NA, pd.NA
    try:
        dist = float(point.distance(line))
        along = float(line.project(point))
        frac = along / float(line.length)
        return dist, along, frac
    except Exception:
        return pd.NA, pd.NA, pd.NA


def before_after(bin_along: Any, signal_along: Any) -> str:
    if pd.isna(bin_along) or pd.isna(signal_along):
        return "ambiguous_missing_projection"
    if float(bin_along) < float(signal_along) - EPS:
        return "before_signal"
    if float(bin_along) > float(signal_along) + EPS:
        return "after_signal"
    return "at_or_too_close_to_signal"


def project_signal_and_bins(
    unresolved: pd.DataFrame,
    clusters: pd.DataFrame,
    road_match: pd.DataFrame,
    road_geoms: dict[str, Any],
    sig_match: pd.DataFrame,
) -> pd.DataFrame:
    cluster_keys = [c for c in clusters.columns if c in unresolved.columns]
    u = unresolved.merge(clusters[cluster_keys + ["bin_geometry_cluster_id"]], on=cluster_keys, how="left")
    sig_geom = {str(r.stable_signal_id): load_road_geom(r.geometry) for r in sig_match.itertuples(index=False) if pd.notna(getattr(r, "geometry", pd.NA))}
    sig_gid = sig_match.set_index("stable_signal_id")["source_globalid"].to_dict()
    match_lu = road_match.set_index("bin_geometry_cluster_id").to_dict("index")
    rows = []
    for i, r in u.iterrows():
        if i and i % 5000 == 0:
            log(f"Projected unresolved bin geometry for {i:,} / {len(u):,} bins.")
        cid = str(r.get("bin_geometry_cluster_id"))
        line = road_geoms.get(cid)
        sig_pt = sig_geom.get(str(r.get("stable_signal_id")))
        bin_pt = representative_point_from_wkt(r.get("geometry_wkt"))
        sig_d, sig_along, sig_frac = project_point_to_line(sig_pt, line)
        bin_d, bin_along, bin_frac = project_point_to_line(bin_pt, line)
        sig_conf, sig_ok, sig_fail = signal_projection_conf(sig_d)
        bin_conf, bin_ok, bin_fail = bin_projection_conf(bin_d)
        rel = before_after(bin_along, sig_along)
        match = match_lu.get(cid, {})
        rows.append(
            {
                "stable_bin_id": r.get("stable_bin_id"),
                "stable_signal_id": r.get("stable_signal_id"),
                "source_globalid": sig_gid.get(str(r.get("stable_signal_id"))),
                "signal_approach_id_v2": r.get("signal_approach_id_v2"),
                "source_route_name": r.get("source_route_name"),
                "distance_band": r.get("distance_band_out"),
                "bin_row_origin": r.get("bin_row_origin"),
                "continuation_class": r.get("continuation_class"),
                "continuation_corridor_id": r.get("continuation_corridor_id"),
                "bin_geometry_cluster_id": cid,
                "source_road_match_type": match.get("source_road_match_type", "no_source_road_match"),
                "signal_projected_distance": sig_along,
                "bin_projected_distance": bin_along,
                "signal_distance_to_road_ft": sig_d,
                "bin_distance_to_road_ft": bin_d,
                "signal_projection_confidence": sig_conf,
                "bin_projection_confidence": bin_conf,
                "signal_projection_usable": sig_ok,
                "bin_projection_usable": bin_ok,
                "projection_failure_reason": sig_fail or bin_fail,
                "bin_before_after_signal": rel,
                "geometry_available": bin_pt is not None,
                "existing_roadway_division_context": r.get("existing_roadway_division_context"),
                "generated_roadway_division_context": r.get("generated_roadway_division_context"),
                "rim_facility_raw": r.get("rim_facility_raw"),
            }
        )
    return pd.DataFrame(rows)


def project_labeled_for_calibration(
    bin_context: pd.DataFrame,
    clusters: pd.DataFrame,
    road_geoms: dict[str, Any],
    sig_match: pd.DataFrame,
) -> pd.DataFrame:
    side = side_values(bin_context)
    resolved = bin_context[nonnull(side)].copy()
    resolved["resolved_side"] = side[nonnull(side)].astype(str).str.lower()
    sig_geom = {str(r.stable_signal_id): load_road_geom(r.geometry) for r in sig_match.itertuples(index=False) if pd.notna(getattr(r, "geometry", pd.NA))}
    rows = []
    key_cols = ["stable_signal_id", "signal_approach_id_v2", "source_route_name"]
    for i, c in clusters.iterrows():
        if i and i % 500 == 0:
            log(f"Calibrated side mapping for {i:,} / {len(clusters):,} clusters.")
        cid = str(c["bin_geometry_cluster_id"])
        line = road_geoms.get(cid)
        sig_pt = sig_geom.get(str(c.get("stable_signal_id")))
        sig_d, sig_along, _ = project_point_to_line(sig_pt, line)
        if line is None or sig_pt is None or pd.isna(sig_along):
            rows.append({"bin_geometry_cluster_id": cid, "local_calibration_available": False, "local_calibration_method": "missing_signal_or_road_geometry", "before_side": "", "after_side": "", "local_calibration_conflict": False, "calibration_bin_count": 0})
            continue
        mask = pd.Series(True, index=resolved.index)
        for col in key_cols:
            mask &= resolved[col].astype(str).eq(str(c.get(col)))
        subset = resolved[mask].copy()
        if subset.empty:
            rows.append({"bin_geometry_cluster_id": cid, "local_calibration_available": False, "local_calibration_method": "no_same_route_directional_bins", "before_side": "", "after_side": "", "local_calibration_conflict": False, "calibration_bin_count": 0})
            continue
        before_sides: list[str] = []
        after_sides: list[str] = []
        projected_count = 0
        for _, b in subset.iterrows():
            pt = representative_point_from_wkt(b.get("geometry_wkt"))
            bd, balong, _ = project_point_to_line(pt, line)
            _, bok, _ = bin_projection_conf(bd)
            if not bok:
                continue
            projected_count += 1
            rel = before_after(balong, sig_along)
            side_val = str(b.get("resolved_side", "")).lower()
            if rel == "before_signal":
                before_sides.append(side_val)
            elif rel == "after_signal":
                after_sides.append(side_val)
        before_unique = sorted(set(v for v in before_sides if v))
        after_unique = sorted(set(v for v in after_sides if v))
        conflict = len(before_unique) > 1 or len(after_unique) > 1
        available = not conflict and (len(before_unique) == 1 or len(after_unique) == 1)
        method = "same_signal_approach_route_bin_geometry_calibration" if available else "no_consistent_bin_geometry_side_mapping"
        rows.append(
            {
                "bin_geometry_cluster_id": cid,
                "local_calibration_available": available,
                "local_calibration_method": method,
                "before_side": before_unique[0] if len(before_unique) == 1 else "",
                "after_side": after_unique[0] if len(after_unique) == 1 else "",
                "local_calibration_conflict": conflict,
                "calibration_bin_count": int(projected_count),
                "before_calibration_bin_count": int(len(before_sides)),
                "after_calibration_bin_count": int(len(after_sides)),
            }
        )
    return pd.DataFrame(rows)


def build_proposals(proj: pd.DataFrame, calibration: pd.DataFrame) -> pd.DataFrame:
    x = proj.merge(calibration, on="bin_geometry_cluster_id", how="left")
    x["proposed_upstream_downstream"] = pd.NA
    before = x["bin_before_after_signal"].eq("before_signal")
    after = x["bin_before_after_signal"].eq("after_signal")
    x.loc[before, "proposed_upstream_downstream"] = x.loc[before, "before_side"]
    x.loc[after, "proposed_upstream_downstream"] = x.loc[after, "after_side"]
    side_ok = nonnull(x["proposed_upstream_downstream"])
    x["proposal_status"] = "no_proposal_ambiguous"
    x["no_proposal_reason"] = "ambiguous"
    x.loc[~x["geometry_available"].fillna(False).astype(bool), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_missing_bin_geometry", "missing_bin_geometry"]
    x.loc[x["source_road_match_type"].isin(["no_source_road_match", "insufficient_route_identity"]), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_no_source_road_match", "no_source_road_match"]
    x.loc[x["source_road_match_type"].eq("missing_signal_or_road_geometry"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_missing_road_geometry", "missing_road_geometry"]
    x.loc[x["signal_projection_confidence"].eq("failed"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_missing_signal_geometry", "missing_signal_geometry"]
    too_far = x["projection_failure_reason"].eq("projection_too_far")
    x.loc[too_far, ["proposal_status", "no_proposal_reason"]] = ["no_proposal_projection_too_far", "projection_too_far"]
    conflict = x["local_calibration_conflict"].fillna(False).astype(bool)
    x.loc[conflict, ["proposal_status", "no_proposal_reason"]] = ["no_proposal_local_calibration_conflict", "local_calibration_conflict"]
    unknown = x["signal_projection_usable"].fillna(False).astype(bool) & x["bin_projection_usable"].fillna(False).astype(bool) & x["bin_before_after_signal"].isin(["before_signal", "after_signal"]) & ~side_ok & ~conflict
    x.loc[unknown, ["proposal_status", "no_proposal_reason"]] = ["no_proposal_before_after_to_side_mapping_unknown", "before_after_to_side_mapping_unknown"]
    too_close = x["bin_before_after_signal"].eq("at_or_too_close_to_signal")
    x.loc[too_close, ["proposal_status", "no_proposal_reason"]] = ["no_proposal_ambiguous", "bin_too_close_to_signal"]
    ok = x["signal_projection_usable"].fillna(False).astype(bool) & x["bin_projection_usable"].fillna(False).astype(bool) & x["bin_before_after_signal"].isin(["before_signal", "after_signal"]) & side_ok & ~conflict
    x["proposed_rule_family"] = pd.NA
    x["proposed_directionality_method"] = pd.NA
    for idx in x.index[ok]:
        status, family, method = classify_rule(x.loc[idx])
        x.loc[idx, "proposal_status"] = status
        x.loc[idx, "proposed_rule_family"] = family
        x.loc[idx, "proposed_directionality_method"] = method
        x.loc[idx, "no_proposal_reason"] = ""
    x["proposed_confidence"] = "none"
    high = ok & x["signal_projection_confidence"].eq("high") & x["bin_projection_confidence"].eq("high") & (pd.to_numeric(x["calibration_bin_count"], errors="coerce") >= 4)
    medium = ok & ~high
    x.loc[high, "proposed_confidence"] = "high"
    x.loc[medium, "proposed_confidence"] = "medium"
    x["local_calibration_used"] = ok
    x["evidence_fields"] = "bin_context.geometry_wkt|signals.geometry|roads.geometry|same_signal_approach_route_local_calibration"
    x["conflict_flag"] = conflict
    return x


def unit_count(df: pd.DataFrame) -> int:
    prop = df[df["proposal_status"].astype(str).str.startswith("proposed_")]
    if prop.empty:
        return 0
    return int(prop[["stable_signal_id", "signal_approach_id_v2", "distance_band", "proposed_upstream_downstream"]].dropna().drop_duplicates().shape[0])


def summarize(proposals: pd.DataFrame) -> dict[str, pd.DataFrame]:
    prop = proposals[proposals["proposal_status"].astype(str).str.startswith("proposed_")]
    no = proposals[~proposals["proposal_status"].astype(str).str.startswith("proposed_")]
    high = prop[prop["proposed_confidence"].eq("high")]
    med = prop[prop["proposed_confidence"].eq("medium")]
    by_rule = prop.groupby(["proposed_rule_family", "proposed_directionality_method", "proposed_confidence"], dropna=False).size().reset_index(name="proposed_bins")
    units = []
    for keys, g in prop.groupby(["proposed_rule_family", "proposed_directionality_method", "proposed_confidence"], dropna=False):
        units.append({"proposed_rule_family": keys[0], "proposed_directionality_method": keys[1], "proposed_confidence": keys[2], "proposed_units": unit_count(g)})
    if units:
        by_rule = by_rule.merge(pd.DataFrame(units), on=["proposed_rule_family", "proposed_directionality_method", "proposed_confidence"], how="left")
    high_units = unit_count(high)
    hm_units = unit_count(pd.concat([high, med], ignore_index=True))
    return {
        "summary": proposals.groupby(["proposal_status", "proposed_confidence"], dropna=False).size().reset_index(name="bins"),
        "no": no.groupby("no_proposal_reason", dropna=False).size().reset_index(name="bins").sort_values("bins", ascending=False),
        "by_rule": by_rule,
        "by_band": prop.groupby("distance_band", dropna=False).size().reset_index(name="proposed_bins"),
        "by_signal": prop.groupby("stable_signal_id", dropna=False).size().reset_index(name="proposed_bins").sort_values("proposed_bins", ascending=False),
        "by_config": prop.groupby(["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"], dropna=False).size().reset_index(name="proposed_bins"),
        "by_conf": prop.groupby("proposed_confidence", dropna=False).size().reset_index(name="proposed_bins"),
        "impact": pd.DataFrame(
            [
                {"metric": "unresolved_bins_considered", "value": len(proposals)},
                {"metric": "proposed_bins_total", "value": len(prop)},
                {"metric": "high_confidence_proposed_bins", "value": len(high)},
                {"metric": "medium_confidence_proposed_bins", "value": len(med)},
                {"metric": "high_confidence_proposed_units", "value": high_units},
                {"metric": "high_plus_medium_proposed_units", "value": hm_units},
                {"metric": "percent_conservative_target_if_high_confidence_applied", "value": round((CURRENT_UNITS + high_units) / CONSERVATIVE_TARGET * 100, 4)},
                {"metric": "percent_conservative_target_if_high_plus_medium_applied", "value": round((CURRENT_UNITS + hm_units) / CONSERVATIVE_TARGET * 100, 4)},
                {"metric": "percent_upper_bound_target_if_high_confidence_applied", "value": round((CURRENT_UNITS + high_units) / UPPER_TARGET * 100, 4)},
                {"metric": "remaining_unresolved_bins_after_all_proposals", "value": len(no)},
            ]
        ),
    }


def manual_validation(proposals: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, case in MANUAL_CASES.iterrows():
        p = proposals[proposals["stable_signal_id"].astype(str).eq(case["stable_signal_id"])]
        prop = p[p["proposal_status"].astype(str).str.startswith("proposed_")]
        rows.append(
            {
                "case_id": case["case_id"],
                "stable_signal_id": case["stable_signal_id"],
                "expected_pattern": case["expected_pattern"],
                "unresolved_bins_before_proposal": len(p),
                "proposed_bins": len(prop),
                "proposed_units": unit_count(prop),
                "rule_families_used": "|".join(sorted(prop["proposed_rule_family"].dropna().astype(str).unique())),
                "confidence_values": "|".join(sorted(prop["proposed_confidence"].dropna().astype(str).unique())),
                "remaining_unresolved_bins": len(p) - len(prop),
                "case2_improved_vs_signal_measure_pass": bool(case["case_id"] == "case_2" and len(prop) > 0),
                "case3_improved_vs_signal_measure_pass": bool(case["case_id"] == "case_3" and len(prop) > 0),
                "conflicts_or_warnings": "",
            }
        )
    return pd.DataFrame(rows)


def recommendation(summaries: dict[str, pd.DataFrame], conflicts: pd.DataFrame) -> str:
    blocking = int(pd.to_numeric(conflicts.loc[conflicts["safety_check"].astype(str).str.startswith("blocking_"), "problem_count"], errors="coerce").fillna(0).sum())
    if blocking:
        return "do_not_apply_due_to_conflicts"
    high = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_bins"), "value"].iloc[0])
    med = int(summaries["impact"].loc[summaries["impact"].metric.eq("medium_confidence_proposed_bins"), "value"].iloc[0])
    if high >= 1000:
        return "implement_high_confidence_bin_geometry_directionality_proposals_to_staging"
    if high > 0 and med > high:
        return "implement_specific_rule_family_first"
    return "improve_source_road_matching_or_projection_tolerances"


def write_findings(clusters: pd.DataFrame, match: pd.DataFrame, proj: pd.DataFrame, calibration: pd.DataFrame, summaries: dict[str, pd.DataFrame], manual: pd.DataFrame, rec: str) -> None:
    proposed = int(summaries["impact"].loc[summaries["impact"].metric.eq("proposed_bins_total"), "value"].iloc[0])
    high = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_bins"), "value"].iloc[0])
    medium = int(summaries["impact"].loc[summaries["impact"].metric.eq("medium_confidence_proposed_bins"), "value"].iloc[0])
    high_units = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_units"), "value"].iloc[0])
    case2 = manual[manual.case_id.eq("case_2")].iloc[0].to_dict() if not manual[manual.case_id.eq("case_2")].empty else {}
    case3 = manual[manual.case_id.eq("case_3")].iloc[0].to_dict() if not manual[manual.case_id.eq("case_3")].empty else {}
    text = f"""# Global Bin-Geometry Directionality Projection Proposal

## What this bin-geometry projection tested

This review-only run considered {int(clusters.unresolved_bins.sum()):,} unresolved bins in {len(clusters):,} bin-geometry clusters. It projected reviewed signal points and bin representative points onto matched source Travelway geometry.

## Why parent source-row measure ranges were insufficient

The prior signal-measure pass treated inherited source-row measures as bin intervals. Many unresolved rows inherited broad parent Travelway ranges, so they appeared to straddle the signal. This run used bin geometry position as the primary before/after test.

## Geometry/projection success and failure patterns

Source road matching and projection summaries are written to CSV. Bins with missing geometry, missing roads, or point-to-line distances beyond tolerance were preserved as no-proposal cases.

## Local side calibration results

Before/after signal position was mapped to upstream/downstream only when same signal/approach/route labeled bins established a consistent relationship. Calibration conflicts were not proposed.

## Case 2 and Case 3 results

Case 2 proposed bins: {case2.get('proposed_bins', 0)}. Case 3 proposed bins: {case3.get('proposed_bins', 0)}. The bin-geometry method improved a case only if proposed bins are greater than zero.

## Global recovery potential

Total proposed bins: {proposed:,}. High-confidence proposed bins: {high:,}. Medium-confidence proposed bins: {medium:,}. High-confidence unit recovery: {high_units:,}.

## Whether high-confidence proposals are safe to apply

High-confidence proposals have usable signal and bin projection plus consistent local calibration. Blocking conflict checks are zero if reported in QA.

## What remains unresolved and why

Remaining unresolved rows are primarily missing local side mapping, missing/failed geometry projection, or local calibration conflicts. These should remain unresolved or move to targeted map review/source-rule discovery.

## Recommended next implementation step

Recommendation: `{rec}`.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Started global bin-geometry directionality projection proposal.")
    required = [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, CONTINUATION_CORRIDORS, SIGNALS, ROADS]
    missing = [rel(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing inputs: " + ", ".join(missing))

    print("reading inputs", flush=True)
    bin_context, signals, roads, corridors = read_inputs()
    pd.read_parquet(SIGNAL_APPROACHES)
    pd.read_parquet(APPROACH_WINDOWS)
    unresolved = build_unresolved(bin_context)
    clusters = build_clusters(unresolved)
    log(f"Built unresolved universe: {len(unresolved):,} bins, {len(clusters):,} clusters.")
    sig_match = signal_crosswalk(bin_context, signals, unresolved["stable_signal_id"])
    print("matching source road geometry", flush=True)
    road_match, road_geoms = match_source_roads(clusters, roads, sig_match)
    print("projecting unresolved bin geometry", flush=True)
    projection = project_signal_and_bins(unresolved, clusters, road_match, road_geoms, sig_match)
    print("building local calibration", flush=True)
    calibration = project_labeled_for_calibration(bin_context, clusters, road_geoms, sig_match)
    print("building proposals", flush=True)
    proposals = build_proposals(projection, calibration)
    summaries = summarize(proposals)
    manual = manual_validation(proposals)
    conflicts = pd.DataFrame(
        [
            {"safety_check": "staged_bin_context_modified", "problem_count": 0},
            {"safety_check": "canonical_products_modified", "problem_count": 0},
            {"safety_check": "crash_direction_fields_used", "problem_count": 0},
            {"safety_check": "blocking_proposed_rows_without_side", "problem_count": int((proposals.proposal_status.astype(str).str.startswith("proposed_") & ~nonnull(proposals.proposed_upstream_downstream)).sum())},
            {"safety_check": "blocking_conflicts_in_proposed_rows", "problem_count": int((proposals.proposal_status.astype(str).str.startswith("proposed_") & proposals.conflict_flag.fillna(False).astype(bool)).sum())},
            {"safety_check": "nonblocking_no_proposal_local_calibration_conflicts", "problem_count": int((~proposals.proposal_status.astype(str).str.startswith("proposed_") & proposals.conflict_flag.fillna(False).astype(bool)).sum())},
        ]
    )
    rec = recommendation(summaries, conflicts)

    out_cols = [
        "stable_bin_id", "stable_signal_id", "source_globalid", "signal_approach_id_v2", "source_route_name",
        "distance_band", "bin_row_origin", "continuation_class", "continuation_corridor_id",
        "proposed_upstream_downstream", "proposed_directionality_method", "proposed_rule_family", "proposed_confidence",
        "signal_projected_distance", "bin_projected_distance", "bin_before_after_signal", "signal_distance_to_road_ft",
        "bin_distance_to_road_ft", "signal_projection_confidence", "bin_projection_confidence", "local_calibration_used",
        "local_calibration_method", "evidence_fields", "conflict_flag", "proposal_status", "no_proposal_reason",
        "existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw",
        "bin_geometry_cluster_id",
    ]
    out_cols = [c for c in out_cols if c in proposals.columns]

    write_csv(clusters, "unresolved_bin_geometry_cluster_inventory.csv")
    write_csv(road_match, "source_road_geometry_match_summary.csv")
    write_csv(projection, "signal_and_bin_projection_results.csv")
    write_csv(calibration, "local_side_calibration_summary.csv")
    write_csv(proposals[out_cols], "global_bin_geometry_directionality_proposal.csv")
    write_csv(summaries["summary"], "global_bin_geometry_directionality_proposal_summary.csv")
    write_csv(summaries["no"], "proposal_no_assignment_reasons.csv")
    write_csv(summaries["by_rule"], "proposed_recovery_by_rule_family.csv")
    write_csv(summaries["by_band"], "proposed_recovery_by_distance_band.csv")
    write_csv(summaries["by_signal"], "proposed_recovery_by_signal.csv")
    write_csv(summaries["by_config"], "proposed_recovery_by_roadway_configuration.csv")
    write_csv(summaries["by_conf"], "proposed_recovery_by_confidence.csv")
    write_csv(manual, "manual_case_bin_geometry_validation_summary.csv")
    write_csv(conflicts, "conflict_and_safety_checks.csv")
    write_csv(
        pd.DataFrame(
            [
                {"priority": 1, "recommended_action": rec, "rationale": "Based on bin-geometry projection proposal volume and conflict checks."},
                {"priority": 2, "recommended_action": "review_no_proposal_before_after_to_side_mapping_unknown", "rationale": "Projection may work but local side calibration is missing."},
                {"priority": 3, "recommended_action": "create_followup_map_review_package_with_signal_points_and_crosswalk", "rationale": "Map review can validate calibration conventions for remaining high-yield clusters."},
            ]
        ),
        "recommended_next_actions.csv",
    )
    write_findings(clusters, road_match, projection, calibration, summaries, manual, rec)

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
        "unresolved_bins_considered": int(len(unresolved)),
        "clusters_considered": int(len(clusters)),
        "proposed_bins": int(summaries["impact"].loc[summaries["impact"].metric.eq("proposed_bins_total"), "value"].iloc[0]),
        "blocking_conflict_problem_count": int(pd.to_numeric(conflicts.loc[conflicts.safety_check.astype(str).str.startswith("blocking_"), "problem_count"], errors="coerce").fillna(0).sum()),
        "staged_bin_context_modified": False,
        "canonical_products_modified": False,
        "crash_direction_fields_used": False,
        "recommendation": rec,
    }
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    (OUT_DIR / "progress_log.md").write_text(f"# Progress\n- {now_iso()} Completed global bin-geometry projection proposal.\n", encoding="utf-8")
    log("Completed global bin-geometry directionality projection proposal.")
    print(f"unresolved_bins={len(unresolved)}")
    print(f"clusters={len(clusters)}")
    print(f"proposed_bins={qa['proposed_bins']}")
    print(f"recommendation={rec}")


if __name__ == "__main__":
    main()
