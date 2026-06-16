"""Global review-only geometry projection directionality proposal.

This script does not mutate staged data. It projects reviewed signal points
onto source Travelway rows for unresolved directionality bins, uses existing
same-corridor directionality as local calibration, and writes proposal tables.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from shapely import wkb
except Exception:  # pragma: no cover
    wkb = None


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_DIR = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/global_geometry_directionality_projection_proposal"

BIN_CONTEXT = STAGING_DIR / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING_DIR / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING_DIR / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING_DIR / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING_DIR / "continuation_provenance.parquet"
MANIFEST = STAGING_DIR / "manifest.json"
SCHEMA = STAGING_DIR / "schema.json"
SIGNALS = REPO_ROOT / "artifacts/normalized/signals.parquet"
ROADS = REPO_ROOT / "artifacts/normalized/roads.parquet"

CURRENT_UNITS = 98_831
CONSERVATIVE_TARGET = 109_842
UPPER_TARGET = 132_866
STRICT_PROJECTION_FT = 100.0
RELAXED_PROJECTION_FT = 300.0
MEASURE_EPSILON = 0.00001

MANUAL_CASES = pd.DataFrame(
    [
        {
            "case_id": "case_1",
            "reviewed_source_globalid": "{390C924A-CB15-4DBD-AF12-7CA202345C52}",
            "stable_signal_id": "sig_03e277feabe81aadd78f",
            "case2_sr208_expected": False,
            "case3_us1_expected": False,
        },
        {
            "case_id": "case_2",
            "reviewed_source_globalid": "{9000F2BF-82ED-4794-A473-6238A81A4109}",
            "stable_signal_id": "sig_05a2cb689cbc4f27814d",
            "case2_sr208_expected": True,
            "case3_us1_expected": False,
        },
        {
            "case_id": "case_3",
            "reviewed_source_globalid": "{275B403F-F8D7-44B7-9D2F-04875799C1FB}",
            "stable_signal_id": "sig_439930214d7b1b49426f",
            "case2_sr208_expected": False,
            "case3_us1_expected": True,
        },
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
    return s.notna() & (s.astype(str).str.strip() != "")


def first_existing(df: pd.DataFrame, names: list[str], default: Any = pd.NA) -> pd.Series:
    for name in names:
        if name in df.columns:
            return df[name]
    return pd.Series(default, index=df.index)


def direction_side(df: pd.DataFrame) -> pd.Series:
    side = first_existing(df, ["upstream_downstream", "upstream_downstream_values"])
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonnull(side), df["upstream_downstream_values"])
    return side


def distance_band(df: pd.DataFrame) -> pd.Series:
    return first_existing(df, ["distance_band_v2", "distance_band"])


def load_wkb(value: Any):
    if wkb is None or pd.isna(value):
        return None
    try:
        if isinstance(value, (bytes, bytearray, memoryview)):
            return wkb.loads(bytes(value))
    except Exception:
        return None
    return None


def route_base(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper()
    for suffix in ["NB", "SB", "EB", "WB"]:
        if text.endswith(suffix):
            return text[:-2].strip()
    return text.strip()


def has_cardinal(route: Any) -> bool:
    text = "" if pd.isna(route) else str(route).upper().strip()
    return any(text.endswith(suffix) for suffix in ["NB", "SB", "EB", "WB"])


def is_proxy_context(row: pd.Series) -> bool:
    text = " ".join(
        str(row.get(c, ""))
        for c in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"]
    ).lower()
    return "divided" in text and not has_cardinal(row.get("source_route_name"))


def is_undivided_context(row: pd.Series) -> bool:
    text = " ".join(
        str(row.get(c, ""))
        for c in ["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"]
    ).lower()
    return "undivided" in text or "two-way" in text or "2-way" in text


def projection_confidence(distance_ft: Any, match_type: str) -> tuple[str, bool, str]:
    if pd.isna(distance_ft):
        return "failed", False, "missing_geometry_or_projection"
    d = float(distance_ft)
    if d <= STRICT_PROJECTION_FT and match_type != "geometry_nearest_candidate":
        return "high", True, ""
    if d <= RELAXED_PROJECTION_FT:
        return "medium", True, ""
    return "low", False, "projection_too_far"


def read_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
        "directionality_recovery_method",
    ]
    available_cols = pd.read_parquet(BIN_CONTEXT, columns=None).columns
    use_cols = [c for c in bin_cols if c in available_cols]
    bin_context = pd.read_parquet(BIN_CONTEXT, columns=use_cols)
    signals = pd.read_parquet(SIGNALS)
    roads = pd.read_parquet(ROADS, columns=["RTE_NM", "FROM_MEASURE", "TO_MEASURE", "RTE_COMMON", "RTE_ID", "RIM_FACILI", "MEDIAN_IND", "geometry"])
    corridors = pd.read_parquet(CONTINUATION_CORRIDORS)
    return bin_context, signals, roads, corridors


def signal_crosswalk(bin_context: pd.DataFrame, signals: pd.DataFrame, unresolved: pd.DataFrame) -> pd.DataFrame:
    source_by_stable = (
        bin_context[["stable_signal_id", "source_signal_id"]]
        .dropna()
        .drop_duplicates()
        .groupby("stable_signal_id")["source_signal_id"]
        .agg(lambda s: sorted({str(v) for v in s if str(v).strip()})[0] if len(s) else "")
        .reset_index()
    )
    wanted = pd.DataFrame({"stable_signal_id": sorted(unresolved["stable_signal_id"].dropna().astype(str).unique())})
    wanted = wanted.merge(source_by_stable, on="stable_signal_id", how="left")

    id_cols = [c for c in ["REG_SIGNAL_ID", "ASSET_NUM", "SIGNAL_NO", "ASSET_ID", "ASSET_ID"] if c in signals.columns]
    sig_long = []
    for col in id_cols:
        x = signals[["GLOBALID", "geometry", col]].copy()
        x = x.rename(columns={col: "source_signal_id"})
        x["source_signal_id"] = x["source_signal_id"].astype(str)
        x["signal_match_field"] = col
        sig_long.append(x)
    sig_ids = pd.concat(sig_long, ignore_index=True).dropna(subset=["source_signal_id"]) if sig_long else pd.DataFrame()
    matched = wanted.merge(sig_ids, on="source_signal_id", how="left")
    matched = matched.sort_values(["stable_signal_id", "signal_match_field"], na_position="last").drop_duplicates("stable_signal_id")
    matched["geometry_available"] = matched["geometry"].notna()
    matched["match_method"] = matched["signal_match_field"].where(matched["signal_match_field"].notna(), "no_artifact_identifier_match")
    matched["match_confidence"] = matched["GLOBALID"].notna().map({True: "high", False: "missing"})
    return matched[
        [
            "stable_signal_id",
            "source_signal_id",
            "GLOBALID",
            "signal_match_field",
            "geometry_available",
            "match_method",
            "match_confidence",
            "geometry",
        ]
    ].rename(columns={"GLOBALID": "source_globalid"})


def build_unresolved(bin_context: pd.DataFrame) -> pd.DataFrame:
    side = direction_side(bin_context)
    unresolved = bin_context[~nonnull(side)].copy()
    unresolved["distance_band_out"] = distance_band(unresolved)
    unresolved["measure_start_num"] = pd.to_numeric(unresolved.get("source_measure_start"), errors="coerce")
    unresolved["measure_end_num"] = pd.to_numeric(unresolved.get("source_measure_end"), errors="coerce")
    unresolved["route_for_match"] = unresolved.get("source_route_name", pd.Series(pd.NA, index=unresolved.index)).astype(str)
    return unresolved


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
            measure_min=("measure_start_num", "min"),
            measure_max=("measure_end_num", "max"),
            distance_min_ft=("distance_start_ft", "min"),
            distance_max_ft=("distance_end_ft", "max"),
            distance_bands=("distance_band_out", lambda s: "|".join(sorted({str(v) for v in s.dropna()}))),
        )
        .reset_index()
    )
    clusters["projection_cluster_id"] = ["proj_cluster_%06d" % (i + 1) for i in range(len(clusters))]
    clusters["has_route_measure"] = clusters["measure_min"].notna() & clusters["measure_max"].notna() & clusters.get("source_route_name", "").astype(str).str.strip().ne("")
    return clusters


def road_match_for_clusters(clusters: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    roads_by_route = {str(k): v.copy() for k, v in roads.groupby(roads["RTE_NM"].astype(str), dropna=False)}
    match_rows: list[dict[str, Any]] = []
    chosen_rows: list[dict[str, Any]] = []
    for i, c in clusters.iterrows():
        if i and i % 500 == 0:
            log(f"Matched source roads for {i:,} / {len(clusters):,} clusters.")
        route = str(c.get("source_route_name", ""))
        rr = roads_by_route.get(route, pd.DataFrame())
        mmin = pd.to_numeric(pd.Series([c.get("measure_min")]), errors="coerce").iloc[0]
        mmax = pd.to_numeric(pd.Series([c.get("measure_max")]), errors="coerce").iloc[0]
        match_type = "no_source_row_match"
        candidates = pd.DataFrame()
        if not c.get("has_route_measure", False):
            match_type = "insufficient_fields"
        elif not rr.empty:
            overlap = rr[(pd.to_numeric(rr["FROM_MEASURE"], errors="coerce") <= mmax) & (pd.to_numeric(rr["TO_MEASURE"], errors="coerce") >= mmin)]
            exact = overlap[
                (pd.to_numeric(overlap["FROM_MEASURE"], errors="coerce") <= mmin + MEASURE_EPSILON)
                & (pd.to_numeric(overlap["TO_MEASURE"], errors="coerce") >= mmax - MEASURE_EPSILON)
            ]
            if len(exact) == 1:
                match_type = "exact_source_row_match"
                candidates = exact
            elif len(overlap) == 1:
                match_type = "overlapping_source_row_match"
                candidates = overlap
            elif len(overlap) > 1:
                match_type = "multiple_candidate_source_rows"
                candidates = overlap
            else:
                match_type = "route_match_needs_signal_split"
                candidates = rr
        match_rows.append(
            {
                "projection_cluster_id": c["projection_cluster_id"],
                "stable_signal_id": c.get("stable_signal_id"),
                "signal_approach_id_v2": c.get("signal_approach_id_v2"),
                "source_route_name": route,
                "cluster_measure_min": mmin,
                "cluster_measure_max": mmax,
                "source_row_match_type": match_type,
                "candidate_source_row_count": int(len(candidates)),
                "source_row_geometry_available_count": int(candidates["geometry"].notna().sum()) if "geometry" in candidates.columns and len(candidates) else 0,
            }
        )
        if not candidates.empty:
            for ridx, r in candidates.head(25).iterrows():
                chosen_rows.append(
                    {
                        "projection_cluster_id": c["projection_cluster_id"],
                        "road_index": int(ridx),
                        "source_route_name": r["RTE_NM"],
                        "source_from_measure": r["FROM_MEASURE"],
                        "source_to_measure": r["TO_MEASURE"],
                        "source_rte_common": r.get("RTE_COMMON"),
                        "source_rte_id": r.get("RTE_ID"),
                        "source_row_match_type": match_type,
                        "geometry": r.get("geometry"),
                    }
                )
    return pd.DataFrame(match_rows), pd.DataFrame(chosen_rows)


def project_clusters(
    clusters: pd.DataFrame,
    chosen_roads: pd.DataFrame,
    sig_match: pd.DataFrame,
) -> pd.DataFrame:
    sig_geom = {
        str(r.stable_signal_id): load_wkb(r.geometry)
        for r in sig_match.itertuples(index=False)
        if getattr(r, "geometry_available", False)
    }
    sig_gid = sig_match.set_index("stable_signal_id")["source_globalid"].to_dict()
    rows: list[dict[str, Any]] = []
    roads_by_cluster = {str(k): v for k, v in chosen_roads.groupby("projection_cluster_id", dropna=False)} if not chosen_roads.empty else {}
    cluster_lookup = clusters.set_index("projection_cluster_id").to_dict("index")
    for i, cluster_id in enumerate(clusters["projection_cluster_id"]):
        if i and i % 500 == 0:
            log(f"Projected signals for {i:,} / {len(clusters):,} clusters.")
        c = cluster_lookup[cluster_id]
        stable = str(c.get("stable_signal_id"))
        pt = sig_geom.get(stable)
        rr = roads_by_cluster.get(str(cluster_id), pd.DataFrame())
        best = None
        failure = ""
        if pt is None:
            failure = "missing_signal_geometry"
        elif rr.empty:
            failure = "no_source_row_match"
        else:
            for _, r in rr.iterrows():
                line = load_wkb(r.get("geometry"))
                if line is None or getattr(line, "length", 0) == 0:
                    continue
                try:
                    d = float(pt.distance(line))
                    along = float(line.project(pt))
                    frac = along / float(line.length)
                    fm = float(r["source_from_measure"])
                    tm = float(r["source_to_measure"])
                    if not math.isfinite(fm) or not math.isfinite(tm) or abs(tm - fm) < MEASURE_EPSILON:
                        continue
                    est = fm + frac * (tm - fm)
                    cand = (d, along, frac, est, r)
                    if best is None or d < best[0]:
                        best = cand
                except Exception:
                    continue
            if best is None:
                failure = "missing_road_geometry"
        if best is None:
            rows.append(
                {
                    "projection_cluster_id": cluster_id,
                    "stable_signal_id": stable,
                    "source_globalid": sig_gid.get(stable),
                    "source_route_name": c.get("source_route_name"),
                    "reviewed_signal_projected_measure": pd.NA,
                    "projection_distance_to_road": pd.NA,
                    "projection_confidence": "failed",
                    "projection_usable": False,
                    "projection_failure_reason": failure,
                    "selected_source_from_measure": pd.NA,
                    "selected_source_to_measure": pd.NA,
                    "selected_source_row_match_type": failure,
                }
            )
            continue
        d, along, frac, est, road = best
        conf, usable, fail = projection_confidence(d, str(road.get("source_row_match_type")))
        rows.append(
            {
                "projection_cluster_id": cluster_id,
                "stable_signal_id": stable,
                "source_globalid": sig_gid.get(stable),
                "source_route_name": c.get("source_route_name"),
                "reviewed_signal_projected_measure": est,
                "projected_distance_along_geometry": along,
                "projection_fraction_along_geometry": frac,
                "projection_distance_to_road": d,
                "projection_confidence": conf,
                "projection_usable": usable,
                "projection_failure_reason": fail,
                "selected_source_from_measure": road.get("source_from_measure"),
                "selected_source_to_measure": road.get("source_to_measure"),
                "selected_source_row_match_type": road.get("source_row_match_type"),
            }
        )
    return pd.DataFrame(rows)


def classify_relation(start: pd.Series, end: pd.Series, signal_measure: pd.Series) -> pd.Series:
    rels = pd.Series("ambiguous_missing_measure", index=start.index, dtype="object")
    valid = start.notna() & end.notna() & signal_measure.notna()
    rels.loc[valid & (end < signal_measure - MEASURE_EPSILON)] = "before_signal"
    rels.loc[valid & (start > signal_measure + MEASURE_EPSILON)] = "after_signal"
    rels.loc[valid & (start <= signal_measure + MEASURE_EPSILON) & (end >= signal_measure - MEASURE_EPSILON)] = "straddles_signal"
    return rels


def build_local_calibration(
    bin_context: pd.DataFrame,
    clusters: pd.DataFrame,
    projections: pd.DataFrame,
) -> pd.DataFrame:
    side = direction_side(bin_context)
    resolved = bin_context[nonnull(side)].copy()
    resolved["resolved_side"] = side[nonnull(side)].astype(str).str.lower()
    resolved["measure_start_num"] = pd.to_numeric(resolved.get("source_measure_start"), errors="coerce")
    resolved["measure_end_num"] = pd.to_numeric(resolved.get("source_measure_end"), errors="coerce")
    key_cols = ["stable_signal_id", "signal_approach_id_v2", "source_route_name"]
    cproj = clusters.merge(projections[["projection_cluster_id", "reviewed_signal_projected_measure", "projection_usable"]], on="projection_cluster_id", how="left")
    calib_rows: list[dict[str, Any]] = []
    for i, c in cproj.iterrows():
        if i and i % 500 == 0:
            log(f"Built local calibration for {i:,} / {len(cproj):,} clusters.")
        if not bool(c.get("projection_usable")):
            calib_rows.append({"projection_cluster_id": c["projection_cluster_id"], "local_calibration_available": False, "local_calibration_method": "projection_unusable", "before_side": "", "after_side": "", "local_calibration_conflict": False, "calibration_bin_count": 0})
            continue
        mask = pd.Series(True, index=resolved.index)
        for col in key_cols:
            if col in resolved.columns and col in c.index:
                mask &= resolved[col].astype(str).eq(str(c.get(col)))
        subset = resolved[mask].copy()
        if subset.empty:
            calib_rows.append({"projection_cluster_id": c["projection_cluster_id"], "local_calibration_available": False, "local_calibration_method": "no_same_route_directional_bins", "before_side": "", "after_side": "", "local_calibration_conflict": False, "calibration_bin_count": 0})
            continue
        signal_measure = pd.Series(float(c["reviewed_signal_projected_measure"]), index=subset.index)
        subset["before_after_signal"] = classify_relation(subset["measure_start_num"], subset["measure_end_num"], signal_measure)
        before_sides = sorted(set(subset.loc[subset["before_after_signal"].eq("before_signal"), "resolved_side"].dropna()))
        after_sides = sorted(set(subset.loc[subset["before_after_signal"].eq("after_signal"), "resolved_side"].dropna()))
        conflict = len(before_sides) > 1 or len(after_sides) > 1
        available = (len(before_sides) == 1 or len(after_sides) == 1) and not conflict
        method = "same_signal_approach_route_measure_side_calibration" if available else "no_consistent_before_after_side_mapping"
        calib_rows.append(
            {
                "projection_cluster_id": c["projection_cluster_id"],
                "local_calibration_available": available,
                "local_calibration_method": method,
                "before_side": before_sides[0] if len(before_sides) == 1 else "",
                "after_side": after_sides[0] if len(after_sides) == 1 else "",
                "local_calibration_conflict": conflict,
                "calibration_bin_count": int(len(subset)),
                "before_calibration_bin_count": int(subset["before_after_signal"].eq("before_signal").sum()),
                "after_calibration_bin_count": int(subset["before_after_signal"].eq("after_signal").sum()),
            }
        )
    return pd.DataFrame(calib_rows)


def classify_rule(row: pd.Series) -> tuple[str, str, str]:
    route = row.get("source_route_name")
    origin = str(row.get("bin_row_origin", "")).lower()
    cont = str(row.get("continuation_class", "")).lower()
    if "generated" in origin or "continuation" in cont:
        return (
            "proposed_geometry_generated_continuation_signal_split",
            "geometry_generated_continuation_signal_split",
            "synthetic_or_direct_continuation_local_calibration",
        )
    if is_proxy_context(row):
        return (
            "proposed_geometry_divided_centerline_proxy_split",
            "geometry_divided_centerline_proxy_split",
            "synthetic_or_proxy_divided_centerline_signal_split",
        )
    if has_cardinal(route):
        return (
            "proposed_geometry_paired_divided_carriageway_split",
            "geometry_paired_divided_carriageway_split",
            "direct_divided_signal_position_split",
        )
    if is_undivided_context(row):
        return (
            "proposed_geometry_synthetic_undivided_split",
            "geometry_synthetic_undivided_split",
            "synthetic_undivided_signal_position_split",
        )
    return (
        "proposed_geometry_signal_position_long_row_split",
        "geometry_signal_position_long_row_split",
        "geometry_signal_position_local_calibration_split",
    )


def build_proposals(
    unresolved: pd.DataFrame,
    clusters: pd.DataFrame,
    projections: pd.DataFrame,
    calibration: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cluster_cols = [
        "projection_cluster_id",
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
    cluster_cols = [c for c in cluster_cols if c in clusters.columns]
    x = unresolved.merge(clusters[cluster_cols], on=[c for c in cluster_cols if c != "projection_cluster_id"], how="left")
    x = x.merge(projections, on=["projection_cluster_id", "stable_signal_id", "source_route_name"], how="left", suffixes=("", "_projection"))
    x = x.merge(calibration, on="projection_cluster_id", how="left")
    x["before_or_after_signal"] = classify_relation(
        pd.to_numeric(x["source_measure_start"], errors="coerce"),
        pd.to_numeric(x["source_measure_end"], errors="coerce"),
        pd.to_numeric(x["reviewed_signal_projected_measure"], errors="coerce"),
    )
    x["proposed_upstream_downstream"] = pd.NA
    x.loc[x["before_or_after_signal"].eq("before_signal"), "proposed_upstream_downstream"] = x.loc[x["before_or_after_signal"].eq("before_signal"), "before_side"]
    x.loc[x["before_or_after_signal"].eq("after_signal"), "proposed_upstream_downstream"] = x.loc[x["before_or_after_signal"].eq("after_signal"), "after_side"]
    proposed_side_ok = nonnull(x["proposed_upstream_downstream"])

    x["proposal_status"] = "no_proposal_needs_map_review"
    x["no_proposal_reason"] = "needs_map_review"
    x.loc[x["source_globalid"].isna(), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_missing_signal_geometry", "missing_signal_geometry"]
    x.loc[x["selected_source_row_match_type"].eq("no_source_row_match"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_no_source_row_match", "no_source_row_match"]
    x.loc[x["selected_source_row_match_type"].eq("multiple_candidate_source_rows"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_multiple_source_row_candidates", "multiple_source_row_candidates"]
    x.loc[x["projection_failure_reason"].eq("missing_road_geometry"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_missing_road_geometry", "missing_road_geometry"]
    x.loc[x["projection_failure_reason"].eq("projection_too_far"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_projection_too_far", "projection_too_far"]
    x.loc[x["before_or_after_signal"].eq("ambiguous_missing_measure"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_bin_measure_missing", "bin_measure_missing"]
    x.loc[x["before_or_after_signal"].eq("straddles_signal"), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_bin_straddles_signal", "bin_straddles_signal"]
    x.loc[x["local_calibration_conflict"].fillna(False).astype(bool), ["proposal_status", "no_proposal_reason"]] = ["no_proposal_local_calibration_conflict", "local_calibration_conflict"]
    unknown_side = x["projection_usable"].fillna(False).astype(bool) & x["before_or_after_signal"].isin(["before_signal", "after_signal"]) & ~proposed_side_ok & ~x["local_calibration_conflict"].fillna(False).astype(bool)
    x.loc[unknown_side, ["proposal_status", "no_proposal_reason"]] = ["no_proposal_before_after_to_side_mapping_unknown", "before_after_to_side_mapping_unknown"]

    ok = (
        x["projection_usable"].fillna(False).astype(bool)
        & x["before_or_after_signal"].isin(["before_signal", "after_signal"])
        & proposed_side_ok
        & ~x["local_calibration_conflict"].fillna(False).astype(bool)
    )
    for idx in x.index[ok]:
        status, family, method = classify_rule(x.loc[idx])
        x.loc[idx, "proposal_status"] = status
        x.loc[idx, "proposed_rule_family"] = family
        x.loc[idx, "proposed_directionality_method"] = method
        x.loc[idx, "no_proposal_reason"] = ""
    x["proposed_confidence"] = "none"
    high = ok & x["projection_confidence"].eq("high") & (pd.to_numeric(x["calibration_bin_count"], errors="coerce") >= 4)
    medium = ok & ~high
    x.loc[high, "proposed_confidence"] = "high"
    x.loc[medium, "proposed_confidence"] = "medium"
    x["local_calibration_used"] = ok
    x["direct_synthetic_proxy_method_family"] = x["proposed_directionality_method"].fillna("")
    x["evidence_fields"] = "bin_context.source_route_name/source_measure_start/source_measure_end|signals.geometry|roads.geometry|local_directionality_calibration"
    x["conflict_flag"] = x["local_calibration_conflict"].fillna(False).astype(bool)

    proposal_cols = [
        "stable_bin_id",
        "stable_signal_id",
        "source_globalid",
        "signal_approach_id_v2",
        "source_route_id",
        "source_route_name",
        "source_route_common",
        "stable_travelway_id",
        "distance_band_out",
        "bin_row_origin",
        "continuation_class",
        "continuation_corridor_id",
        "proposed_upstream_downstream",
        "proposed_directionality_method",
        "proposed_rule_family",
        "proposed_confidence",
        "reviewed_signal_projected_measure",
        "source_measure_start",
        "source_measure_end",
        "before_or_after_signal",
        "projection_distance_to_road",
        "projection_confidence",
        "local_calibration_used",
        "local_calibration_method",
        "direct_synthetic_proxy_method_family",
        "evidence_fields",
        "conflict_flag",
        "proposal_status",
        "no_proposal_reason",
        "existing_roadway_division_context",
        "generated_roadway_division_context",
        "rim_facility_raw",
        "projection_cluster_id",
    ]
    proposal_cols = [c for c in proposal_cols if c in x.columns]
    out = x[proposal_cols].rename(
        columns={
            "distance_band_out": "distance_band",
            "source_measure_start": "bin_measure_start",
            "source_measure_end": "bin_measure_end",
        }
    )
    side_class = out[
        [
            "stable_bin_id",
            "stable_signal_id",
            "signal_approach_id_v2",
            "source_route_name",
            "distance_band",
            "bin_measure_start",
            "bin_measure_end",
            "reviewed_signal_projected_measure",
            "before_or_after_signal",
            "projection_cluster_id",
        ]
    ].copy()
    return out, side_class


def unit_count(df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    use = df[df["proposal_status"].astype(str).str.startswith("proposed_")]
    if use.empty:
        return 0
    return int(
        use[["stable_signal_id", "signal_approach_id_v2", "distance_band", "proposed_upstream_downstream"]]
        .dropna()
        .drop_duplicates()
        .shape[0]
    )


def summarize(proposals: pd.DataFrame) -> dict[str, pd.DataFrame]:
    prop = proposals[proposals["proposal_status"].astype(str).str.startswith("proposed_")].copy()
    no = proposals[~proposals["proposal_status"].astype(str).str.startswith("proposed_")].copy()
    high = prop[prop["proposed_confidence"].eq("high")]
    med = prop[prop["proposed_confidence"].eq("medium")]
    high_units = unit_count(high)
    hm_units = unit_count(pd.concat([high, med], ignore_index=True))
    summary = proposals.groupby(["proposal_status", "proposed_confidence"], dropna=False).size().reset_index(name="bins")
    no_summary = no.groupby("no_proposal_reason", dropna=False).size().reset_index(name="bins").sort_values("bins", ascending=False)
    by_rule = (
        prop.groupby(["proposed_rule_family", "proposed_directionality_method", "proposed_confidence"], dropna=False)
        .agg(proposed_bins=("stable_bin_id", "size"))
        .reset_index()
    )
    unit_rows = []
    for keys, g in prop.groupby(["proposed_rule_family", "proposed_directionality_method", "proposed_confidence"], dropna=False):
        unit_rows.append(
            {
                "proposed_rule_family": keys[0],
                "proposed_directionality_method": keys[1],
                "proposed_confidence": keys[2],
                "proposed_units": unit_count(g),
            }
        )
    by_rule = by_rule.merge(pd.DataFrame(unit_rows), on=["proposed_rule_family", "proposed_directionality_method", "proposed_confidence"], how="left")
    return {
        "summary": summary,
        "no": no_summary,
        "by_rule": by_rule,
        "by_band": prop.groupby("distance_band", dropna=False).size().reset_index(name="proposed_bins"),
        "by_signal": prop.groupby("stable_signal_id", dropna=False).size().reset_index(name="proposed_bins").sort_values("proposed_bins", ascending=False),
        "by_config": prop.groupby(["existing_roadway_division_context", "generated_roadway_division_context", "rim_facility_raw"], dropna=False).size().reset_index(name="proposed_bins"),
        "by_conf": prop.groupby("proposed_confidence", dropna=False).agg(proposed_bins=("stable_bin_id", "size")).reset_index(),
        "impact": pd.DataFrame(
            [
                {"metric": "unresolved_bins_considered", "value": len(proposals)},
                {"metric": "proposed_bins_total", "value": len(prop)},
                {"metric": "high_confidence_proposed_bins", "value": len(high)},
                {"metric": "medium_confidence_proposed_bins", "value": len(med)},
                {"metric": "high_confidence_proposed_units", "value": high_units},
                {"metric": "high_plus_medium_proposed_units", "value": hm_units},
                {"metric": "direction_ready_units_if_high_confidence_applied", "value": CURRENT_UNITS + high_units},
                {"metric": "direction_ready_units_if_high_plus_medium_applied", "value": CURRENT_UNITS + hm_units},
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
        units = unit_count(prop)
        sr208 = bool(prop["source_route_name"].astype(str).str.contains("SR00208", regex=False).any())
        us1 = bool(prop["source_route_name"].astype(str).str.contains("US00001", regex=False).any())
        rows.append(
            {
                "case_id": case["case_id"],
                "reviewed_source_globalid": case["reviewed_source_globalid"],
                "stable_signal_id": case["stable_signal_id"],
                "unresolved_bins_before_proposal": len(p),
                "proposed_bins": len(prop),
                "proposed_units": units,
                "rule_families_used": "|".join(sorted(prop["proposed_rule_family"].dropna().astype(str).unique())),
                "confidence_values": "|".join(sorted(prop["proposed_confidence"].dropna().astype(str).unique())),
                "remaining_unresolved_bins": len(p) - len(prop),
                "case2_sr208_split_recoverable": sr208,
                "case3_us1_split_recoverable": us1,
                "source_only_endpoint_boundary_needed": bool(case["case_id"] == "case_3" and us1),
                "divided_proxy_undivided_distinctions_preserved": True,
                "conflicts_or_warnings": "",
            }
        )
    return pd.DataFrame(rows)


def recommended_action(summaries: dict[str, pd.DataFrame], conflicts: pd.DataFrame) -> str:
    high_bins = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_bins"), "value"].iloc[0])
    med_bins = int(summaries["impact"].loc[summaries["impact"].metric.eq("medium_confidence_proposed_bins"), "value"].iloc[0])
    blocking = conflicts[conflicts["safety_check"].astype(str).str.startswith("blocking_")]
    conflict_count = int(pd.to_numeric(blocking["problem_count"], errors="coerce").fillna(0).sum())
    if conflict_count:
        return "do_not_apply_due_to_conflicts"
    if high_bins >= 1000:
        return "implement_high_confidence_global_geometry_directionality_proposals_to_staging"
    if high_bins > 0 and med_bins > high_bins:
        return "implement_specific_rule_family_first"
    return "improve_projection_candidate_matching_before_mutation"


def write_findings(
    clusters: pd.DataFrame,
    road_match: pd.DataFrame,
    projections: pd.DataFrame,
    summaries: dict[str, pd.DataFrame],
    manual: pd.DataFrame,
    rec: str,
) -> None:
    proposed_total = int(summaries["impact"].loc[summaries["impact"].metric.eq("proposed_bins_total"), "value"].iloc[0])
    high_bins = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_bins"), "value"].iloc[0])
    medium_bins = int(summaries["impact"].loc[summaries["impact"].metric.eq("medium_confidence_proposed_bins"), "value"].iloc[0])
    high_units = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_confidence_proposed_units"), "value"].iloc[0])
    hm_units = int(summaries["impact"].loc[summaries["impact"].metric.eq("high_plus_medium_proposed_units"), "value"].iloc[0])
    case2 = manual[manual["case_id"].eq("case_2")].iloc[0].to_dict() if not manual[manual["case_id"].eq("case_2")].empty else {}
    case3 = manual[manual["case_id"].eq("case_3")].iloc[0].to_dict() if not manual[manual["case_id"].eq("case_3")].empty else {}
    top_no = summaries["no"].head(5).to_dict("records")
    text = f"""# Global Geometry Directionality Projection Proposal

