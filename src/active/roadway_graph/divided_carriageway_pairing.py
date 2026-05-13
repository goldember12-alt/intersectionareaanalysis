from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import Point


OUTPUT_ROOT = Path("work/output/roadway_graph")
FEET_PER_METER = 3.280839895
SIDE_DISTANCE_TOLERANCE_FT = 8.0
HIGH_SIDE_DISTANCE_FT = 16.0
MAX_SAME_LEG_BEARING_DIFF_DEG = 35.0
PAIR_REVIEW_SAMPLE_SIZE = 500
UNPAIRED_REVIEW_SAMPLE_SIZE = 500


def _read_wkt_csv(path: Path) -> gpd.GeoDataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    frame["geometry"] = frame["geometry"].map(wkt.loads)
    return gpd.GeoDataFrame(frame, geometry="geometry")


def _write_csv(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(frame.copy())
    if "geometry" in out.columns and isinstance(frame, gpd.GeoDataFrame):
        out["geometry"] = frame.geometry.to_wkt()
    out.to_csv(path, index=False)


def _write_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    else:
        frame.to_file(path, driver="GeoJSON")


def _xy(coord: tuple[float, ...]) -> tuple[float, float]:
    return float(coord[0]), float(coord[1])


def _line_endpoints(geometry) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    if geometry is None or geometry.is_empty or not hasattr(geometry, "coords"):
        return None, None
    coords = list(geometry.coords)
    if len(coords) < 2:
        return None, None
    return _xy(coords[0]), _xy(coords[-1])


def _line_midpoint(geometry) -> Point | None:
    if geometry is None or geometry.is_empty:
        return None
    try:
        return geometry.interpolate(0.5, normalized=True)
    except Exception:
        return None


def _bearing_degrees(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return None
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _angular_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def _route_stem(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\b|[-_ ])(NB|SB|EB|WB|NORTHBOUND|SOUTHBOUND|EASTBOUND|WESTBOUND)$", "", text, flags=re.I)
    text = re.sub(r"([A-Z]+-\d+)([NSEW])$", r"\1", text, flags=re.I)
    text = re.sub(r"([A-Z]+-\d+)(NB|SB|EB|WB)$", r"\1", text, flags=re.I)
    return text.strip()


def _side_of_reference(
    reference_start: tuple[float, float],
    reference_end: tuple[float, float],
    test_point: Point,
) -> tuple[str, float]:
    vx = reference_end[0] - reference_start[0]
    vy = reference_end[1] - reference_start[1]
    wx = test_point.x - reference_start[0]
    wy = test_point.y - reference_start[1]
    length = math.hypot(vx, vy)
    if length == 0:
        return "ambiguous", 0.0
    signed = vx * wy - vy * wx
    distance_ft = abs(signed) / length * FEET_PER_METER
    if distance_ft <= SIDE_DISTANCE_TOLERANCE_FT:
        return "center", distance_ft
    return ("left" if signed > 0 else "right"), distance_ft


def _line_signature(geometry) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    start, end = _line_endpoints(geometry)
    if start is None or end is None:
        return None, None
    rounded_start = (round(start[0], 2), round(start[1], 2))
    rounded_end = (round(end[0], 2), round(end[1], 2))
    return rounded_start, rounded_end


def _prepare_segments(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = segments.copy()
    for column in out.columns:
        if column != "geometry":
            out[column] = out[column].astype("object")
    out["route_pair_stem"] = out.get("route_common", pd.Series("", index=out.index)).map(_route_stem)
    starts = []
    ends = []
    bearings = []
    signatures = []
    for geometry in out.geometry:
        start, end = _line_endpoints(geometry)
        starts.append(start)
        ends.append(end)
        bearings.append("" if start is None or end is None else _bearing_degrees(start, end))
        signatures.append(_line_signature(geometry))
    out["_start_xy"] = starts
    out["_end_xy"] = ends
    out["_segment_bearing"] = bearings
    out["_line_signature"] = signatures
    return out


def _evaluate_pair(row_a: pd.Series, row_b: pd.Series) -> dict[str, object]:
    start_a = row_a["_start_xy"]
    end_a = row_a["_end_xy"]
    start_b = row_b["_start_xy"]
    end_b = row_b["_end_xy"]
    bearing_a = row_a["_segment_bearing"]
    bearing_b = row_b["_segment_bearing"]
    if not all([start_a, end_a, start_b, end_b]) or bearing_a == "" or bearing_b == "":
        return {"candidate_status": "unresolved", "pairing_problem_reason": "invalid_or_empty_geometry"}
    bearing_diff = _angular_diff(float(bearing_a), float(bearing_b))
    if bearing_diff > MAX_SAME_LEG_BEARING_DIFF_DEG:
        return {"candidate_status": "unresolved", "pairing_problem_reason": "not_same_leg_bearing"}
    if row_a.get("base_graph_edge_id") == row_b.get("base_graph_edge_id"):
        return {"candidate_status": "unresolved", "pairing_problem_reason": "same_base_graph_edge"}
    if row_a.get("road_component_id") == row_b.get("road_component_id"):
        return {"candidate_status": "unresolved", "pairing_problem_reason": "same_road_component"}
    if row_a.get("_line_signature") == row_b.get("_line_signature"):
        return {"candidate_status": "unresolved", "pairing_problem_reason": "same_physical_geometry_signature"}

    reference_start = ((start_a[0] + start_b[0]) / 2.0, (start_a[1] + start_b[1]) / 2.0)
    reference_end = ((end_a[0] + end_b[0]) / 2.0, (end_a[1] + end_b[1]) / 2.0)
    reference_bearing = _bearing_degrees(reference_start, reference_end)
    if reference_bearing is None:
        return {"candidate_status": "unresolved", "pairing_problem_reason": "zero_length_reference_vector"}

    midpoint_a = _line_midpoint(row_a.geometry)
    midpoint_b = _line_midpoint(row_b.geometry)
    if midpoint_a is None or midpoint_b is None:
        return {"candidate_status": "unresolved", "pairing_problem_reason": "invalid_midpoint_geometry"}
    side_a, distance_a = _side_of_reference(reference_start, reference_end, midpoint_a)
    side_b, distance_b = _side_of_reference(reference_start, reference_end, midpoint_b)
    sides = {side_a, side_b}
    if not {"left", "right"}.issubset(sides):
        if "center" in sides:
            reason = "side_assignment_near_centerline"
        else:
            reason = "candidate_geometries_do_not_bracket_reference"
        return {
            "candidate_status": "ambiguous",
            "pairing_problem_reason": reason,
            "reference_bearing": reference_bearing,
            "side_a": side_a,
            "side_b": side_b,
            "distance_a": distance_a,
            "distance_b": distance_b,
            "bearing_diff": bearing_diff,
        }

    if side_a == "right":
        right = row_a
        left = row_b
        right_score = distance_a
        left_score = distance_b
    else:
        right = row_b
        left = row_a
        right_score = distance_b
        left_score = distance_a

    min_side = min(right_score, left_score)
    if min_side >= HIGH_SIDE_DISTANCE_FT and bearing_diff <= 20.0:
        quality = "bracketed_parallel_clear"
        confidence = "high"
    elif min_side > SIDE_DISTANCE_TOLERANCE_FT:
        quality = "bracketed_parallel_acceptable"
        confidence = "medium"
    else:
        quality = "bracketed_but_close"
        confidence = "low"

    return {
        "candidate_status": "paired",
        "pairing_problem_reason": "",
        "reference_bearing": reference_bearing,
        "side_a": side_a,
        "side_b": side_b,
        "distance_a": distance_a,
        "distance_b": distance_b,
        "bearing_diff": bearing_diff,
        "right_segment_id": right["oriented_segment_id"],
        "left_segment_id": left["oriented_segment_id"],
        "right_side_score": right_score,
        "left_side_score": left_score,
        "pair_geometry_quality": quality,
        "pair_confidence": confidence,
    }


def _build_pair_candidates(segments: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict[str, dict[str, object]]]:
    divided = segments.loc[segments["roadway_directionality_type"].eq("divided")].copy()
    pair_rows: list[dict[str, object]] = []
    assigned: set[str] = set()
    enrichment: dict[str, dict[str, object]] = {}
    pair_number = 0

    group_cols = ["reference_signal_id", "route_pair_stem"]
    for (_signal_id, _route_stem), group in divided.groupby(group_cols, dropna=False, sort=False):
        group = group.loc[~group["oriented_segment_id"].isin(assigned)].copy()
        candidate_evals: list[dict[str, object]] = []
        rows = list(group.iterrows())
        for i, (_, row_a) in enumerate(rows):
            for _, row_b in rows[i + 1 :]:
                result = _evaluate_pair(row_a, row_b)
                if result.get("candidate_status") not in {"paired", "ambiguous"}:
                    continue
                score = min(float(result.get("right_side_score", 0.0) or result.get("distance_a", 0.0)), float(result.get("left_side_score", 0.0) or result.get("distance_b", 0.0)))
                candidate_evals.append({"row_a": row_a, "row_b": row_b, "result": result, "score": score})

        candidate_evals.sort(key=lambda item: item["score"], reverse=True)
        for candidate in candidate_evals:
            row_a = candidate["row_a"]
            row_b = candidate["row_b"]
            result = candidate["result"]
            id_a = row_a["oriented_segment_id"]
            id_b = row_b["oriented_segment_id"]
            if id_a in assigned or id_b in assigned:
                continue
            if result["candidate_status"] != "paired":
                continue

            pair_number += 1
            pair_id = f"divpair_{pair_number:06d}"
            assigned.update({id_a, id_b})
            right_id = result["right_segment_id"]
            left_id = result["left_segment_id"]
            right_row = row_a if id_a == right_id else row_b
            left_row = row_a if id_a == left_id else row_b
            pair_rows.append(
                {
                    "divided_pair_id": pair_id,
                    "segment_family_id": f"{right_row['segment_family_id']}|{left_row['segment_family_id']}",
                    "reference_signal_id": right_row["reference_signal_id"],
                    "anchor_a_id": right_row["from_anchor_id"],
                    "anchor_b_id": f"{right_row['to_anchor_id']}|{left_row['to_anchor_id']}",
                    "anchor_a_type": right_row["from_anchor_type"],
                    "anchor_b_type": f"{right_row['to_anchor_type']}|{left_row['to_anchor_type']}",
                    "a_to_b_reference_bearing": round(float(result["reference_bearing"]), 3),
                    "right_side_segment_id": right_id,
                    "left_side_segment_id": left_id,
                    "a_to_b_candidate_segment_id": right_id,
                    "b_to_a_candidate_segment_id": left_id,
                    "right_side_score": round(float(result["right_side_score"]), 3),
                    "left_side_score": round(float(result["left_side_score"]), 3),
                    "pair_geometry_quality": result["pair_geometry_quality"],
                    "pair_confidence": result["pair_confidence"],
                    "pairing_method": "same_signal_route_stem_parallel_bracketing_right_hand_rule",
                    "pairing_problem_reason": "",
                    "true_vehicle_direction_inferred": False,
                }
            )
            enrichment[right_id] = {
                "divided_pair_id": pair_id,
                "paired_opposite_segment_id": left_id,
                "carriageway_side_of_reference": "right",
                "geometric_movement_orientation": "A_to_B",
                "geometric_direction_method": "divided_right_hand_side_rule",
                "geometric_direction_confidence": result["pair_confidence"],
                "divided_pairing_status": "paired",
            }
            enrichment[left_id] = {
                "divided_pair_id": pair_id,
                "paired_opposite_segment_id": right_id,
                "carriageway_side_of_reference": "left",
                "geometric_movement_orientation": "B_to_A",
                "geometric_direction_method": "divided_right_hand_side_rule",
                "geometric_direction_confidence": result["pair_confidence"],
                "divided_pairing_status": "paired",
            }

    return pd.DataFrame(pair_rows), enrichment


def _enrich_segments(segments: gpd.GeoDataFrame, enrichment: dict[str, dict[str, object]]) -> gpd.GeoDataFrame:
    out = segments.copy()
    for column in out.columns:
        if column != "geometry":
            out[column] = out[column].astype("object")
    out["divided_pair_id"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["paired_opposite_segment_id"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["divided_pairing_status"] = pd.Series(["not_applicable"] * len(out), index=out.index, dtype=object)
    out["pairing_problem_reason"] = pd.Series([""] * len(out), index=out.index, dtype=object)
    out["true_vehicle_direction_inferred"] = pd.Series([False] * len(out), index=out.index, dtype=object)

    divided_mask = out["roadway_directionality_type"].eq("divided")
    out.loc[divided_mask, "divided_pairing_status"] = "unpaired"
    out.loc[divided_mask, "carriageway_side_of_reference"] = "ambiguous"
    out.loc[divided_mask, "geometric_movement_orientation"] = "unresolved"
    out.loc[divided_mask, "geometric_direction_method"] = "unresolved"
    out.loc[divided_mask, "geometric_direction_confidence"] = "unresolved"
    out.loc[divided_mask, "pairing_problem_reason"] = "no_clear_opposite_carriageway_pair_found"

    non_divided_mask = ~divided_mask
    out.loc[non_divided_mask, "carriageway_side_of_reference"] = "not_applicable"
    out.loc[non_divided_mask, "geometric_movement_orientation"] = "not_applicable"
    out.loc[non_divided_mask, "geometric_direction_method"] = "not_applicable"
    out.loc[non_divided_mask, "geometric_direction_confidence"] = "not_applicable"

    for segment_id, values in enrichment.items():
        mask = out["oriented_segment_id"].eq(segment_id)
        for column, value in values.items():
            out.loc[mask, column] = value
        out.loc[mask, "pairing_problem_reason"] = ""

    return out


def _summary(
    segments: gpd.GeoDataFrame,
    pair_candidates: pd.DataFrame,
    *,
    divided_candidate_rows: int,
    signal_adjacent_rows: int,
    roadway_edge_rows: int,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    divided = segments.loc[segments["roadway_directionality_type"].eq("divided")]
    add("crash_data_read", False, "This diagnostic reads only roadway graph and Step 5 segment/bin outputs.")
    add("segment_rows_enriched", len(segments), "")
    add("divided_rows", len(divided), "")
    for status, count in divided["divided_pairing_status"].value_counts(dropna=False).sort_index().items():
        add(f"divided_rows_{status}", int(count), "")
    add("divided_pair_candidate_rows", len(pair_candidates), "")
    if not pair_candidates.empty:
        for confidence, count in pair_candidates["pair_confidence"].value_counts(dropna=False).sort_index().items():
            add(f"divided_pairs_{confidence}_confidence", int(count), "")
    add("divided_pairs_with_both_A_to_B_and_B_to_A", len(pair_candidates), "Every accepted pair has one right-side A_to_B and one left-side B_to_A candidate.")
    add("divided_rows_still_unresolved", int(divided["geometric_movement_orientation"].eq("unresolved").sum()), "")
    add("true_vehicle_direction_inferred_not_false", int(segments["true_vehicle_direction_inferred"].astype(str).str.lower().ne("false").sum()), "")
    add("divided_edge_directional_candidate_rows_read", divided_candidate_rows, "Read for no-crash roadway graph context.")
    add("signal_adjacent_edge_rows_read", signal_adjacent_rows, "Read for no-crash roadway graph context.")
    add("roadway_graph_edge_rows_read", roadway_edge_rows, "Read for no-crash roadway graph context.")
    return pd.DataFrame(rows)


def _problem_rows(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    divided = segments.loc[segments["roadway_directionality_type"].eq("divided")].copy()
    return divided.loc[~divided["divided_pairing_status"].eq("paired")].copy()


def _examples(pair_candidates: pd.DataFrame, segments: gpd.GeoDataFrame) -> pd.DataFrame:
    paired = pair_candidates.sort_values(["pair_confidence", "right_side_score", "left_side_score"], ascending=[True, False, False]).head(50)
    unpaired = segments.loc[
        segments["roadway_directionality_type"].eq("divided") & segments["divided_pairing_status"].eq("unpaired")
    ].head(50)
    rows = []
    for _, row in paired.iterrows():
        rows.append({**row.to_dict(), "example_type": "paired_candidate"})
    for _, row in unpaired.iterrows():
        rows.append(
            {
                "divided_pair_id": "",
                "segment_family_id": row.get("segment_family_id", ""),
                "reference_signal_id": row.get("reference_signal_id", ""),
                "anchor_a_id": row.get("from_anchor_id", ""),
                "anchor_b_id": row.get("to_anchor_id", ""),
                "anchor_a_type": row.get("from_anchor_type", ""),
                "anchor_b_type": row.get("to_anchor_type", ""),
                "a_to_b_reference_bearing": "",
                "right_side_segment_id": "",
                "left_side_segment_id": "",
                "a_to_b_candidate_segment_id": "",
                "b_to_a_candidate_segment_id": "",
                "right_side_score": "",
                "left_side_score": "",
                "pair_geometry_quality": "",
                "pair_confidence": "unresolved",
                "pairing_method": "",
                "pairing_problem_reason": row.get("pairing_problem_reason", ""),
                "true_vehicle_direction_inferred": False,
                "example_type": "unpaired_row",
            }
        )
    return pd.DataFrame(rows)


def build_divided_carriageway_pairing(output_root: Path = OUTPUT_ROOT) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    geojson = output_root / "review/geojson/current"

    segments = _read_wkt_csv(tables / "signal_oriented_roadway_segments_geometric_direction.csv")
    _ = _read_wkt_csv(tables / "signal_oriented_segment_bins_geometric_direction.csv")
    roadway_edges = pd.read_csv(tables / "roadway_graph_edges.csv", usecols=["graph_edge_id"], dtype=str)
    signal_adjacent = pd.read_csv(tables / "signal_adjacent_edges.csv", usecols=["graph_edge_id"], dtype=str)
    divided_candidates = pd.read_csv(tables / "divided_edge_directional_candidates.csv", usecols=["graph_edge_id"], dtype=str)

    prepared = _prepare_segments(segments)
    pair_candidates, enrichment = _build_pair_candidates(prepared)
    enriched = _enrich_segments(segments, enrichment)

    summary = _summary(
        enriched,
        pair_candidates,
        divided_candidate_rows=len(divided_candidates),
        signal_adjacent_rows=len(signal_adjacent),
        roadway_edge_rows=len(roadway_edges),
    )
    problems = _problem_rows(enriched)
    unpaired = enriched.loc[
        enriched["roadway_directionality_type"].eq("divided") & enriched["divided_pairing_status"].eq("unpaired")
    ].copy()
    examples = _examples(pair_candidates, enriched)

    _write_csv(pair_candidates, tables / "divided_carriageway_pair_candidates.csv")
    _write_csv(enriched, tables / "signal_oriented_roadway_segments_divided_pairing_enriched.csv")
    _write_csv(summary, review / "divided_carriageway_pairing_summary.csv")
    _write_csv(problems, review / "divided_carriageway_pairing_problem_rows.csv")
    _write_csv(unpaired, review / "divided_carriageway_unpaired_rows.csv")
    _write_csv(examples, review / "divided_carriageway_pairing_examples.csv")

    paired_review = enriched.loc[enriched["divided_pairing_status"].eq("paired")].head(PAIR_REVIEW_SAMPLE_SIZE).copy()
    unpaired_review = unpaired.head(UNPAIRED_REVIEW_SAMPLE_SIZE).copy()
    _write_geojson(gpd.GeoDataFrame(paired_review, geometry="geometry"), geojson / "divided_carriageway_pairing_review.geojson")
    _write_geojson(gpd.GeoDataFrame(unpaired_review, geometry="geometry"), geojson / "divided_carriageway_unpaired_review.geojson")

    return {
        "pair_candidates_csv": str(tables / "divided_carriageway_pair_candidates.csv"),
        "enriched_segments_csv": str(tables / "signal_oriented_roadway_segments_divided_pairing_enriched.csv"),
        "summary_csv": str(review / "divided_carriageway_pairing_summary.csv"),
        "problem_rows_csv": str(review / "divided_carriageway_pairing_problem_rows.csv"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build no-crash divided carriageway pairing diagnostics.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    outputs = build_divided_carriageway_pairing(output_root=args.output_root)
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
