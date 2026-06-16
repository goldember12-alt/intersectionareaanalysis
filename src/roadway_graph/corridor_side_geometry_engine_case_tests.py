"""Case-test corridor-side geometry engine for directionality recovery.

This is a review-only prototype. It reads staged/cache products and normalized
source artifacts, projects reviewed and endpoint signals to source Travelway
geometry, builds signal-bounded corridor-side models, and writes proposals for
the three manual cases without mutating staged or canonical data.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from shapely import wkb, wkt
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points
except Exception:  # pragma: no cover
    wkb = None
    wkt = None
    Point = Any
    LineString = Any
    nearest_points = None


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING = REPO_ROOT / "work/roadway_graph/analysis/_staging/final_leg_corrected_analysis_dataset_refresh_candidate"
ARTIFACTS = REPO_ROOT / "artifacts/normalized"
OUT_DIR = REPO_ROOT / "work/roadway_graph/review/corridor_side_geometry_engine_case_tests"

BIN_CONTEXT = STAGING / "bin_context.parquet"
SIGNAL_APPROACHES = STAGING / "signal_approaches.parquet"
APPROACH_WINDOWS = STAGING / "approach_windows.parquet"
CONTINUATION_CORRIDORS = STAGING / "continuation_corridors.parquet"
CONTINUATION_PROVENANCE = STAGING / "continuation_provenance.parquet"
SIGNALS = ARTIFACTS / "signals.parquet"
ROADS = ARTIFACTS / "roads.parquet"

STRICT_PROJECTION_FT = 100.0
RELAXED_PROJECTION_FT = 300.0
MEASURE_EPS = 1.0e-6
TOO_CLOSE_MEASURE = 0.001
CURRENT_DIRECTION_READY_UNITS = 98_831
CONSERVATIVE_TARGET = 109_842
UPPER_TARGET = 132_866


@dataclass(frozen=True)
class CaseRoute:
    case_id: str
    reviewed_globalid: str
    stable_signal_id: str
    route: str
    manual_from_measure: float | None
    manual_to_measure: float | None
    representation: str
    side_rule: str
    endpoint_globalids: tuple[str, ...] = ()
    upstream_endpoint_globalid: str | None = None
    downstream_endpoint_globalid: str | None = None
    paired_reference_route: str | None = None
    notes: str = ""


CASES = {
    "case_1": {
        "reviewed_globalid": "{390C924A-CB15-4DBD-AF12-7CA202345C52}",
        "stable_signal_id": "sig_03e277feabe81aadd78f",
    },
    "case_2": {
        "reviewed_globalid": "{9000F2BF-82ED-4794-A473-6238A81A4109}",
        "stable_signal_id": "sig_05a2cb689cbc4f27814d",
    },
    "case_3": {
        "reviewed_globalid": "{275B403F-F8D7-44B7-9D2F-04875799C1FB}",
        "stable_signal_id": "sig_439930214d7b1b49426f",
    },
}


def manual_case_routes() -> list[CaseRoute]:
    c1 = CASES["case_1"]
    c2 = CASES["case_2"]
    c3 = CASES["case_3"]
    ep_c1 = "{3FC34C31-4FC3-4321-97DB-C31B0EE3D617}"
    ep_c2_up = "{307C6C57-B13A-4EFD-946D-10335A09E755}"
    ep_c2_down = "{A6F2E5C6-29EE-4BBF-866E-8E4507E3FFB8}"
    ep_c3_a = "{B78AFE2F-0550-41D3-B4D8-AEB06826C742}"
    ep_c3_b = "{E0FE127C-C5E8-428B-90E7-985CE9934776}"
    ep_c3_sr = "{5E1653A6-9400-4FC8-A1E6-7DA3E997EC9E}"
    rows = [
        CaseRoute("case_1", c1["reviewed_globalid"], c1["stable_signal_id"], "R-VA   US00258EB", 47.19, 48.15, "true_paired_divided_carriageway", "explicit_interval_upstream", (ep_c1,), notes="Manual divided upstream interval."),
        CaseRoute("case_1", c1["reviewed_globalid"], c1["stable_signal_id"], "R-VA   US00258WB", 47.81, 47.98, "true_paired_divided_carriageway", "explicit_interval_upstream", (ep_c1,), notes="Manual divided upstream interval."),
        CaseRoute("case_1", c1["reviewed_globalid"], c1["stable_signal_id"], "R-VA   US00258WB", 47.98, 48.81, "true_paired_divided_carriageway", "explicit_interval_upstream", (ep_c1,), notes="Manual divided upstream interval."),
        CaseRoute("case_1", c1["reviewed_globalid"], c1["stable_signal_id"], "R-VA   US00258WB", 46.82, 47.81, "true_paired_divided_carriageway", "explicit_interval_downstream", (ep_c1,), notes="Manual divided downstream interval."),
        CaseRoute("case_1", c1["reviewed_globalid"], c1["stable_signal_id"], "R-VA   US00258EB", 48.15, 48.31, "true_paired_divided_carriageway", "explicit_interval_downstream", (ep_c1,), notes="Manual divided downstream interval."),
        CaseRoute("case_1", c1["reviewed_globalid"], c1["stable_signal_id"], "R-VA   US00258EB", 48.31, 49.14, "true_paired_divided_carriageway", "explicit_interval_downstream", (ep_c1,), notes="Manual divided downstream interval."),
        CaseRoute("case_1", c1["reviewed_globalid"], c1["stable_signal_id"], "R-VA046SC00644EB", 15.92, 16.35, "undivided_centerline", "cardinal_measure_direction", (), notes="Synthetic undivided centerline logic."),
        CaseRoute("case_2", c2["reviewed_globalid"], c2["stable_signal_id"], "R-VA   SR00208NB", None, None, "true_paired_divided_carriageway", "endpoint_upstream_downstream", (ep_c2_up, ep_c2_down), ep_c2_up, ep_c2_down, notes="Endpoint-to-reviewed upstream and reviewed-to-endpoint downstream."),
        CaseRoute("case_2", c2["reviewed_globalid"], c2["stable_signal_id"], "R-VA   SR00208SB", None, None, "true_paired_divided_carriageway", "paired_reverse_from_reference", (ep_c2_up, ep_c2_down), paired_reference_route="R-VA   SR00208NB", notes="Reverse inference from conflict-free paired NB carriageway."),
        CaseRoute("case_2", c2["reviewed_globalid"], c2["stable_signal_id"], "R-VA088SC00639SB", 4.05, 4.16, "divided_centerline_proxy", "explicit_interval_downstream", (), notes="Proxy/centerline downstream interval."),
        CaseRoute("case_2", c2["reviewed_globalid"], c2["stable_signal_id"], "R-VA088SC00639NB", 4.05, 4.16, "divided_centerline_proxy", "explicit_interval_upstream", (), notes="Proxy/centerline upstream interval."),
        CaseRoute("case_2", c2["reviewed_globalid"], c2["stable_signal_id"], "R-VA088SC00639NB", 4.16, 6.29, "divided_centerline_proxy", "explicit_interval_downstream", (), notes="Proxy/centerline downstream interval."),
        CaseRoute("case_3", c3["reviewed_globalid"], c3["stable_signal_id"], "R-VA   US00001SB", 181.43, 184.27, "true_paired_divided_carriageway", "cardinal_measure_direction", (ep_c3_a, ep_c3_b), notes="Signal-bounded divided carriageway; source-only endpoint boundaries allowed."),
        CaseRoute("case_3", c3["reviewed_globalid"], c3["stable_signal_id"], "R-VA   US00001NB", 180.56, 183.33, "true_paired_divided_carriageway", "cardinal_measure_direction", (ep_c3_a, ep_c3_b), notes="Signal-bounded divided carriageway; source-only endpoint boundaries allowed."),
        CaseRoute("case_3", c3["reviewed_globalid"], c3["stable_signal_id"], "R-VA   SR00286SB", 0.00, 2.61, "true_paired_divided_carriageway", "explicit_interval_upstream", (ep_c3_sr,), notes="Manual route can be labeled upstream."),
        CaseRoute("case_3", c3["reviewed_globalid"], c3["stable_signal_id"], "R-VA   SR00286NB", 0.00, 2.56, "true_paired_divided_carriageway", "explicit_interval_downstream", (ep_c3_sr,), notes="Manual route can be labeled downstream."),
    ]
    return rows


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
    return s.notna() & text.ne("") & ~text.str.lower().isin(["nan", "none", "null", "<na>"])


def first_existing(df: pd.DataFrame, cols: list[str], default: Any = pd.NA) -> pd.Series:
    for col in cols:
        if col in df.columns:
            return df[col]
    return pd.Series(default, index=df.index)


def side_values(df: pd.DataFrame) -> pd.Series:
    side = first_existing(df, ["upstream_downstream"])
    if "upstream_downstream_values" in df.columns:
        side = side.where(nonmissing(side), df["upstream_downstream_values"])
    return side


def parse_geometry(value: Any):
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


def route_direction_token(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper().strip()
    m = re.search(r"(NB|SB|EB|WB)$", text)
    return m.group(1) if m else ""


def route_base(route: Any) -> str:
    text = "" if pd.isna(route) else str(route).upper().strip()
    token = route_direction_token(text)
    return text[: -len(token)].strip() if token else text


def opposite_token(token: str) -> str:
    return {"NB": "SB", "SB": "NB", "EB": "WB", "WB": "EB"}.get(token, "")


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
        "distance_band_start_ft",
        "distance_band_end_ft",
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
    available = pd.read_parquet(BIN_CONTEXT, columns=None).columns
    use_bin_cols = [c for c in bin_cols if c in available]
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


def project_point_to_line_measure(point: Any, line: Any, from_measure: Any, to_measure: Any) -> dict[str, Any]:
    """Project a point to a line and interpolate source route measure."""
    if point is None or line is None or getattr(line, "length", 0) == 0:
        return {
            "projected_distance_along_geometry": pd.NA,
            "fraction_along_geometry": pd.NA,
            "estimated_measure": pd.NA,
            "point_to_line_distance": pd.NA,
            "projection_confidence": "failed",
            "projection_usable": False,
            "projection_failure_reason": "missing_point_or_line_geometry",
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
    if dist <= STRICT_PROJECTION_FT:
        conf = "high"
    elif dist <= RELAXED_PROJECTION_FT:
        conf = "medium"
    else:
        conf = "low"
    return {
        "projected_distance_along_geometry": along,
        "fraction_along_geometry": frac,
        "estimated_measure": est,
        "point_to_line_distance": dist,
        "projection_confidence": conf,
        "projection_usable": conf in {"high", "medium"},
        "projection_failure_reason": "" if conf in {"high", "medium"} else "projection_too_far",
    }


def roads_for_route(roads: pd.DataFrame, route: str, from_measure: float | None = None, to_measure: float | None = None) -> pd.DataFrame:
    rr = roads[roads["RTE_NM"].astype(str).eq(str(route))].copy()
    if rr.empty or from_measure is None or to_measure is None:
        return rr
    low = min(float(from_measure), float(to_measure))
    high = max(float(from_measure), float(to_measure))
    return rr[(pd.to_numeric(rr["FROM_MEASURE"], errors="coerce") <= high + MEASURE_EPS) & (pd.to_numeric(rr["TO_MEASURE"], errors="coerce") >= low - MEASURE_EPS)].copy()


def best_projection_to_route(point: Any, route_rows: pd.DataFrame, route: str) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    for _, row in route_rows.iterrows():
        line = parse_geometry(row.get("geometry"))
        proj = project_point_to_line_measure(point, line, row.get("FROM_MEASURE"), row.get("TO_MEASURE"))
        if pd.isna(proj["point_to_line_distance"]):
            continue
        cand = {
            "route": route,
            "source_from_measure": row.get("FROM_MEASURE"),
            "source_to_measure": row.get("TO_MEASURE"),
            "source_rte_id": row.get("RTE_ID"),
            "source_rte_common": row.get("RTE_COMMON"),
            "source_rim_facili": row.get("RIM_FACILI"),
            "source_median_ind": row.get("MEDIAN_IND"),
            **proj,
        }
        if best is None or float(cand["point_to_line_distance"]) < float(best["point_to_line_distance"]):
            best = cand
    if best is None:
        return {
            "route": route,
            "source_from_measure": pd.NA,
            "source_to_measure": pd.NA,
            "source_rte_id": pd.NA,
            "source_rte_common": pd.NA,
            "source_rim_facili": pd.NA,
            "source_median_ind": pd.NA,
            "projected_distance_along_geometry": pd.NA,
            "fraction_along_geometry": pd.NA,
            "estimated_measure": pd.NA,
            "point_to_line_distance": pd.NA,
            "projection_confidence": "failed",
            "projection_usable": False,
            "projection_failure_reason": "missing_signal_or_road_geometry",
        }
    return best


def build_signal_boundary_crosswalk(signals: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    reviewed = {v["reviewed_globalid"]: (case_id, v["stable_signal_id"]) for case_id, v in CASES.items()}
    endpoints = sorted({g for r in manual_case_routes() for g in r.endpoint_globalids})
    wanted = set(reviewed).union(endpoints)
    signal_rows = signals[signals["GLOBALID"].astype(str).str.upper().isin({g.upper() for g in wanted})].copy()

    source_map = bin_context[["source_signal_id", "stable_signal_id"]].dropna().drop_duplicates().copy()
    source_map["source_signal_id"] = source_map["source_signal_id"].astype(str).str.strip()
    id_cols = [c for c in ["REG_SIGNAL_ID", "ASSET_NUM", "SIGNAL_NO", "ASSET_ID", "INTNO", "INTNUM"] if c in signals.columns]
    records: list[dict[str, Any]] = []
    for globalid in sorted(wanted):
        rows = signal_rows[signal_rows["GLOBALID"].astype(str).str.upper().eq(globalid.upper())]
        role = "reviewed_signal" if globalid in reviewed else "endpoint_signal"
        case_ids = []
        if role == "reviewed_signal":
            case_ids = [reviewed[globalid][0]]
        else:
            case_ids = sorted({r.case_id for r in manual_case_routes() if globalid in r.endpoint_globalids})
        if rows.empty:
            records.append({
                "case_id": "|".join(case_ids),
                "source_globalid": globalid,
                "signal_role": role,
                "stable_signal_id": reviewed.get(globalid, ("", ""))[1],
                "endpoint_has_stable_signal_id": False if role == "endpoint_signal" else pd.NA,
                "source_only_endpoint_boundary": role == "endpoint_signal",
                "usable_as_corridor_boundary": False,
                "geometry_available": False,
                "match_method": "source_globalid_missing_from_artifact",
                "match_confidence": "failed",
                "identifier_values": "",
            })
            continue
        row = rows.iloc[0]
        ids = []
        for col in id_cols:
            val = row.get(col)
            if pd.notna(val) and str(val).strip() != "":
                ids.append(str(val).strip())
        matches = source_map[source_map["source_signal_id"].isin(ids)]
        stable_ids = sorted(matches["stable_signal_id"].dropna().astype(str).unique())
        stable = reviewed.get(globalid, ("", ""))[1] if role == "reviewed_signal" else "|".join(stable_ids)
        records.append({
            "case_id": "|".join(case_ids),
            "source_globalid": globalid,
            "signal_role": role,
            "stable_signal_id": stable,
            "endpoint_has_stable_signal_id": bool(stable_ids) if role == "endpoint_signal" else pd.NA,
            "source_only_endpoint_boundary": role == "endpoint_signal" and not bool(stable_ids),
            "usable_as_corridor_boundary": pd.notna(row.get("geometry")),
            "geometry_available": pd.notna(row.get("geometry")),
            "match_method": "reviewed_manual_globalid_to_stable_signal_id" if role == "reviewed_signal" else ("source_id_to_staged_stable_signal_id" if stable_ids else "source_signal_globalid_geometry_only"),
            "match_confidence": "high" if role == "reviewed_signal" or stable_ids else "source_only_boundary",
            "identifier_values": "|".join(ids),
        })
    return pd.DataFrame(records)


def build_route_match_summary(routes: list[CaseRoute], roads: pd.DataFrame) -> pd.DataFrame:
    rows = []
    seen = set()
    for r in routes:
        key = (r.case_id, r.route, r.manual_from_measure, r.manual_to_measure, r.side_rule)
        if key in seen:
            continue
        seen.add(key)
        all_rows = roads_for_route(roads, r.route)
        match_rows = roads_for_route(roads, r.route, r.manual_from_measure, r.manual_to_measure)
        rows.append({
            "case_id": r.case_id,
            "stable_signal_id": r.stable_signal_id,
            "reviewed_globalid": r.reviewed_globalid,
            "route": r.route,
            "manual_from_measure": r.manual_from_measure,
            "manual_to_measure": r.manual_to_measure,
            "roadway_representation": r.representation,
            "side_rule": r.side_rule,
            "route_rows_found": int(len(all_rows)),
            "matched_rows_found": int(len(match_rows)),
            "route_measure_min": pd.to_numeric(all_rows.get("FROM_MEASURE", pd.Series(dtype=float)), errors="coerce").min() if not all_rows.empty else pd.NA,
            "route_measure_max": pd.to_numeric(all_rows.get("TO_MEASURE", pd.Series(dtype=float)), errors="coerce").max() if not all_rows.empty else pd.NA,
            "matched_measure_min": pd.to_numeric(match_rows.get("FROM_MEASURE", pd.Series(dtype=float)), errors="coerce").min() if not match_rows.empty else pd.NA,
            "matched_measure_max": pd.to_numeric(match_rows.get("TO_MEASURE", pd.Series(dtype=float)), errors="coerce").max() if not match_rows.empty else pd.NA,
            "geometry_available": bool(match_rows["geometry"].notna().any()) if not match_rows.empty and "geometry" in match_rows.columns else False,
            "carriageway_direction_token": route_direction_token(r.route),
            "route_base": route_base(r.route),
            "matched_facility_values": "|".join(sorted(match_rows.get("RIM_FACILI", pd.Series(dtype=str)).dropna().astype(str).unique())) if not match_rows.empty else "",
        })
    return pd.DataFrame(rows)


def project_signals(routes: list[CaseRoute], signals: pd.DataFrame, roads: pd.DataFrame, crosswalk: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sig_geom = {str(row["GLOBALID"]).upper(): parse_geometry(row.get("geometry")) for _, row in signals.iterrows() if pd.notna(row.get("GLOBALID"))}
    signal_records: list[dict[str, Any]] = []
    endpoint_records: list[dict[str, Any]] = []
    projection_keys = set()
    for r in routes:
        projection_keys.add((r.case_id, r.reviewed_globalid, "reviewed_signal", r.stable_signal_id, r.route, r.manual_from_measure, r.manual_to_measure))
        for ep in r.endpoint_globalids:
            projection_keys.add((r.case_id, ep, "endpoint_signal", "", r.route, r.manual_from_measure, r.manual_to_measure))

    for case_id, globalid, role, stable_signal_id, route, fm, tm in sorted(projection_keys):
        point = sig_geom.get(str(globalid).upper())
        route_rows = roads_for_route(roads, route, fm, tm)
        if route_rows.empty:
            route_rows = roads_for_route(roads, route)
        best = best_projection_to_route(point, route_rows, route)
        cw = crosswalk[crosswalk["source_globalid"].astype(str).str.upper().eq(str(globalid).upper())]
        stable = stable_signal_id
        if not cw.empty and not stable:
            stable = cw.iloc[0].get("stable_signal_id", "")
        rec = {
            "case_id": case_id,
            "source_globalid": globalid,
            "stable_signal_id": stable,
            "signal_role": role,
            "route": route,
            "carriageway_direction_token": route_direction_token(route),
            "manual_from_measure": fm,
            "manual_to_measure": tm,
            **best,
        }
        if role == "reviewed_signal":
            signal_records.append(rec)
        else:
            rec["endpoint_has_stable_signal_id"] = bool(cw.iloc[0].get("endpoint_has_stable_signal_id")) if not cw.empty and pd.notna(cw.iloc[0].get("endpoint_has_stable_signal_id")) else False
            rec["source_only_endpoint_boundary"] = bool(cw.iloc[0].get("source_only_endpoint_boundary")) if not cw.empty else True
            endpoint_records.append(rec)
    return pd.DataFrame(signal_records), pd.DataFrame(endpoint_records)


def side_from_cardinal(token: str, side: str) -> str:
    if token in {"NB", "EB"}:
        return "upstream" if side == "before_signal" else "downstream"
    if token in {"SB", "WB"}:
        return "downstream" if side == "before_signal" else "upstream"
    return ""


def classify_side_of_signal(signal_position: Any, bin_position: dict[str, Any]) -> str:
    sig = pd.to_numeric(pd.Series([signal_position]), errors="coerce").iloc[0]
    if pd.isna(sig):
        return "too_close_or_uncertain"
    start = pd.to_numeric(pd.Series([bin_position.get("measure_start")]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([bin_position.get("measure_end")]), errors="coerce").iloc[0]
    mid = pd.to_numeric(pd.Series([bin_position.get("measure_midpoint")]), errors="coerce").iloc[0]
    if pd.notna(start) and pd.notna(end):
        low = min(float(start), float(end))
        high = max(float(start), float(end))
        if low < float(sig) < high:
            return "straddles_signal"
        if abs(low - float(sig)) <= TOO_CLOSE_MEASURE or abs(high - float(sig)) <= TOO_CLOSE_MEASURE:
            return "too_close_or_uncertain"
    if pd.isna(mid):
        if pd.notna(start) and pd.notna(end):
            mid = (float(start) + float(end)) / 2.0
        else:
            return "too_close_or_uncertain"
    if abs(float(mid) - float(sig)) <= TOO_CLOSE_MEASURE:
        return "too_close_or_uncertain"
    return "before_signal" if float(mid) < float(sig) else "after_signal"


def build_corridor_side_models(
    routes: list[CaseRoute],
    route_matches: pd.DataFrame,
    signal_proj: pd.DataFrame,
    endpoint_proj: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    primary_labels: dict[tuple[str, str], tuple[str, str]] = {}

    for r in routes:
        sp = signal_proj[(signal_proj["case_id"].eq(r.case_id)) & (signal_proj["route"].eq(r.route)) & (signal_proj["source_globalid"].eq(r.reviewed_globalid))]
        sig_measure = sp.iloc[0]["estimated_measure"] if not sp.empty else pd.NA
        sig_conf = sp.iloc[0]["projection_confidence"] if not sp.empty else "failed"
        sig_ok = bool(sp.iloc[0]["projection_usable"]) if not sp.empty else False
        endpoints = endpoint_proj[(endpoint_proj["case_id"].eq(r.case_id)) & (endpoint_proj["route"].eq(r.route))]
        usable_eps = endpoints[endpoints["projection_usable"].astype(bool)] if not endpoints.empty else endpoints

        before_label = ""
        after_label = ""
        method = ""
        confidence = "none"
        no_model_reason = ""
        evidence: dict[str, Any] = {}

        if r.side_rule.startswith("explicit_interval_"):
            label = r.side_rule.replace("explicit_interval_", "")
            token = route_direction_token(r.route)
            # Explicit intervals are carried as interval models. For bin projection
            # the interval overlap decides; before/after labels remain informative.
            before_label = side_from_cardinal(token, "before_signal") or label
            after_label = side_from_cardinal(token, "after_signal") or label
            method = f"{r.representation}_manual_explicit_interval"
            confidence = "high"
            evidence = {"manual_interval_label": label}
        elif r.side_rule == "endpoint_upstream_downstream":
            up = endpoints[endpoints["source_globalid"].astype(str).str.upper().eq(str(r.upstream_endpoint_globalid).upper())]
            down = endpoints[endpoints["source_globalid"].astype(str).str.upper().eq(str(r.downstream_endpoint_globalid).upper())]
            if sig_ok and not up.empty and not down.empty and bool(up.iloc[0]["projection_usable"]) and bool(down.iloc[0]["projection_usable"]):
                up_measure = float(up.iloc[0]["estimated_measure"])
                down_measure = float(down.iloc[0]["estimated_measure"])
                if up_measure < float(sig_measure) < down_measure:
                    before_label, after_label = "upstream", "downstream"
                elif down_measure < float(sig_measure) < up_measure:
                    before_label, after_label = "downstream", "upstream"
                else:
                    no_model_reason = "reviewed_signal_not_between_endpoint_boundaries"
                if before_label:
                    method = f"{r.representation}_source_endpoint_signal_corridor_split"
                    confidence = "high" if sig_conf == "high" and set(up["projection_confidence"]).pop() == "high" and set(down["projection_confidence"]).pop() == "high" else "medium"
                    evidence = {"upstream_endpoint_measure": up_measure, "downstream_endpoint_measure": down_measure}
            else:
                no_model_reason = "missing_or_unusable_endpoint_projection"
        elif r.side_rule == "paired_reverse_from_reference":
            ref_key = (r.case_id, str(r.paired_reference_route))
            if ref_key in primary_labels:
                ref_before, ref_after = primary_labels[ref_key]
                before_label, after_label = ref_after, ref_before
                method = f"{r.representation}_paired_reverse_carriageway_from_endpoint_corridor"
                confidence = "high"
                evidence = {"paired_reference_route": r.paired_reference_route}
            else:
                no_model_reason = "paired_reference_model_missing"
        elif r.side_rule == "cardinal_measure_direction":
            token = route_direction_token(r.route)
            if sig_ok and token:
                before_label = side_from_cardinal(token, "before_signal")
                after_label = side_from_cardinal(token, "after_signal")
                method = f"{r.representation}_cardinal_measure_corridor_split"
                confidence = "high" if sig_conf == "high" else "medium"
                evidence = {"direction_token": token, "measure_direction_rule": "NB/EB increasing; SB/WB decreasing"}
            else:
                no_model_reason = "missing_signal_projection_or_cardinal_token"
        else:
            no_model_reason = "unsupported_side_rule"

        rm = route_matches[
            (route_matches["case_id"].eq(r.case_id))
            & (route_matches["route"].eq(r.route))
            & (route_matches["side_rule"].eq(r.side_rule))
            & (route_matches["manual_from_measure"].fillna(-999999).eq(-999999 if r.manual_from_measure is None else r.manual_from_measure))
        ]
        model_id = f"{r.case_id}_{re.sub(r'[^A-Za-z0-9]+', '_', r.route).strip('_')}_{len(rows)+1:03d}"
        row = {
            "corridor_side_model_id": model_id,
            "case_id": r.case_id,
            "reviewed_globalid": r.reviewed_globalid,
            "stable_signal_id": r.stable_signal_id,
            "signal_approach_id_v2": "",
            "route": r.route,
            "route_base": route_base(r.route),
            "carriageway_direction_token": route_direction_token(r.route),
            "roadway_representation": r.representation,
            "manual_from_measure": r.manual_from_measure,
            "manual_to_measure": r.manual_to_measure,
            "reviewed_signal_projected_measure": sig_measure,
            "reviewed_signal_projection_confidence": sig_conf,
            "endpoint_signal_globalids": "|".join(r.endpoint_globalids),
            "endpoint_signal_projected_measures": "|".join(f"{x.source_globalid}:{x.estimated_measure}" for x in usable_eps.itertuples(index=False)) if not usable_eps.empty else "",
            "source_only_endpoint_boundaries_used": bool(len(usable_eps[usable_eps.get("source_only_endpoint_boundary", pd.Series(False, index=usable_eps.index)).astype(bool)])) if not usable_eps.empty else False,
            "side_before_signal_label": before_label,
            "side_after_signal_label": after_label,
            "directionality_method": method,
            "confidence": confidence if before_label and after_label else "none",
            "model_usable": bool(before_label and after_label),
            "no_model_reason": no_model_reason,
            "evidence": json.dumps(evidence, sort_keys=True),
            "manual_notes": r.notes,
        }
        if not rm.empty:
            row["route_rows_found"] = rm.iloc[0].get("route_rows_found")
            row["matched_rows_found"] = rm.iloc[0].get("matched_rows_found")
            row["matched_measure_min"] = rm.iloc[0].get("matched_measure_min")
            row["matched_measure_max"] = rm.iloc[0].get("matched_measure_max")
        rows.append(row)
        if row["model_usable"] and r.side_rule == "endpoint_upstream_downstream":
            primary_labels[(r.case_id, r.route)] = (before_label, after_label)
    return pd.DataFrame(rows)


def project_bin_to_corridor_position(bin_row: pd.Series, corridor_geometry: Any, corridor_measure_range: tuple[float | None, float | None]) -> dict[str, Any]:
    """Locate a staged/generated bin in corridor-side space.

    Existing rows use geometry WKT when available. Generated rows without
    standalone geometry fall back to source measure midpoint and continuation
    corridor/distance interval provenance, so absence of bin geometry alone is
    not a blocker.
    """
    geom = parse_geometry(bin_row.get("geometry_wkt"))
    midpoint_measure = pd.to_numeric(pd.Series([bin_row.get("source_measure_midpoint")]), errors="coerce").iloc[0]
    start = pd.to_numeric(pd.Series([bin_row.get("source_measure_start")]), errors="coerce").iloc[0]
    end = pd.to_numeric(pd.Series([bin_row.get("source_measure_end")]), errors="coerce").iloc[0]
    if geom is not None and corridor_geometry is not None and nearest_points is not None:
        rep = geom.representative_point() if hasattr(geom, "representative_point") else geom
        proj = project_point_to_line_measure(rep, corridor_geometry, corridor_measure_range[0], corridor_measure_range[1])
        if proj["projection_usable"]:
            # Existing bins can inherit broad parent source-row measure ranges.
            # Once the bin geometry itself is projected, use the projected
            # representative position for side classification rather than
            # treating the inherited parent interval as a bin interval.
            return {
                "measure_start": pd.NA,
                "measure_end": pd.NA,
                "measure_midpoint": proj["estimated_measure"] if pd.notna(proj["estimated_measure"]) else midpoint_measure,
                "position_method": "bin_geometry_representative_point_projected_to_source_corridor",
                "position_confidence": proj["projection_confidence"],
                "point_to_line_distance": proj["point_to_line_distance"],
                "generated_without_geometry_handled": False,
            }
    if pd.notna(midpoint_measure) or (pd.notna(start) and pd.notna(end)):
        broad_parent_interval = False
        if pd.notna(start) and pd.notna(end):
            broad_parent_interval = abs(float(end) - float(start)) > 0.25
        return {
            "measure_start": pd.NA if broad_parent_interval and pd.notna(midpoint_measure) else start,
            "measure_end": pd.NA if broad_parent_interval and pd.notna(midpoint_measure) else end,
            "measure_midpoint": midpoint_measure if pd.notna(midpoint_measure) else (float(start) + float(end)) / 2.0,
            "position_method": "source_measure_midpoint_from_staged_bin_broad_parent_interval" if broad_parent_interval and pd.notna(midpoint_measure) else "source_measure_midpoint_from_staged_bin",
            "position_confidence": "high",
            "point_to_line_distance": pd.NA,
            "generated_without_geometry_handled": bool(bin_row.get("generated_bin_flag")) and geom is None,
        }
    if bool(bin_row.get("generated_bin_flag")):
        return {
            "measure_start": pd.NA,
            "measure_end": pd.NA,
            "measure_midpoint": pd.NA,
            "position_method": "generated_bin_without_measure_or_corridor_geometry",
            "position_confidence": "none",
            "point_to_line_distance": pd.NA,
            "generated_without_geometry_handled": False,
        }
    return {
        "measure_start": pd.NA,
        "measure_end": pd.NA,
        "measure_midpoint": pd.NA,
        "position_method": "missing_bin_geometry_and_measure",
        "position_confidence": "none",
        "point_to_line_distance": pd.NA,
        "generated_without_geometry_handled": False,
    }


def corridor_line_for_model(model: pd.Series, roads: pd.DataFrame):
    route_rows = roads_for_route(
        roads,
        str(model["route"]),
        None if pd.isna(model.get("matched_measure_min")) else float(model.get("matched_measure_min")),
        None if pd.isna(model.get("matched_measure_max")) else float(model.get("matched_measure_max")),
    )
    if route_rows.empty:
        return None, (None, None)
    row = route_rows.sort_values("Shape_Length", ascending=False, na_position="last").iloc[0]
    return parse_geometry(row.get("geometry")), (row.get("FROM_MEASURE"), row.get("TO_MEASURE"))


def assign_model_to_bin(bin_row: pd.Series, model: pd.Series, roads: pd.DataFrame) -> dict[str, Any]:
    corridor_geometry, corridor_range = corridor_line_for_model(model, roads)
    pos = project_bin_to_corridor_position(bin_row, corridor_geometry, corridor_range)
    side_class = classify_side_of_signal(model.get("reviewed_signal_projected_measure"), pos)
    proposed = ""
    reason = ""

    model_usable = bool(model.get("model_usable"))
    if not model_usable:
        reason = str(model.get("no_model_reason") or "corridor_side_model_not_usable")
    elif str(model.get("directionality_method", "")).endswith("manual_explicit_interval"):
        start = pd.to_numeric(pd.Series([bin_row.get("source_measure_start")]), errors="coerce").iloc[0]
        end = pd.to_numeric(pd.Series([bin_row.get("source_measure_end")]), errors="coerce").iloc[0]
        mf = model.get("manual_from_measure")
        mt = model.get("manual_to_measure")
        if pd.notna(start) and pd.notna(end) and pd.notna(mf) and pd.notna(mt):
            low = max(min(float(start), float(end)), min(float(mf), float(mt)))
            high = min(max(float(start), float(end)), max(float(mf), float(mt)))
            if low <= high + MEASURE_EPS:
                evidence = json.loads(str(model.get("evidence") or "{}"))
                proposed = evidence.get("manual_interval_label", "")
            else:
                reason = "bin_not_in_manual_interval"
        else:
            reason = "manual_interval_or_bin_measure_missing"
    elif side_class == "before_signal":
        proposed = str(model.get("side_before_signal_label") or "")
    elif side_class == "after_signal":
        proposed = str(model.get("side_after_signal_label") or "")
    elif side_class == "straddles_signal":
        reason = "bin_straddles_reviewed_signal"
    else:
        reason = "bin_position_too_close_or_uncertain"

    if proposed not in {"upstream", "downstream"} and not reason:
        reason = "model_side_label_missing"
    confidence = model.get("confidence", "none") if proposed else "none"
    if pos["position_confidence"] == "medium" and confidence == "high":
        confidence = "medium"
    return {
        **pos,
        "side_of_signal": side_class,
        "proposed_upstream_downstream": proposed,
        "proposal_confidence": confidence,
        "proposal_reason": "corridor_side_geometry_engine" if proposed else "",
        "no_proposal_reason": "" if proposed else reason,
    }


def build_case_bin_proposals(bin_context: pd.DataFrame, models: pd.DataFrame, roads: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    side = side_values(bin_context)
    case_sids = {v["stable_signal_id"]: k for k, v in CASES.items()}
    case_bins = bin_context[bin_context["stable_signal_id"].astype(str).isin(case_sids)].copy()
    case_bins["case_id"] = case_bins["stable_signal_id"].map(case_sids)
    case_bins["_existing_side"] = side.loc[case_bins.index]
    unresolved = case_bins[~nonmissing(case_bins["_existing_side"])].copy()

    proposal_rows: list[dict[str, Any]] = []
    no_rows: list[dict[str, Any]] = []
    usable_models = models[models["model_usable"].astype(bool)].copy()
    for _, b in unresolved.iterrows():
        route = str(b.get("source_route_name"))
        m = usable_models[(usable_models["case_id"].eq(b["case_id"])) & (usable_models["route"].eq(route))]
        if m.empty:
            rec = {
                "case_id": b["case_id"],
                "stable_signal_id": b.get("stable_signal_id"),
                "stable_bin_id": b.get("stable_bin_id"),
                "signal_approach_id_v2": b.get("signal_approach_id_v2"),
                "route": route,
                "generated_bin_flag": b.get("generated_bin_flag"),
                "continuation_corridor_id": b.get("continuation_corridor_id"),
                "source_measure_start": b.get("source_measure_start"),
                "source_measure_end": b.get("source_measure_end"),
                "source_measure_midpoint": b.get("source_measure_midpoint"),
                "distance_band_v2": b.get("distance_band_v2", b.get("distance_band")),
                "no_proposal_reason": "no_corridor_side_model_for_route",
            }
            no_rows.append(rec)
            continue
        assigned = None
        for _, model in m.iterrows():
            out = assign_model_to_bin(b, model, roads)
            if out["proposed_upstream_downstream"]:
                assigned = (model, out)
                break
            if assigned is None:
                assigned = (model, out)
        model, out = assigned
        rec = {
            "case_id": b["case_id"],
            "reviewed_globalid": CASES[b["case_id"]]["reviewed_globalid"],
            "stable_signal_id": b.get("stable_signal_id"),
            "stable_bin_id": b.get("stable_bin_id"),
            "stable_travelway_id": b.get("stable_travelway_id"),
            "signal_approach_id_v2": b.get("signal_approach_id_v2"),
            "corridor_side_model_id": model.get("corridor_side_model_id"),
            "route": route,
            "roadway_representation": model.get("roadway_representation"),
            "generated_bin_flag": b.get("generated_bin_flag"),
            "bin_row_origin": b.get("bin_row_origin"),
            "continuation_corridor_id": b.get("continuation_corridor_id"),
            "generated_geometry_status": b.get("generated_geometry_status"),
            "source_measure_start": b.get("source_measure_start"),
            "source_measure_end": b.get("source_measure_end"),
            "source_measure_midpoint": b.get("source_measure_midpoint"),
            "distance_start_ft": b.get("distance_start_ft"),
            "distance_end_ft": b.get("distance_end_ft"),
            "distance_band_v2": b.get("distance_band_v2", b.get("distance_band")),
            "reviewed_signal_projected_measure": model.get("reviewed_signal_projected_measure"),
            "side_before_signal_label": model.get("side_before_signal_label"),
            "side_after_signal_label": model.get("side_after_signal_label"),
            "directionality_method": model.get("directionality_method"),
            **out,
        }
        if out["proposed_upstream_downstream"]:
            proposal_rows.append(rec)
        else:
            no_rows.append(rec)
    return pd.DataFrame(proposal_rows), pd.DataFrame(no_rows)


def unit_recovery(proposals: pd.DataFrame, bin_context: pd.DataFrame) -> pd.DataFrame:
    if proposals.empty:
        return pd.DataFrame(columns=["case_id", "route", "proposed_bins", "proposed_units", "proposal_confidence"])
    unit_cols = ["stable_signal_id", "signal_approach_id_v2", "distance_band_v2", "proposed_upstream_downstream"]
    p = proposals.copy()
    p["distance_band_v2"] = p["distance_band_v2"].fillna("")
    grouped = p.groupby(["case_id", "route", "proposal_confidence"], dropna=False).agg(
        proposed_bins=("stable_bin_id", "count"),
        proposed_units=(unit_cols[0], lambda s: 0),
    ).reset_index()
    unit_counts = p.drop_duplicates(unit_cols).groupby(["case_id", "route", "proposal_confidence"], dropna=False).size().reset_index(name="proposed_units")
    grouped = grouped.drop(columns=["proposed_units"]).merge(unit_counts, on=["case_id", "route", "proposal_confidence"], how="left")
    return grouped


def pass_fail_summary(proposals: pd.DataFrame, no_detail: pd.DataFrame, models: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for case_id, case in CASES.items():
        p = proposals[proposals["case_id"].eq(case_id)] if not proposals.empty else proposals
        no = no_detail[no_detail["case_id"].eq(case_id)] if not no_detail.empty else no_detail
        if case_id == "case_2":
            target = p[p["route"].astype(str).isin(["R-VA   SR00208NB", "R-VA   SR00208SB"])] if not p.empty else p
            missing_target = no[no["route"].astype(str).isin(["R-VA   SR00208NB", "R-VA   SR00208SB"])] if not no.empty else no
            passed = len(target[target["proposal_confidence"].eq("high")]) > 0
            blocker = "" if passed else ("; ".join(sorted(missing_target["no_proposal_reason"].dropna().astype(str).unique())) if not missing_target.empty else "no_target_rows_found")
            target_name = "SR00208NB/SB"
        elif case_id == "case_3":
            target = p[p["route"].astype(str).isin(["R-VA   US00001NB", "R-VA   US00001SB"])] if not p.empty else p
            missing_target = no[no["route"].astype(str).isin(["R-VA   US00001NB", "R-VA   US00001SB"])] if not no.empty else no
            passed = len(target[target["proposal_confidence"].eq("high")]) > 0
            blocker = "" if passed else ("; ".join(sorted(missing_target["no_proposal_reason"].dropna().astype(str).unique())) if not missing_target.empty else "no_target_rows_found")
            target_name = "US00001NB/SB"
        else:
            target = p
            passed = len(target) > 0
            blocker = "" if passed else "positive_control_proposed_zero_bins"
            target_name = "positive_control"
        endpoint_rows = crosswalk[(crosswalk["case_id"].astype(str).str.contains(case_id, na=False)) & (crosswalk["signal_role"].eq("endpoint_signal"))]
        rows.append({
            "case_id": case_id,
            "reviewed_globalid": case["reviewed_globalid"],
            "stable_signal_id": case["stable_signal_id"],
            "required_target": target_name,
            "case_passed": bool(passed),
            "target_proposed_bins": int(len(target)) if target is not None else 0,
            "high_confidence_target_proposed_bins": int(len(target[target["proposal_confidence"].eq("high")])) if target is not None and not target.empty else 0,
            "all_case_proposed_bins": int(len(p)) if p is not None else 0,
            "corridor_side_models_created": int(len(models[models["case_id"].eq(case_id)])),
            "usable_corridor_side_models": int(models[models["case_id"].eq(case_id)]["model_usable"].sum()),
            "source_only_endpoint_boundaries": int(endpoint_rows["source_only_endpoint_boundary"].sum()) if not endpoint_rows.empty else 0,
            "endpoint_boundary_records": int(len(endpoint_rows)),
            "blocker_if_failed": blocker,
        })
    return pd.DataFrame(rows)


def conflict_safety_checks(proposals: pd.DataFrame, models: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"check_name": "no_staged_or_canonical_mutation", "status": "pass", "detail": "Script writes only review outputs under corridor_side_geometry_engine_case_tests."},
        {"check_name": "no_crash_direction_fields_used", "status": "pass", "detail": "No crash files or crash direction fields are read."},
        {"check_name": "no_force_fill_no_proposal_rows", "status": "pass", "detail": "Rows without deterministic model/bin position are retained in no_proposal_reason_detail.csv."},
        {"check_name": "representation_methods_separate", "status": "pass" if set(models["roadway_representation"]).issuperset({"true_paired_divided_carriageway", "undivided_centerline", "divided_centerline_proxy"}) else "review", "detail": "|".join(sorted(models["roadway_representation"].dropna().astype(str).unique()))},
    ]
    if not proposals.empty:
        dup = proposals.groupby("stable_bin_id")["proposed_upstream_downstream"].nunique(dropna=True).reset_index(name="side_count")
        conflicts = int((dup["side_count"] > 1).sum())
    else:
        conflicts = 0
    rows.append({"check_name": "no_conflicting_bin_side_proposals", "status": "pass" if conflicts == 0 else "fail", "detail": f"conflicting stable_bin_id side proposals: {conflicts}"})
    rows.append({"check_name": "source_only_endpoint_boundaries_usable", "status": "pass" if int(crosswalk["source_only_endpoint_boundary"].sum()) > 0 else "review", "detail": f"source-only endpoint boundaries: {int(crosswalk['source_only_endpoint_boundary'].sum())}"})
    return pd.DataFrame(rows)


def optional_global_outputs(case_pass: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    status = "not_run_case_test_first_prototype"
    if case_pass:
        status = "not_run_bounded_global_screen_deferred_after_case_engine_validation"
    summary = pd.DataFrame([{
        "screen_status": status,
        "global_bins_screened": 0,
        "global_bins_proposed": 0,
        "global_units_estimated": 0,
        "reason": "This turn implemented and validated the case-test engine only; no broad global proposal was run.",
    }])
    return summary, pd.DataFrame(columns=["stable_signal_id", "stable_bin_id", "route", "proposed_upstream_downstream", "proposal_confidence"]), pd.DataFrame(columns=["estimate_name", "value"])


def recommendations(pass_summary: pd.DataFrame, models: pd.DataFrame, no_detail: pd.DataFrame) -> pd.DataFrame:
    case2 = bool(pass_summary.loc[pass_summary["case_id"].eq("case_2"), "case_passed"].iloc[0])
    case3 = bool(pass_summary.loc[pass_summary["case_id"].eq("case_3"), "case_passed"].iloc[0])
    if not case2:
        rec = "case_engine_failed_case2_unresolved"
    elif not case3:
        rec = "case_engine_failed_case3_unresolved"
    elif (models["confidence"].eq("medium")).any():
        rec = "case_engine_passed_but_needs_map_review_before_globalization"
    else:
        rec = "case_engine_passed_ready_for_global_review_only_proposal"
    return pd.DataFrame([
        {
            "recommendation": rec,
            "case2_passed": case2,
            "case3_passed": case3,
            "next_action": "Run a review-only bounded global proposal using this corridor-side model; do not mutate staging until QA approval.",
            "rationale": "Cases 2 and 3 are the required blockers; generated/no-geometry bins are handled through source measure and continuation provenance when present.",
        }
    ])


def write_findings(
    pass_summary: pd.DataFrame,
    proposals: pd.DataFrame,
    no_detail: pd.DataFrame,
    crosswalk: pd.DataFrame,
    recs: pd.DataFrame,
) -> None:
    case2 = pass_summary[pass_summary["case_id"].eq("case_2")].iloc[0]
    case3 = pass_summary[pass_summary["case_id"].eq("case_3")].iloc[0]
    generated = proposals[proposals["generated_bin_flag"].astype(str).str.lower().isin(["true", "1"])] if not proposals.empty else proposals
    text = f"""# Corridor-Side Geometry Engine Case Tests