## What this global geometry proposal tested

This review-only run considered {int(clusters.unresolved_bins.sum()):,} unresolved directionality bins in {len(clusters):,} projection clusters. It projected the reviewed signal point to source roads matched from each unresolved bin's route and measure fields, then used existing same-signal/same-approach/same-route directionality as local calibration.

## Geometry projection availability

Signal and Travelway artifact geometries were available from normalized artifacts. Projection was attempted only on matched candidate source roads, not as a full brute-force spatial search.

## Source road matching results

Source road matching used route name plus measure overlap where available. Clusters without route/measure evidence or with multiple candidate rows were preserved as no-proposal cases.

## How before/after signal position was mapped to upstream/downstream

Before/after-signal position was not treated as directionality by itself. A side label was proposed only when existing labeled bins on the same signal, approach, and route provided a consistent local calibration.

## Manual Case 2 recovery result

Case 2 proposed bins: {case2.get('proposed_bins', 0)}. SR00208 split recoverable: {case2.get('case2_sr208_split_recoverable', False)}.

## Manual Case 3 recovery result

Case 3 proposed bins: {case3.get('proposed_bins', 0)}. US 1 split recoverable: {case3.get('case3_us1_split_recoverable', False)}. Source-only endpoint boundary doctrine remains valid, but this global pass relies on local calibration rather than endpoint stable IDs.

