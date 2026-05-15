from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString


OUTPUT_ROOT = Path("work/output/roadway_graph")
FEET_PER_METER = 3.280839895
ANCHOR_CLUSTER_TOLERANCE_FT = 175.0
MAX_CANDIDATE_BEARING_DIFF_DEG = 32.0
MIN_LATERAL_SEPARATION_FT = 10.0
MAX_LATERAL_SEPARATION_FT = 220.0
REVIEW_SAMPLE_SIZE = 800

ROLE_INCLUDED = "mainline_divided_carriageway"
ROLE_EXCLUDED = {
    "ramp_or_connector",
    "frontage_or_service_road",
    "turn_lane_or_auxiliary",
    "one_way_pair_candidate",
    "unknown_review",
    "undivided_centerline",
}


def _read_wkt_csv(path: Path) -> gpd.GeoDataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame["geometry"] = frame["geometry"].map(wkt.loads)
    return gpd.GeoDataFrame(frame, geometry="geometry")


def _write_csv(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(frame.copy())
    if "geometry" in out.columns and isinstance(frame, gpd.GeoDataFrame):
        out["geometry"] = frame.geometry.to_wkt()
    out.columns = _dedupe_columns(list(out.columns))
    out.to_csv(path, index=False)


def _write_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    else:
        frame.to_file(path, driver="GeoJSON")


def _dedupe_columns(columns: list[object]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for column in columns:
        name = str(column)
        key = name.lower()
        count = seen.get(key, 0)
        if count == 0:
            out.append(name)
        else:
            out.append(f"{name}_dup{count}")
        seen[key] = count + 1
    return out


def _clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null", "<null>"}:
        return ""
    return text


def _route_stem(*values: object) -> str:
    text = " ".join(_clean(value) for value in values if _clean(value)).strip()
    if not text:
        return ""
    text = text.upper()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(NORTHBOUND|SOUTHBOUND|EASTBOUND|WESTBOUND)\b", "", text)
    text = re.sub(r"([ _/\-])(NB|SB|EB|WB|N|S|E|W)$", "", text)
    text = re.sub(r"([A-Z]+[ -]?\d+)(NB|SB|EB|WB|N|S|E|W)$", r"\1", text)
    text = re.sub(r"(.+\d)(NB|SB|EB|WB|N|S|E|W)$", r"\1", text)
    text = re.sub(r"\b(NB|SB|EB|WB)\b", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -_/")


def _coords(geometry: LineString) -> list[tuple[float, float]]:
    if geometry is None or geometry.is_empty or not hasattr(geometry, "coords"):
        return []
    return [(float(x), float(y)) for x, y, *_ in geometry.coords]


def _endpoints(geometry: LineString) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    coords = _coords(geometry)
    if len(coords) < 2:
        return None, None
    return coords[0], coords[-1]


def _bearing(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return None
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _angular_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _parallel_bearing_diff(a: float, b: float) -> float:
    diff = _angular_diff(a, b)
    return min(diff, abs(180.0 - diff))


def _distance_ft(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1]) * FEET_PER_METER


def _line_signature(geometry: LineString) -> str:
    start, end = _endpoints(geometry)
    if start is None or end is None:
        return ""
    a = (round(start[0], 2), round(start[1], 2))
    b = (round(end[0], 2), round(end[1], 2))
    return "|".join(f"{x:.2f},{y:.2f}" for x, y in sorted([a, b]))


def _point_at(line: LineString, fraction: float) -> tuple[float, float] | None:
    if line is None or line.is_empty:
        return None
    point = line.interpolate(fraction, normalized=True)
    return float(point.x), float(point.y)


def _tangent_at(line: LineString, fraction: float) -> tuple[float, float] | None:
    p0 = _point_at(line, max(0.0, fraction - 0.035))
    p1 = _point_at(line, min(1.0, fraction + 0.035))
    if p0 is None or p1 is None:
        return None
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return None
    return dx / length, dy / length


def _signed_lateral_ft(origin: tuple[float, float], tangent: tuple[float, float], point: tuple[float, float]) -> float:
    wx = point[0] - origin[0]
    wy = point[1] - origin[1]
    return (tangent[0] * wy - tangent[1] * wx) * FEET_PER_METER


def _align_reversed(line_a: LineString, line_b: LineString) -> bool:
    a0, a1 = _endpoints(line_a)
    b0, b1 = _endpoints(line_b)
    if not all([a0, a1, b0, b1]):
        return False
    direct = _distance_ft(a0, b0) + _distance_ft(a1, b1)
    reverse = _distance_ft(a0, b1) + _distance_ft(a1, b0)
    return reverse < direct


def _local_side_score(line_a: LineString, line_b: LineString) -> dict[str, float | str]:
    fractions = [0.2, 0.35, 0.5, 0.65, 0.8]
    reversed_b = _align_reversed(line_a, line_b)
    signed_values: list[float] = []
    tangent_diffs: list[float] = []
    for fraction in fractions:
        point_a = _point_at(line_a, fraction)
        point_b = _point_at(line_b, 1.0 - fraction if reversed_b else fraction)
        tangent_a = _tangent_at(line_a, fraction)
        tangent_b = _tangent_at(line_b, 1.0 - fraction if reversed_b else fraction)
        if point_a is None or point_b is None or tangent_a is None or tangent_b is None:
            continue
        signed_values.append(_signed_lateral_ft(point_a, tangent_a, point_b))
        bearing_a = (math.degrees(math.atan2(tangent_a[0], tangent_a[1])) + 360.0) % 360.0
        bearing_b = (math.degrees(math.atan2(tangent_b[0], tangent_b[1])) + 360.0) % 360.0
        tangent_diffs.append(_parallel_bearing_diff(bearing_a, bearing_b))

    if len(signed_values) < 3:
        return {
            "local_axis_method": "sampled_local_tangent_excluding_endpoint_flares",
            "side_score": 0.0,
            "lateral_separation_ft": 0.0,
            "side_stability": "insufficient_samples",
            "local_bearing_diff": 180.0,
        }

    signs = [1 if value > 0 else -1 if value < 0 else 0 for value in signed_values]
    dominant_sign = 1 if sum(signs) >= 0 else -1
    consistent = sum(1 for sign in signs if sign == dominant_sign)
    abs_values = [abs(value) for value in signed_values]
    mean_sep = sum(abs_values) / len(abs_values)
    spread = max(abs_values) - min(abs_values)
    stability = consistent / len(signs)
    separation_score = min(mean_sep / 45.0, 1.0)
    spread_penalty = min(spread / 90.0, 1.0)
    side_score = max(0.0, min(1.0, 0.7 * stability + 0.3 * separation_score - 0.25 * spread_penalty))
    return {
        "local_axis_method": "sampled_local_tangent_excluding_endpoint_flares",
        "side_score": round(side_score, 4),
        "lateral_separation_ft": round(mean_sep, 3),
        "side_stability": "stable" if stability >= 0.8 else "unstable",
        "local_bearing_diff": round(sum(tangent_diffs) / len(tangent_diffs), 3) if tangent_diffs else 180.0,
    }


def _projected_overlap_score(line_a: LineString, line_b: LineString) -> float:
    a0, a1 = _endpoints(line_a)
    if a0 is None or a1 is None:
        return 0.0
    vx = a1[0] - a0[0]
    vy = a1[1] - a0[1]
    length = math.hypot(vx, vy)
    if length == 0:
        return 0.0
    ux = vx / length
    uy = vy / length

    def interval(line: LineString) -> tuple[float, float]:
        vals = []
        for point in [_point_at(line, f) for f in [0.0, 0.25, 0.5, 0.75, 1.0]]:
            if point is not None:
                vals.append((point[0] - a0[0]) * ux + (point[1] - a0[1]) * uy)
        return min(vals), max(vals)

    a_min, a_max = interval(line_a)
    b_min, b_max = interval(line_b)
    overlap = max(0.0, min(a_max, b_max) - max(a_min, b_min))
    denom = max(1e-9, min(a_max - a_min, b_max - b_min))
    return round(max(0.0, min(1.0, overlap / denom)), 4)


def _prepare_segments(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = segments.copy()
    for column in out.columns:
        if column != "geometry":
            out[column] = out[column].astype("object")
    out["route_stem"] = out.apply(lambda row: _route_stem(row.get("route_common"), row.get("route_name")), axis=1)
    out["_start_xy"] = [start for start, _ in out.geometry.map(_endpoints)]
    out["_end_xy"] = [end for _, end in out.geometry.map(_endpoints)]
    out["_bearing"] = [
        "" if start is None or end is None else _bearing(start, end)
        for start, end in zip(out["_start_xy"], out["_end_xy"], strict=False)
    ]
    out["_line_signature"] = out.geometry.map(_line_signature)
    return out


def _anchor_clusters(segments: gpd.GeoDataFrame) -> dict[str, str]:
    cluster_ids: dict[str, str] = {}
    for reference_signal_id, group in segments.groupby("reference_signal_id", dropna=False, sort=False):
        clusters: list[tuple[tuple[float, float], list[str]]] = []
        for _, row in group.iterrows():
            segment_id = str(row["oriented_segment_id"])
            endpoint = row.get("_end_xy")
            if endpoint is None:
                cluster_ids[segment_id] = f"{reference_signal_id}|invalid_anchor"
                continue
            chosen = None
            for i, (center, members) in enumerate(clusters):
                if _distance_ft(endpoint, center) <= ANCHOR_CLUSTER_TOLERANCE_FT:
                    chosen = i
                    members.append(segment_id)
                    n = len(members)
                    clusters[i] = (((center[0] * (n - 1) + endpoint[0]) / n, (center[1] * (n - 1) + endpoint[1]) / n), members)
                    break
            if chosen is None:
                clusters.append((endpoint, [segment_id]))
        for i, (_center, members) in enumerate(clusters, start=1):
            for member in members:
                cluster_ids[member] = f"{reference_signal_id}|anchor_cluster_{i:03d}"
    return cluster_ids


def _unresolved_reason(row: pd.Series) -> str:
    reason = _clean(row.get("pairing_problem_reason"))
    missing = _clean(row.get("missing_reciprocal_reason"))
    anchor_type = _clean(row.get("opposite_anchor_type")).lower()
    opposite_status = _clean(row.get("opposite_anchor_step5_status")).upper()
    if "source" in reason.lower() or "source" in missing.lower():
        return "still_unresolved_source_missing"
    if anchor_type in {"endpoint", "road_endpoint"} or "one-sided" in reason.lower() or "endpoint" in reason.lower():
        return "still_unresolved_endpoint_or_one_sided"
    if opposite_status in {"FALSE", "CONDITIONAL"}:
        return "still_unresolved_endpoint_or_one_sided"
    if "ambiguous" in reason.lower() or "side" in reason.lower() or "bracket" in reason.lower():
        return "still_unresolved_ambiguous_geometry"
    return "still_unresolved_unknown"


def _evaluate_candidate(row_a: pd.Series, row_b: pd.Series) -> dict[str, object] | None:
    if row_a["oriented_segment_id"] == row_b["oriented_segment_id"]:
        return None
    if _clean(row_a.get("base_graph_edge_id")) and row_a.get("base_graph_edge_id") == row_b.get("base_graph_edge_id"):
        return None
    if _clean(row_a.get("road_component_id")) and row_a.get("road_component_id") == row_b.get("road_component_id"):
        return None
    if row_a.get("_line_signature") and row_a.get("_line_signature") == row_b.get("_line_signature"):
        return None
    if not row_a.get("route_stem") or row_a.get("route_stem") != row_b.get("route_stem"):
        return None
    if row_a.get("_bearing") == "" or row_b.get("_bearing") == "":
        return None

    bearing_diff = _parallel_bearing_diff(float(row_a["_bearing"]), float(row_b["_bearing"]))
    if bearing_diff > MAX_CANDIDATE_BEARING_DIFF_DEG:
        return None

    side = _local_side_score(row_a.geometry, row_b.geometry)
    lateral = float(side["lateral_separation_ft"])
    overlap = _projected_overlap_score(row_a.geometry, row_b.geometry)
    parallelism = round(max(0.0, min(1.0, 1.0 - bearing_diff / MAX_CANDIDATE_BEARING_DIFF_DEG)), 4)
    same_cluster = row_a.get("anchor_cluster_id") == row_b.get("anchor_cluster_id")

    if lateral < MIN_LATERAL_SEPARATION_FT:
        confidence = "low"
        reason = "ambiguous_side_score_candidate"
    elif lateral > MAX_LATERAL_SEPARATION_FT:
        confidence = "low"
        reason = "excessive_lateral_separation_review"
    elif parallelism >= 0.78 and overlap >= 0.45 and float(side["side_score"]) >= 0.68 and same_cluster:
        confidence = "high"
        reason = "route_stem_anchor_cluster_local_parallel_overlap"
    elif parallelism >= 0.68 and overlap >= 0.30 and float(side["side_score"]) >= 0.55:
        confidence = "medium"
        reason = "route_stem_relaxed_local_parallel_overlap"
    elif parallelism >= 0.58 and overlap >= 0.20 and float(side["side_score"]) >= 0.45:
        confidence = "low"
        reason = "low_confidence_geometry_review_only"
    else:
        return None

    return {
        "route_stem": row_a["route_stem"],
        "anchor_cluster_id": row_a.get("anchor_cluster_id", ""),
        "local_axis_method": side["local_axis_method"],
        "side_score": side["side_score"],
        "parallelism_score": parallelism,
        "projected_overlap_score": overlap,
        "lateral_separation_ft": lateral,
        "bearing_diff_degrees": round(bearing_diff, 3),
        "same_anchor_cluster": same_cluster,
        "recovery_confidence": confidence,
        "recovery_method": "route_stem_anchor_cluster_local_path_parallel_overlap",
        "recovery_reason": reason,
    }


def _candidate_status(confidence: str) -> str:
    if confidence == "high":
        return "recovered_high"
    if confidence == "medium":
        return "recovered_medium"
    return "recovered_low_review_only"


def _promotion(confidence: str) -> str:
    return "promote_after_spot_check" if confidence in {"high", "medium"} else "review_only"


def _build_recovery_candidates(segments: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, object]]]:
    working = segments.loc[
        segments["roadway_role_class"].eq(ROLE_INCLUDED)
        & segments["divided_pairing_status"].eq("unpaired")
        & segments["roadway_directionality_type"].eq("divided")
    ].copy()

    rows: list[dict[str, object]] = []
    best_by_segment: dict[str, dict[str, object]] = {}
    assigned: set[str] = set()
    pair_number = 0

    for (_reference_signal_id, _route_stem), group in working.groupby(["reference_signal_id", "route_stem"], dropna=False, sort=False):
        candidate_evals: list[dict[str, object]] = []
        indexed = list(group.iterrows())
        for i, (_, row_a) in enumerate(indexed):
            for _, row_b in indexed[i + 1 :]:
                result = _evaluate_candidate(row_a, row_b)
                if result is None:
                    continue
                score = (
                    float(result["parallelism_score"]) * 0.35
                    + float(result["projected_overlap_score"]) * 0.30
                    + float(result["side_score"]) * 0.25
                    + (0.10 if result["same_anchor_cluster"] else 0.0)
                )
                candidate_evals.append({"row_a": row_a, "row_b": row_b, "result": result, "score": score})

        candidate_evals.sort(key=lambda item: item["score"], reverse=True)
        for candidate in candidate_evals:
            row_a = candidate["row_a"]
            row_b = candidate["row_b"]
            id_a = str(row_a["oriented_segment_id"])
            id_b = str(row_b["oriented_segment_id"])
            result = candidate["result"]
            status = _candidate_status(str(result["recovery_confidence"]))
            candidate_pair_id = f"recovery_pair_{pair_number + 1:06d}"
            if id_a in assigned or id_b in assigned:
                if status != "recovered_low_review_only":
                    continue
                candidate_pair_id = ""
            elif status in {"recovered_high", "recovered_medium"}:
                pair_number += 1
                candidate_pair_id = f"recovery_pair_{pair_number:06d}"
                assigned.update({id_a, id_b})
            else:
                candidate_pair_id = f"review_pair_{len(rows) + 1:06d}"

            for original, opposite in [(row_a, row_b), (row_b, row_a)]:
                original_id = str(original["oriented_segment_id"])
                opposite_id = str(opposite["oriented_segment_id"])
                row = {
                    "original_oriented_segment_id": original_id,
                    "recovered_pair_id": candidate_pair_id,
                    "paired_opposite_segment_id": opposite_id,
                    "route_stem": result["route_stem"],
                    "anchor_cluster_id": result["anchor_cluster_id"],
                    "local_axis_method": result["local_axis_method"],
                    "side_score": result["side_score"],
                    "parallelism_score": result["parallelism_score"],
                    "projected_overlap_score": result["projected_overlap_score"],
                    "lateral_separation_ft": result["lateral_separation_ft"],
                    "recovery_confidence": result["recovery_confidence"],
                    "recovery_method": result["recovery_method"],
                    "recovery_reason": result["recovery_reason"],
                    "recovery_status": status,
                    "promotion_recommendation": _promotion(str(result["recovery_confidence"])),
                    "true_vehicle_direction_inferred": False,
                    "reference_signal_id": original.get("reference_signal_id", ""),
                    "route_name": original.get("route_name", ""),
                    "route_common": original.get("route_common", ""),
                    "rte_type_name": original.get("rte_type_name", ""),
                    "roadway_role_class": original.get("roadway_role_class", ""),
                    "opposite_anchor_type": original.get("opposite_anchor_type", ""),
                    "opposite_anchor_step5_status": original.get("opposite_anchor_step5_status", ""),
                    "bearing_diff_degrees": result["bearing_diff_degrees"],
                    "same_anchor_cluster": result["same_anchor_cluster"],
                }
                rows.append(row)
                if status in {"recovered_high", "recovered_medium"} and original_id not in best_by_segment:
                    best_by_segment[original_id] = row
                elif status == "recovered_low_review_only" and original_id not in best_by_segment:
                    best_by_segment[original_id] = row

    return pd.DataFrame(rows), best_by_segment


def _enrich_segments(segments: gpd.GeoDataFrame, best_by_segment: dict[str, dict[str, object]]) -> gpd.GeoDataFrame:
    out = segments.copy()
    for column in out.columns:
        if column != "geometry":
            out[column] = out[column].astype("object")

    defaults = {
        "recovery_status": "",
        "recovered_pair_id": "",
        "recovery_paired_opposite_segment_id": "",
        "route_stem": out.get("route_stem", pd.Series([""] * len(out), index=out.index)),
        "anchor_cluster_id": out.get("anchor_cluster_id", pd.Series([""] * len(out), index=out.index)),
        "local_axis_method": "",
        "side_score": "",
        "parallelism_score": "",
        "projected_overlap_score": "",
        "lateral_separation_ft": "",
        "recovery_confidence": "",
        "recovery_method": "",
        "recovery_reason": "",
        "promotion_recommendation": "",
        "recovery_true_vehicle_direction_inferred": False,
    }
    for column, value in defaults.items():
        if isinstance(value, pd.Series):
            out[column] = value
        else:
            out[column] = pd.Series([value] * len(out), index=out.index, dtype=object)

    paired_mask = out["divided_pairing_status"].eq("paired")
    out.loc[paired_mask, "recovery_status"] = "existing_accepted_pair"
    out.loc[paired_mask, "recovered_pair_id"] = out.loc[paired_mask, "divided_pair_id"]
    out.loc[paired_mask, "recovery_paired_opposite_segment_id"] = out.loc[paired_mask, "paired_opposite_segment_id"]
    out.loc[paired_mask, "recovery_confidence"] = out.loc[paired_mask, "geometric_direction_confidence"]
    out.loc[paired_mask, "recovery_method"] = "existing_divided_carriageway_pairing_preserved"
    out.loc[paired_mask, "recovery_reason"] = "existing_accepted_pair_preserved"
    out.loc[paired_mask, "promotion_recommendation"] = "promote_after_spot_check"

    role_excluded = out["roadway_directionality_type"].eq("divided") & out["roadway_role_class"].isin(ROLE_EXCLUDED)
    out.loc[role_excluded & ~paired_mask, "recovery_status"] = "still_unresolved_role_excluded"
    out.loc[role_excluded & ~paired_mask, "promotion_recommendation"] = "keep_unresolved"
    out.loc[role_excluded & ~paired_mask, "recovery_reason"] = "roadway_role_excluded_from_generic_divided_recovery"

    mainline_unpaired = (
        out["roadway_directionality_type"].eq("divided")
        & out["roadway_role_class"].eq(ROLE_INCLUDED)
        & out["divided_pairing_status"].eq("unpaired")
    )
    for idx, row in out.loc[mainline_unpaired].iterrows():
        segment_id = str(row["oriented_segment_id"])
        best = best_by_segment.get(segment_id)
        if best:
            out.at[idx, "recovery_status"] = best["recovery_status"]
            out.at[idx, "recovered_pair_id"] = best["recovered_pair_id"]
            out.at[idx, "recovery_paired_opposite_segment_id"] = best["paired_opposite_segment_id"]
            for column in [
                "anchor_cluster_id",
                "local_axis_method",
                "side_score",
                "parallelism_score",
                "projected_overlap_score",
                "lateral_separation_ft",
                "recovery_confidence",
                "recovery_method",
                "recovery_reason",
                "promotion_recommendation",
            ]:
                out.at[idx, column] = best[column]
        else:
            out.at[idx, "recovery_status"] = _unresolved_reason(row)
            out.at[idx, "promotion_recommendation"] = "keep_unresolved"
            out.at[idx, "recovery_reason"] = "no_defensible_recovery_candidate"

    out["true_vehicle_direction_inferred"] = False
    out["recovery_true_vehicle_direction_inferred"] = False
    return out


def _summary(enriched: gpd.GeoDataFrame, candidates: pd.DataFrame, existing_pairs: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    divided = enriched.loc[enriched["roadway_directionality_type"].eq("divided")]
    add("crash_data_read", False, "This recovery prototype reads only roadway graph, role, and no-crash pairing outputs.")
    add("divided_rows_reviewed", len(divided), "")
    add("existing_accepted_pair_rows_preserved", int(enriched["recovery_status"].eq("existing_accepted_pair").sum()), "")
    add("existing_accepted_pairs_preserved", int(existing_pairs["divided_pair_id"].nunique()) if not existing_pairs.empty else 0, "")
    add("newly_recovered_high_rows", int(enriched["recovery_status"].eq("recovered_high").sum()), "")
    add("newly_recovered_medium_rows", int(enriched["recovery_status"].eq("recovered_medium").sum()), "")
    add("newly_recovered_high_medium_pairs", int(enriched.loc[enriched["recovery_status"].isin(["recovered_high", "recovered_medium"]), "recovered_pair_id"].nunique()), "")
    add("low_confidence_review_only_rows", int(enriched["recovery_status"].eq("recovered_low_review_only").sum()), "")
    add("candidate_rows_written", len(candidates), "")
    for status, count in enriched["recovery_status"].value_counts(dropna=False).sort_index().items():
        add(f"recovery_status_{status}", int(count), "")
    for recommendation, count in enriched["promotion_recommendation"].value_counts(dropna=False).sort_index().items():
        add(f"promotion_recommendation_{recommendation}", int(count), "")
    add("true_vehicle_direction_inferred_not_false", int(enriched["true_vehicle_direction_inferred"].astype(str).str.lower().ne("false").sum()), "")
    excluded = enriched.loc[enriched["roadway_role_class"].isin(["ramp_or_connector", "frontage_or_service_road", "turn_lane_or_auxiliary", "unknown_review"])]
    add("generic_recovery_rows_with_excluded_roles", int(excluded["recovery_status"].isin(["recovered_high", "recovered_medium", "recovered_low_review_only"]).sum()), "")
    add("accepted_pair_ids_overwritten", 0, "Recovery writes separate recovery fields and does not edit existing divided_pair_id/status fields.")
    return pd.DataFrame(rows)


def _by_route_type(enriched: gpd.GeoDataFrame) -> pd.DataFrame:
    route_type = enriched.get("rte_type_name", pd.Series("", index=enriched.index)).where(
        enriched.get("rte_type_name", pd.Series("", index=enriched.index)).astype(str).ne(""),
        enriched.get("RTE_TYPE_N", pd.Series("", index=enriched.index)),
    )
    frame = pd.DataFrame(enriched.drop(columns="geometry")).copy()
    frame["route_type_report"] = route_type
    return (
        frame.loc[frame["roadway_directionality_type"].eq("divided")]
        .groupby(["route_type_report", "roadway_role_class", "recovery_status", "promotion_recommendation"], dropna=False)
        .size()
        .reset_index(name="row_count")
        .sort_values(["route_type_report", "roadway_role_class", "recovery_status"])
    )


def _by_reason(enriched: gpd.GeoDataFrame) -> pd.DataFrame:
    return (
        pd.DataFrame(enriched.drop(columns="geometry"))
        .loc[lambda df: df["roadway_directionality_type"].eq("divided")]
        .groupby(["recovery_status", "recovery_reason", "roadway_role_class"], dropna=False)
        .size()
        .reset_index(name="row_count")
        .sort_values(["recovery_status", "recovery_reason", "roadway_role_class"])
    )


def _promotion_recommendation(enriched: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    for recommendation, group in enriched.groupby("promotion_recommendation", dropna=False):
        if not recommendation:
            continue
        rows.append(
            {
                "promotion_recommendation": recommendation,
                "row_count": len(group),
                "pair_count": int(group["recovered_pair_id"].replace("", pd.NA).dropna().nunique()),
                "recommended_action": (
                    "Small QGIS spot check before promotion into a later geometric direction revision."
                    if recommendation == "promote_after_spot_check"
                    else "Keep as review-only evidence." if recommendation == "review_only" else "Keep unresolved."
                ),
            }
        )
    return pd.DataFrame(rows)


def _load_optional(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    return pd.DataFrame()


def build_divided_pairing_recovery(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    geojson = output_root / "review/geojson/current"

    role_segments = _read_wkt_csv(tables / "signal_oriented_roadway_segments_role_enriched.csv")
    existing_enriched = _read_wkt_csv(tables / "signal_oriented_roadway_segments_divided_pairing_enriched.csv")
    existing_pairs = pd.read_csv(tables / "divided_carriageway_pair_candidates.csv", dtype=str, keep_default_na=False)
    _ = pd.read_csv(tables / "roadway_role_classification.csv", dtype=str, keep_default_na=False)
    unresolved_reason = _load_optional(review / "divided_pairing_unresolved_reason_summary.csv")
    possible_improvements = _load_optional(review / "divided_pairing_unresolved_possible_logic_improvements.csv")
    _ = _load_optional(tables / "roadway_graph_edges.csv")
    _ = _load_optional(tables / "roadway_graph_nodes.csv")

    existing_cols = [
        "oriented_segment_id",
        "divided_pair_id",
        "paired_opposite_segment_id",
        "divided_pairing_status",
        "pairing_problem_reason",
        "carriageway_side_of_reference",
        "geometric_movement_orientation",
        "geometric_direction_confidence",
    ]
    role_segments = role_segments.drop(columns=[column for column in existing_cols[1:] if column in role_segments.columns], errors="ignore")
    merged = role_segments.merge(
        pd.DataFrame(existing_enriched[[column for column in existing_cols if column in existing_enriched.columns]]),
        on="oriented_segment_id",
        how="left",
    )
    segments = _prepare_segments(gpd.GeoDataFrame(merged, geometry="geometry"))
    clusters = _anchor_clusters(segments)
    segments["anchor_cluster_id"] = segments["oriented_segment_id"].map(clusters).fillna("")

    candidates, best_by_segment = _build_recovery_candidates(segments)
    enriched = _enrich_segments(segments, best_by_segment).drop(columns=["_start_xy", "_end_xy", "_bearing", "_line_signature"], errors="ignore")

    required_candidate_cols = [
        "original_oriented_segment_id",
        "recovered_pair_id",
        "paired_opposite_segment_id",
        "route_stem",
        "anchor_cluster_id",
        "local_axis_method",
        "side_score",
        "parallelism_score",
        "projected_overlap_score",
        "lateral_separation_ft",
        "recovery_confidence",
        "recovery_method",
        "recovery_reason",
        "promotion_recommendation",
        "true_vehicle_direction_inferred",
    ]
    for column in required_candidate_cols:
        if column not in candidates.columns:
            candidates[column] = ""
    candidates = candidates[required_candidate_cols + [column for column in candidates.columns if column not in required_candidate_cols]]

    recovered = enriched.loc[enriched["recovery_status"].isin(["recovered_high", "recovered_medium", "recovered_low_review_only"])].copy()
    still_unresolved = enriched.loc[enriched["recovery_status"].astype(str).str.startswith("still_unresolved")].copy()
    problems = pd.concat(
        [
            still_unresolved,
            enriched.loc[enriched["recovery_status"].eq("recovered_low_review_only")],
        ],
        ignore_index=True,
    )
    summary = _summary(enriched, candidates, existing_pairs)
    by_route = _by_route_type(enriched)
    by_reason = _by_reason(enriched)
    promotion = _promotion_recommendation(enriched)

    if not unresolved_reason.empty:
        summary = pd.concat(
            [
                summary,
                pd.DataFrame(
                    {
                        "metric": [f"input_unresolved_reason_{row['unpaired_reason']}" for _, row in unresolved_reason.iterrows()],
                        "value": [row.get("unpaired_rows", "") for _, row in unresolved_reason.iterrows()],
                        "notes": [row.get("diagnostic_basis", "") for _, row in unresolved_reason.iterrows()],
                    }
                ),
            ],
            ignore_index=True,
        )
    if not possible_improvements.empty:
        for _, row in possible_improvements.iterrows():
            summary.loc[len(summary)] = {
                "metric": f"input_possible_improvement_{row.get('possible_improvement', '')}",
                "value": row.get("affected_unpaired_rows", ""),
                "notes": row.get("recommendation", ""),
            }

    _write_csv(candidates, tables / "divided_carriageway_pair_candidates_recovery.csv")
    _write_csv(enriched, tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv")
    _write_csv(summary, review / "divided_pairing_recovery_summary.csv")
    _write_csv(recovered, review / "divided_pairing_recovered_rows.csv")
    _write_csv(still_unresolved, review / "divided_pairing_still_unresolved_rows.csv")
    _write_csv(problems, review / "divided_pairing_recovery_problem_rows.csv")
    _write_csv(by_route, review / "divided_pairing_recovery_by_route_type.csv")
    _write_csv(by_reason, review / "divided_pairing_recovery_by_reason.csv")
    _write_csv(promotion, review / "divided_pairing_recovery_promotion_recommendation.csv")

    _write_geojson(
        gpd.GeoDataFrame(recovered.head(REVIEW_SAMPLE_SIZE), geometry="geometry"),
        geojson / "divided_pairing_recovery_review.geojson",
    )
    _write_geojson(
        gpd.GeoDataFrame(still_unresolved.head(REVIEW_SAMPLE_SIZE), geometry="geometry"),
        geojson / "divided_pairing_still_unresolved_review.geojson",
    )

    return {
        "candidate_csv": str(tables / "divided_carriageway_pair_candidates_recovery.csv"),
        "enriched_csv": str(tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv"),
        "summary_csv": str(review / "divided_pairing_recovery_summary.csv"),
        "recovered_rows_csv": str(review / "divided_pairing_recovered_rows.csv"),
        "still_unresolved_csv": str(review / "divided_pairing_still_unresolved_rows.csv"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build no-crash review-only divided pairing recovery candidates.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_divided_pairing_recovery(output_root=args.output_root)
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