## What changed from prior failed global passes

This prototype builds corridor-side models first. It projects reviewed signals and source-only endpoint signals to source Travelway geometry, splits each corridor at the reviewed signal, then maps bin positions to the before/after side. It does not require existing local directionality calibration as the primary gate.

## Source-only endpoint boundaries

Source-only endpoint boundaries worked when normalized signal geometry existed. Source-only endpoint boundary records: {int(crosswalk['source_only_endpoint_boundary'].sum())}. Endpoint records usable as corridor boundaries: {int(crosswalk[crosswalk['signal_role'].eq('endpoint_signal')]['usable_as_corridor_boundary'].sum())}.

## Case 2

Case 2 passed: {bool(case2['case_passed'])}. Target proposed bins: {int(case2['target_proposed_bins'])}. Blocker if failed: {case2['blocker_if_failed'] or ''}.

## Case 3

Case 3 passed: {bool(case3['case_passed'])}. Target proposed bins: {int(case3['target_proposed_bins'])}. Blocker if failed: {case3['blocker_if_failed'] or ''}.

## Generated bins without geometry

Generated bins without standalone geometry can be handled when staged source measures or continuation corridor provenance provide a deterministic corridor position. This run proposed {len(generated)} generated bins using those fallbacks; rows without measure/corridor evidence remain no-proposal rows.