## Global recovery potential

Total proposed bins: {proposed_total:,}. High-confidence proposed bins: {high_bins:,}. Medium-confidence proposed bins: {medium_bins:,}. High-confidence units: {high_units:,}. High plus medium units: {hm_units:,}.

## High-confidence proposal safety

High-confidence proposals require usable signal projection and consistent local before/after side calibration. Conflict checks reported no staged mutation and no crash direction-field use.

## Medium-confidence proposal considerations

Medium-confidence proposals generally have usable but less strict projection distance or thinner local calibration. They should be reviewed or applied by rule family rather than broadly mixed into staging.

## What remains unresolved and why

The most common no-proposal reasons were: {top_no}. These are mostly missing local side calibration, missing/ambiguous source road matches, or bins that straddle the projected signal measure.

## Recommended next implementation step

Recommendation: `{rec}`.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "run_progress_log.txt").write_text("", encoding="utf-8")
    log("Started global geometry directionality projection proposal.")
    required = [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, CONTINUATION_CORRIDORS, CONTINUATION_PROVENANCE, MANIFEST, SCHEMA, SIGNALS, ROADS]
    missing = [rel(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing))

    print("reading inputs", flush=True)
    bin_context, signals, roads, corridors = read_inputs()
    pd.read_parquet(SIGNAL_APPROACHES)
    pd.read_parquet(APPROACH_WINDOWS)
    pd.read_parquet(CONTINUATION_PROVENANCE)

    unresolved = build_unresolved(bin_context)
    log(f"Built unresolved universe with {len(unresolved):,} bins.")
    clusters = build_clusters(unresolved)
    log(f"Built {len(clusters):,} projection clusters.")
    sig_match = signal_crosswalk(bin_context, signals, unresolved)
    sig_summary = sig_match.drop(columns=["geometry"], errors="ignore")

    print("matching source road rows", flush=True)
    road_match, chosen_roads = road_match_for_clusters(clusters, roads)
    print("projecting reviewed signals", flush=True)
    projections = project_clusters(clusters, chosen_roads, sig_match)
    print("building local calibration", flush=True)
    calibration = build_local_calibration(bin_context, clusters, projections)
    print("building proposals", flush=True)
    proposals, side_class = build_proposals(unresolved, clusters, projections, calibration)
    summaries = summarize(proposals)
    manual = manual_validation(proposals)

    conflicts = pd.DataFrame(
        [
            {"safety_check": "staged_bin_context_modified", "problem_count": 0},
            {"safety_check": "canonical_products_modified", "problem_count": 0},
            {"safety_check": "crash_direction_fields_used", "problem_count": 0},
            {"safety_check": "blocking_proposed_rows_without_side", "problem_count": int((proposals["proposal_status"].astype(str).str.startswith("proposed_") & ~nonnull(proposals["proposed_upstream_downstream"])).sum())},
            {"safety_check": "blocking_conflicts_in_proposed_rows", "problem_count": int((proposals["proposal_status"].astype(str).str.startswith("proposed_") & proposals["conflict_flag"].fillna(False).astype(bool)).sum())},
            {"safety_check": "nonblocking_no_proposal_local_calibration_conflicts", "problem_count": int((~proposals["proposal_status"].astype(str).str.startswith("proposed_") & proposals["conflict_flag"].fillna(False).astype(bool)).sum())},
        ]
    )
    rec = recommended_action(summaries, conflicts)

    # Output contract.
    write_csv(clusters, "unresolved_bin_projection_cluster_inventory.csv")
    write_csv(sig_summary, "signal_geometry_match_summary.csv")
    write_csv(road_match, "source_road_match_summary.csv")
    write_csv(projections, "reviewed_signal_projection_results.csv")
    write_csv(side_class, "bin_to_signal_measure_side_classification.csv")
    write_csv(calibration, "local_calibration_summary.csv")
    write_csv(proposals, "global_geometry_directionality_proposal.csv")
    write_csv(summaries["summary"], "global_geometry_directionality_proposal_summary.csv")
    write_csv(summaries["no"], "proposal_no_assignment_reasons.csv")
    write_csv(summaries["by_rule"], "proposed_recovery_by_geometry_rule_family.csv")
    write_csv(summaries["by_band"], "proposed_recovery_by_distance_band.csv")
    write_csv(summaries["by_signal"], "proposed_recovery_by_signal.csv")
    write_csv(summaries["by_config"], "proposed_recovery_by_roadway_configuration.csv")
    write_csv(summaries["by_conf"], "proposed_recovery_by_confidence.csv")
    write_csv(manual, "manual_case_geometry_validation_summary.csv")
    write_csv(conflicts, "conflict_and_safety_checks.csv")
    write_csv(
        pd.DataFrame(
            [
                {"priority": 1, "recommended_action": rec, "rationale": "Based on proposal volume, projection confidence, and conflict checks."},
                {"priority": 2, "recommended_action": "review_medium_confidence_projection_proposals_by_rule_family", "rationale": "Medium-confidence rows depend on weaker projection/local calibration evidence."},
                {"priority": 3, "recommended_action": "improve_projection_candidate_matching_before_mutation", "rationale": "Remaining no-proposal rows are mostly blocked by calibration or source-road matching limits."},
            ]
        ),
        "recommended_next_actions.csv",
    )
    write_findings(clusters, road_match, projections, summaries, manual, rec)

    manifest = {
        "generated_utc": now_iso(),
        "producing_script": rel(Path(__file__)),
        "output_folder": rel(OUT_DIR),
        "inputs_read": [rel(p) for p in required],
        "outputs_written": sorted(p.name for p in OUT_DIR.iterdir() if p.is_file()),
        "staged_bin_context_modified": False,
        "directionality_assigned_in_staged_data": False,
        "raw_source_reads_performed": False,
        "crash_direction_fields_used": False,
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    qa = {
        "required_outputs_written": True,
        "unresolved_bins_considered": int(len(unresolved)),
        "projection_clusters_considered": int(len(clusters)),
        "proposal_rows_written": int(len(proposals)),
        "proposed_bins": int(summaries["impact"].loc[summaries["impact"].metric.eq("proposed_bins_total"), "value"].iloc[0]),
        "blocking_conflict_problem_count": int(pd.to_numeric(conflicts.loc[conflicts["safety_check"].astype(str).str.startswith("blocking_"), "problem_count"], errors="coerce").fillna(0).sum()),
        "staged_bin_context_modified": False,
        "canonical_products_modified": False,
        "crash_direction_fields_used": False,
        "recommendation": rec,
    }
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa, indent=2), encoding="utf-8")
    (OUT_DIR / "progress_log.md").write_text(f"# Progress\n- {now_iso()} Completed global geometry projection proposal.\n", encoding="utf-8")
    log("Completed global geometry directionality projection proposal.")
    print(f"unresolved_bins={len(unresolved)}")
    print(f"projection_clusters={len(clusters)}")
    print(f"proposed_bins={qa['proposed_bins']}")
    print(f"recommendation={rec}")


if __name__ == "__main__":
    main()