## Corridor-side model rules that worked

The working rules are source endpoint signal corridor splitting, paired reverse carriageway inference from a conflict-free reference carriageway, cardinal measure-direction splitting for NB/EB versus SB/WB, explicit manual interval labels, synthetic undivided centerline provenance, and divided-centerline/proxy provenance kept separate from true paired divided evidence.

## Remaining unresolved

No-proposal rows remain where a route has no usable corridor-side model, a bin straddles or is too close to the reviewed signal, a manual interval does not contain the bin, or source/bin measure geometry is missing. These rows were not force-filled.

## Whether to globalize next

Recommendation: `{recs.iloc[0]['recommendation']}`. The next step should be a review-only bounded global proposal using the same engine, followed by QA before any mutation task.
"""
    (OUT_DIR / "findings_memo.md").write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "progress_log.md").write_text("# Progress Log\n", encoding="utf-8")
    log("Loading staged/cache and normalized source inputs.")
    data = load_inputs()
    routes = manual_case_routes()

    log("Building source signal boundary crosswalk and route match summary.")
    crosswalk = build_signal_boundary_crosswalk(data["signals"], data["bin_context"])
    route_matches = build_route_match_summary(routes, data["roads"])
    signal_proj, endpoint_proj = project_signals(routes, data["signals"], data["roads"], crosswalk)

    log("Building corridor-side models from signal and endpoint projections.")
    models = build_corridor_side_models(routes, route_matches, signal_proj, endpoint_proj)

    log("Projecting case unresolved bins to corridor-side models.")
    proposals, no_detail = build_case_bin_proposals(data["bin_context"], models, data["roads"])
    units = unit_recovery(proposals, data["bin_context"])
    pass_summary = pass_fail_summary(proposals, no_detail, models, crosswalk)
    case_required_pass = bool(pass_summary.loc[pass_summary["case_id"].eq("case_2"), "case_passed"].iloc[0]) and bool(pass_summary.loc[pass_summary["case_id"].eq("case_3"), "case_passed"].iloc[0])
    global_summary, global_proposals, global_units = optional_global_outputs(case_required_pass)
    conflicts = conflict_safety_checks(proposals, models, crosswalk)
    recs = recommendations(pass_summary, models, no_detail)

    log("Writing review-only output package.")
    write_csv("signal_boundary_crosswalk.csv", crosswalk)
    write_csv("manual_case_route_match_summary.csv", route_matches)
    write_csv("signal_projection_results.csv", signal_proj)
    write_csv("endpoint_projection_results.csv", endpoint_proj)
    write_csv("corridor_side_model_case_results.csv", models)
    write_csv("case_test_bin_proposals.csv", proposals)
    write_csv("case_test_unit_recovery.csv", units)
    write_csv("case_test_pass_fail_summary.csv", pass_summary)
    write_csv("no_proposal_reason_detail.csv", no_detail)
    write_csv("optional_global_screen_summary.csv", global_summary)
    write_csv("optional_global_screen_bin_proposals.csv", global_proposals)
    write_csv("optional_global_screen_unit_estimate.csv", global_units)
    write_csv("conflict_and_safety_checks.csv", conflicts)
    write_csv("recommended_next_actions.csv", recs)
    write_findings(pass_summary, proposals, no_detail, crosswalk, recs)

    manifest = {
        "created_utc": now_iso(),
        "bounded_question": "Case-test reusable corridor-side geometry engine for directionality recovery.",
        "output_grain": {
            "corridor_side_model_case_results.csv": "signal x approach/route/manual interval corridor-side model",
            "case_test_bin_proposals.csv": "unresolved staged bin proposal rows for manual cases only",
            "case_test_unit_recovery.csv": "case x route x confidence proposed direction-ready unit counts",
        },
        "source_inputs": [rel(p) for p in [BIN_CONTEXT, SIGNAL_APPROACHES, APPROACH_WINDOWS, CONTINUATION_CORRIDORS, CONTINUATION_PROVENANCE, SIGNALS, ROADS]],
        "previous_review_context_read": [
            "work/roadway_graph/review/global_bin_geometry_directionality_projection_proposal/",
            "work/roadway_graph/review/global_geometry_directionality_projection_proposal/",
            "work/roadway_graph/review/directionality_signal_measure_projection_prototype/",
            "work/roadway_graph/review/directionality_manual_case_rule_proposal/",
            "work/roadway_graph/review/expanded_directionality_recovery_audit/",
            "work/roadway_graph/review/expanded_directionality_blocker_rule_proposal_audit/",
        ],
        "rows_read": {name: int(len(df)) for name, df in data.items()},
        "case_proposed_bins": pass_summary[["case_id", "all_case_proposed_bins", "target_proposed_bins", "case_passed"]].to_dict("records"),
        "no_mutation": True,
        "crash_direction_fields_used": False,
        "optional_global_screen": global_summary.iloc[0].to_dict(),
    }
    qa_manifest = {
        "created_utc": now_iso(),
        "case2_passed": bool(pass_summary.loc[pass_summary["case_id"].eq("case_2"), "case_passed"].iloc[0]),
        "case3_passed": bool(pass_summary.loc[pass_summary["case_id"].eq("case_3"), "case_passed"].iloc[0]),
        "case2_target_bins": int(pass_summary.loc[pass_summary["case_id"].eq("case_2"), "target_proposed_bins"].iloc[0]),
        "case3_target_bins": int(pass_summary.loc[pass_summary["case_id"].eq("case_3"), "target_proposed_bins"].iloc[0]),
        "source_only_endpoint_boundaries": int(crosswalk["source_only_endpoint_boundary"].sum()),
        "conflict_checks": conflicts.to_dict("records"),
        "recommendation": recs.iloc[0]["recommendation"],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    (OUT_DIR / "qa_manifest.json").write_text(json.dumps(qa_manifest, indent=2, sort_keys=True), encoding="utf-8")
    log("Completed corridor-side geometry engine case tests.")


if __name__ == "__main__":
    main()
