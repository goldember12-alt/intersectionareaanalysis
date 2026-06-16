from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt
from shapely.geometry import LineString, Point


OUTPUT_ROOT = Path("work/output/roadway_graph")
TABLES_DIR = Path("tables/current")
REVIEW_DIR = Path("review/current/endpoint_junction_qa")
LAYER_DIR = REVIEW_DIR / "endpoint_junction_qa_static_review_layers"

FEET_PER_METER = 3.280839895
NEAR_MISS_ENDPOINT_FT = 35.0
ENDPOINT_CLUSTER_FT = 45.0
SUPPORTED_JUNCTION_FT = 8.0
SIGNAL_OFFSET_REVIEW_FT = 60.0
MAX_INTERSECTION_FLAGS = 2500

UNRESOLVED_RECOVERY_STATUSES = {
    "recovered_low_review_only",
    "still_unresolved_source_missing",
    "still_unresolved_endpoint_or_one_sided",
    "still_unresolved_ambiguous_geometry",
    "still_unresolved_role_excluded",
    "still_unresolved_unknown",
}

ROLE_EXCLUDED = {
    "ramp_or_connector",
    "frontage_or_service_road",
    "turn_lane_or_auxiliary",
    "unknown_review",
}

GEOMETRY_COLUMNS = ["geometry", "diagnostic_geometry"]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _read_wkt_csv(path: Path) -> gpd.GeoDataFrame:
    frame = _read_csv(path)
    if frame.empty:
        return gpd.GeoDataFrame(frame, geometry=[])
    if "geometry" in frame.columns:
        frame["geometry"] = frame["geometry"].map(lambda value: wkt.loads(value) if str(value).strip() else None)
        return gpd.GeoDataFrame(frame, geometry="geometry")
    return gpd.GeoDataFrame(frame)


def _write_csv(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = pd.DataFrame(frame.copy())
    for column in GEOMETRY_COLUMNS:
        if column in out.columns:
            out[column] = out[column].map(lambda geom: geom.wkt if geom is not None else "")
    out.to_csv(path, index=False)


def _write_geojson(frame: pd.DataFrame | gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        return
    out = frame.copy()
    geometry_column = "diagnostic_geometry" if "diagnostic_geometry" in out.columns else "geometry"
    out = gpd.GeoDataFrame(out, geometry=geometry_column)
    out = out[out.geometry.notna()].copy()
    if out.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    else:
        out.to_file(path, driver="GeoJSON")


def _num(series: pd.Series | None, default: float = 0.0) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").fillna(default)


def _text(row: pd.Series, column: str) -> str:
    if column not in row.index:
        return ""
    return str(row[column])


def _route_category(row: pd.Series) -> str:
    return _text(row, "rte_category") or _text(row, "RTE_CATEGO")


def _endpoint_nodes(nodes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if nodes.empty or "node_type" not in nodes.columns:
        return gpd.GeoDataFrame(nodes.head(0), geometry="geometry")
    return nodes[nodes["node_type"].eq("road_endpoint") & nodes.geometry.notna()].copy()


def _node_within(nodes: gpd.GeoDataFrame, geom, tolerance_ft: float) -> bool:
    if nodes.empty or geom is None:
        return False
    tolerance = tolerance_ft / FEET_PER_METER
    for index in nodes.sindex.query(geom.buffer(tolerance)):
        node_geom = nodes.geometry.iloc[int(index)]
        if node_geom is not None and geom.distance(node_geom) <= tolerance:
            return True
    return False


def _edge_endpoint_set(row: pd.Series) -> set[str]:
    return {_text(row, "from_graph_node_id"), _text(row, "to_graph_node_id")}


def _representative_point(geom) -> Point | None:
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Point":
        return geom
    if geom.geom_type.startswith("Multi"):
        for part in geom.geoms:
            point = _representative_point(part)
            if point is not None:
                return point
        return None
    if geom.geom_type == "LineString":
        return geom.interpolate(0.5, normalized=True)
    return geom.representative_point()


def _base_flag(row: pd.Series, category: str, confidence: str, evidence: str, geometry=None) -> dict[str, object]:
    return {
        "affected_record_id": _text(row, "oriented_segment_id")
        or _text(row, "graph_edge_id")
        or _text(row, "graph_node_id")
        or _text(row, "signal_id"),
        "oriented_segment_id": _text(row, "oriented_segment_id"),
        "graph_edge_id": _text(row, "base_graph_edge_id") or _text(row, "graph_edge_id"),
        "graph_node_id": _text(row, "graph_node_id"),
        "reference_signal_id": _text(row, "reference_signal_id") or _text(row, "signal_id"),
        "route_name": _text(row, "route_name") or _text(row, "matched_route_name"),
        "route_common": _text(row, "route_common") or _text(row, "matched_route_common"),
        "route_stem": _text(row, "route_stem"),
        "roadway_role_class": _text(row, "roadway_role_class"),
        "route_type_name": _text(row, "rte_type_name") or _text(row, "RTE_TYPE_N"),
        "route_category": _route_category(row),
        "from_anchor_type": _text(row, "from_anchor_type"),
        "to_anchor_type": _text(row, "to_anchor_type"),
        "opposite_anchor_type": _text(row, "opposite_anchor_type"),
        "opposite_anchor_step5_status": _text(row, "opposite_anchor_step5_status"),
        "divided_pairing_status": _text(row, "divided_pairing_status"),
        "recovery_status": _text(row, "recovery_status"),
        "diagnostic_category": category,
        "diagnostic_confidence": confidence,
        "evidence_summary": evidence,
        "distance_ft": "",
        "nearby_record_id": "",
        "nearby_route_common": "",
        "nearby_node_type": "",
        "affected_signal_count": "",
        "affected_unresolved_divided_rows": "",
        "geometry_source": "segment" if _text(row, "oriented_segment_id") else "graph",
        "diagnostic_geometry": geometry if geometry is not None else row.get("geometry", None),
    }


def _segment_level_flags(segments: gpd.GeoDataFrame) -> pd.DataFrame:
    flags: list[dict[str, object]] = []
    if segments.empty:
        return pd.DataFrame(flags)

    status = segments.get("recovery_status", pd.Series("", index=segments.index)).astype(str)
    pairing = segments.get("divided_pairing_status", pd.Series("", index=segments.index)).astype(str)
    role = segments.get("roadway_role_class", pd.Series("", index=segments.index)).astype(str)
    anchor = segments.get("opposite_anchor_type", pd.Series("", index=segments.index)).astype(str)
    step5 = segments.get("opposite_anchor_step5_status", pd.Series("", index=segments.index)).astype(str)

    unresolved = status.isin(UNRESOLVED_RECOVERY_STATUSES) | pairing.eq("unpaired_divided")
    mainline = role.eq("mainline_divided_carriageway")

    for _, row in segments[unresolved & mainline & step5.isin(["FALSE", "CONDITIONAL"])].iterrows():
        flags.append(
            _base_flag(
                row,
                "opposite_anchor_outside_true_reference_scope",
                "high",
                "opposite anchor may be a valid boundary but is not a TRUE Step 5 reference signal",
            )
        )

    endpoint_mask = unresolved & mainline & (
        status.eq("still_unresolved_endpoint_or_one_sided")
        | anchor.str.contains("endpoint|dead_end|non_signalized", case=False, na=False)
    )
    for _, row in segments[endpoint_mask].iterrows():
        category = "valid_dead_end_or_one_sided_edge"
        confidence = "medium"
        if _text(row, "recovery_status") == "still_unresolved_source_missing":
            category = "source_missing_leg_candidate"
            confidence = "medium"
        evidence = "segment terminates at non-TRUE, non-signalized, or endpoint boundary and should not be forced into pairing"
        flags.append(_base_flag(row, category, confidence, evidence))

    ambiguous_mask = unresolved & mainline & status.isin(
        {"still_unresolved_ambiguous_geometry", "recovered_low_review_only"}
    )
    for _, row in segments[ambiguous_mask].iterrows():
        flags.append(
            _base_flag(
                row,
                "divided_carriageway_representation_issue",
                "medium",
                "divided row remains unpaired because opposite carriageway geometry is ambiguous or low confidence",
            )
        )

    source_missing_mask = unresolved & mainline & status.eq("still_unresolved_source_missing")
    for _, row in segments[source_missing_mask].iterrows():
        flags.append(
            _base_flag(
                row,
                "source_missing_leg_candidate",
                "medium",
                "no clear opposite Travelway leg is visible in the current crash-ready graph subset",
            )
        )

    role_excluded_mask = unresolved & role.isin(ROLE_EXCLUDED)
    for _, row in segments[role_excluded_mask].iterrows():
        flags.append(
            _base_flag(
                row,
                "unknown_endpoint_junction_issue",
                "low",
                "unresolved row is outside generic mainline divided recovery scope because of roadway role",
            )
        )

    unknown_mask = unresolved & mainline & status.eq("still_unresolved_unknown")
    for _, row in segments[unknown_mask].iterrows():
        flags.append(
            _base_flag(
                row,
                "unknown_endpoint_junction_issue",
                "low",
                "unresolved row lacks enough non-crash evidence for a more specific endpoint/junction category",
            )
        )

    return pd.DataFrame(flags)


def _near_miss_endpoint_flags(nodes: gpd.GeoDataFrame, edges: gpd.GeoDataFrame) -> pd.DataFrame:
    endpoints = _endpoint_nodes(nodes).reset_index(drop=True)
    flags: list[dict[str, object]] = []
    if endpoints.empty:
        return pd.DataFrame(flags)

    tolerance = NEAR_MISS_ENDPOINT_FT / FEET_PER_METER
    endpoint_sindex = endpoints.sindex
    edge_sindex = edges.sindex if not edges.empty else None

    seen_pairs: set[tuple[str, str]] = set()
    for i, row in endpoints.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        for j in endpoint_sindex.query(geom.buffer(tolerance)):
            j = int(j)
            if i >= j:
                continue
            other = endpoints.iloc[j]
            if _text(row, "graph_node_id") == _text(other, "graph_node_id"):
                continue
            distance_ft = geom.distance(other.geometry) * FEET_PER_METER
            if distance_ft > NEAR_MISS_ENDPOINT_FT:
                continue
            pair = tuple(sorted([_text(row, "graph_node_id"), _text(other, "graph_node_id")]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            flag = _base_flag(
                row,
                "near_miss_endpoint",
                "medium" if distance_ft <= 20 else "low",
                "road endpoints are spatially close but remain separate graph nodes",
                geometry=LineString([geom, other.geometry]) if other.geometry is not None else geom,
            )
            flag["distance_ft"] = round(distance_ft, 3)
            flag["nearby_record_id"] = _text(other, "graph_node_id")
            flag["nearby_route_common"] = _text(other, "route_common")
            flag["nearby_node_type"] = _text(other, "node_type")
            flags.append(flag)

        if edge_sindex is None:
            continue
        for edge_index in edge_sindex.query(geom.buffer(tolerance)):
            edge = edges.iloc[int(edge_index)]
            if _text(row, "graph_node_id") in _edge_endpoint_set(edge):
                continue
            distance_ft = geom.distance(edge.geometry) * FEET_PER_METER
            if distance_ft > NEAR_MISS_ENDPOINT_FT:
                continue
            flag = _base_flag(
                row,
                "near_miss_endpoint",
                "medium" if distance_ft <= 20 else "low",
                "road endpoint is close to another graph edge but is not represented as a shared node",
                geometry=geom,
            )
            flag["distance_ft"] = round(distance_ft, 3)
            flag["nearby_record_id"] = _text(edge, "graph_edge_id")
            flag["nearby_route_common"] = _text(edge, "route_common")
            flag["nearby_node_type"] = "edge"
            flags.append(flag)
            break

    return pd.DataFrame(flags)


def _endpoint_cluster_flags(nodes: gpd.GeoDataFrame) -> pd.DataFrame:
    endpoints = _endpoint_nodes(nodes).reset_index(drop=True)
    if endpoints.empty:
        return pd.DataFrame()
    tolerance = ENDPOINT_CLUSTER_FT / FEET_PER_METER
    parent = list(range(len(endpoints)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    sindex = endpoints.sindex
    for i, geom in enumerate(endpoints.geometry):
        if geom is None:
            continue
        for j in sindex.query(geom.buffer(tolerance)):
            j = int(j)
            if i >= j:
                continue
            if geom.distance(endpoints.geometry.iloc[j]) <= tolerance:
                union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(endpoints)):
        groups[find(i)].append(i)

    flags: list[dict[str, object]] = []
    for indices in groups.values():
        if len(indices) < 3:
            continue
        subset = endpoints.iloc[indices]
        centroid = subset.geometry.union_all().centroid
        routes = sorted(set(subset.get("route_common", pd.Series("", index=subset.index)).astype(str)))
        row = subset.iloc[0]
        flag = _base_flag(
            row,
            "endpoint_cluster",
            "high" if len(indices) >= 5 else "medium",
            f"{len(indices)} road endpoints cluster within {ENDPOINT_CLUSTER_FT:.0f} ft; routes={'; '.join(routes[:5])}",
            geometry=centroid,
        )
        flag["nearby_record_id"] = ";".join(subset["graph_node_id"].astype(str).head(12))
        flag["affected_unresolved_divided_rows"] = ""
        flags.append(flag)
    return pd.DataFrame(flags)


def _intersection_flags(edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame) -> pd.DataFrame:
    if edges.empty:
        return pd.DataFrame()
    edges = edges[edges.geometry.notna()].reset_index(drop=True)
    flags: list[dict[str, object]] = []
    sindex = edges.sindex
    seen: set[tuple[str, str]] = set()

    for i, row in edges.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        for j in sindex.query(geom):
            j = int(j)
            if i >= j:
                continue
            other = edges.iloc[j]
            pair = tuple(sorted([_text(row, "graph_edge_id"), _text(other, "graph_edge_id")]))
            if pair in seen:
                continue
            seen.add(pair)
            if _edge_endpoint_set(row) & _edge_endpoint_set(other):
                continue
            if _text(row, "road_component_id") == _text(other, "road_component_id"):
                continue
            other_geom = other.geometry
            if other_geom is None or not geom.intersects(other_geom):
                continue
            intersection = _representative_point(geom.intersection(other_geom))
            if intersection is None:
                continue
            if _node_within(nodes, intersection, SUPPORTED_JUNCTION_FT):
                continue

            row_text = " ".join([_text(row, "route_common"), _text(row, "rte_ramp_code"), _text(row, "rte_category")]).lower()
            other_text = " ".join(
                [_text(other, "route_common"), _text(other, "rte_ramp_code"), _text(other, "rte_category")]
            ).lower()
            category = "crossing_without_supported_junction"
            confidence = "low"
            if not any(token in row_text + " " + other_text for token in ["ramp", "frontage", "service"]):
                category = "unsplit_intersection_candidate"
                confidence = "medium"
            flag = _base_flag(
                row,
                category,
                confidence,
                "edge geometries intersect without a nearby graph junction; this is review evidence, not automatic connectivity",
                geometry=intersection,
            )
            flag["nearby_record_id"] = _text(other, "graph_edge_id")
            flag["nearby_route_common"] = _text(other, "route_common")
            flags.append(flag)
            if len(flags) >= MAX_INTERSECTION_FLAGS:
                return pd.DataFrame(flags)
    return pd.DataFrame(flags)


def _signal_offset_flags(signals: gpd.GeoDataFrame, signal_adjacent_edges: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame()
    flags: list[dict[str, object]] = []
    adjacent_counts = signal_adjacent_edges.groupby("signal_id").size() if "signal_id" in signal_adjacent_edges else pd.Series()
    match_distance = _num(signals.get("match_distance_ft", pd.Series("", index=signals.index)))
    for idx, row in signals[match_distance.ge(SIGNAL_OFFSET_REVIEW_FT)].iterrows():
        adjacent_count = int(adjacent_counts.get(_text(row, "signal_id"), 0))
        confidence = "high" if adjacent_count <= 1 else "medium"
        flag = _base_flag(
            row,
            "signal_offset_candidate",
            confidence,
            f"signal match distance is {float(match_distance.loc[idx]):.1f} ft; adjacent edge count={adjacent_count}",
        )
        flag["distance_ft"] = round(float(match_distance.loc[idx]), 3)
        flags.append(flag)
    return pd.DataFrame(flags)


def _source_missing_leg_flags(
    segments: gpd.GeoDataFrame,
    signal_adjacent_edges: pd.DataFrame,
    existing_flags: pd.DataFrame,
) -> pd.DataFrame:
    if segments.empty or "reference_signal_id" not in segments.columns:
        return pd.DataFrame()
    flags: list[dict[str, object]] = []
    adjacent_counts = signal_adjacent_edges.groupby("signal_id").size() if "signal_id" in signal_adjacent_edges else pd.Series()
    flagged_keys = set(existing_flags.get("oriented_segment_id", pd.Series(dtype=str)).astype(str))
    status = segments.get("recovery_status", pd.Series("", index=segments.index)).astype(str)
    role = segments.get("roadway_role_class", pd.Series("", index=segments.index)).astype(str)
    candidates = segments[
        status.isin({"still_unresolved_unknown", "still_unresolved_endpoint_or_one_sided"})
        & role.eq("mainline_divided_carriageway")
    ]
    for _, row in candidates.iterrows():
        if _text(row, "oriented_segment_id") in flagged_keys:
            continue
        adjacent_count = int(adjacent_counts.get(_text(row, "reference_signal_id"), 0))
        if adjacent_count > 2:
            continue
        flag = _base_flag(
            row,
            "source_missing_leg_candidate",
            "medium",
            f"reference signal has only {adjacent_count} adjacent graph edges while divided row remains unresolved",
        )
        flag["affected_unresolved_divided_rows"] = "1"
        flags.append(flag)
    return pd.DataFrame(flags)


def _attach_signal_context(flags: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    if flags.empty or segments.empty or "reference_signal_id" not in flags.columns:
        return flags
    unresolved = segments[
        segments.get("recovery_status", pd.Series("", index=segments.index)).astype(str).isin(UNRESOLVED_RECOVERY_STATUSES)
        & segments.get("roadway_role_class", pd.Series("", index=segments.index)).astype(str).eq("mainline_divided_carriageway")
    ]
    unresolved_counts = unresolved.groupby("reference_signal_id").size()
    signal_counts = flags.groupby("reference_signal_id")["diagnostic_category"].transform("count")
    flags = flags.copy()
    flags["affected_signal_count"] = signal_counts
    flags["affected_unresolved_divided_rows"] = flags["reference_signal_id"].map(unresolved_counts).fillna(
        flags["affected_unresolved_divided_rows"]
    )
    return flags


def _summary(flags: pd.DataFrame) -> pd.DataFrame:
    if flags.empty:
        return pd.DataFrame(
            columns=[
                "diagnostic_category",
                "roadway_role_class",
                "route_type_name",
                "route_category",
                "opposite_anchor_type",
                "divided_pairing_status",
                "recovery_status",
                "flag_count",
            ]
        )
    groups = [
        "diagnostic_category",
        "roadway_role_class",
        "route_type_name",
        "route_category",
        "opposite_anchor_type",
        "divided_pairing_status",
        "recovery_status",
    ]
    return flags.groupby(groups, dropna=False).size().reset_index(name="flag_count").sort_values(
        ["diagnostic_category", "flag_count"], ascending=[True, False]
    )


def _signal_summary(flags: pd.DataFrame, segments: pd.DataFrame, signal_adjacent_edges: pd.DataFrame) -> pd.DataFrame:
    adjacent_counts = signal_adjacent_edges.groupby("signal_id").size().rename("adjacent_edge_count")
    unresolved = segments[
        segments.get("recovery_status", pd.Series("", index=segments.index)).astype(str).isin(UNRESOLVED_RECOVERY_STATUSES)
        & segments.get("roadway_role_class", pd.Series("", index=segments.index)).astype(str).eq("mainline_divided_carriageway")
    ]
    unresolved_counts = unresolved.groupby("reference_signal_id").size().rename("unresolved_divided_rows")
    base = pd.concat([adjacent_counts, unresolved_counts], axis=1).fillna(0).reset_index()
    base = base.rename(columns={"index": "reference_signal_id", "signal_id": "reference_signal_id"})
    if flags.empty:
        for column in [
            "endpoint_issue_count",
            "near_miss_issue_count",
            "possible_unsplit_intersection_count",
            "source_missing_leg_candidate_count",
            "signal_offset_candidate_count",
            "divided_representation_issue_count",
            "total_endpoint_junction_flags",
        ]:
            base[column] = 0
        return base.sort_values("unresolved_divided_rows", ascending=False)

    pivot = flags.pivot_table(
        index="reference_signal_id",
        columns="diagnostic_category",
        values="affected_record_id",
        aggfunc="count",
        fill_value=0,
    )
    for category in [
        "near_miss_endpoint",
        "unsplit_intersection_candidate",
        "source_missing_leg_candidate",
        "signal_offset_candidate",
        "divided_carriageway_representation_issue",
    ]:
        if category not in pivot.columns:
            pivot[category] = 0
    pivot["endpoint_issue_count"] = pivot[
        [column for column in pivot.columns if "endpoint" in str(column) or "one_sided" in str(column)]
    ].sum(axis=1)
    pivot["total_endpoint_junction_flags"] = pivot.sum(axis=1)
    out = base.merge(pivot.reset_index(), on="reference_signal_id", how="outer").fillna(0)
    out = out.rename(
        columns={
            "near_miss_endpoint": "near_miss_issue_count",
            "unsplit_intersection_candidate": "possible_unsplit_intersection_count",
            "source_missing_leg_candidate": "source_missing_leg_candidate_count",
            "signal_offset_candidate": "signal_offset_candidate_count",
            "divided_carriageway_representation_issue": "divided_representation_issue_count",
        }
    )
    keep = [
        "reference_signal_id",
        "adjacent_edge_count",
        "unresolved_divided_rows",
        "endpoint_issue_count",
        "near_miss_issue_count",
        "possible_unsplit_intersection_count",
        "source_missing_leg_candidate_count",
        "signal_offset_candidate_count",
        "divided_representation_issue_count",
        "total_endpoint_junction_flags",
    ]
    return out[[column for column in keep if column in out.columns]].sort_values(
        ["unresolved_divided_rows", "total_endpoint_junction_flags"], ascending=[False, False]
    )


def _ranked_queue(flags: pd.DataFrame) -> pd.DataFrame:
    if flags.empty:
        return flags.copy()
    category_weight = {
        "divided_carriageway_representation_issue": 35,
        "source_missing_leg_candidate": 32,
        "unsplit_intersection_candidate": 30,
        "near_miss_endpoint": 25,
        "endpoint_cluster": 24,
        "signal_offset_candidate": 22,
        "opposite_anchor_outside_true_reference_scope": 18,
        "crossing_without_supported_junction": 15,
        "valid_dead_end_or_one_sided_edge": 8,
        "unknown_endpoint_junction_issue": 5,
    }
    confidence_weight = {"high": 10, "medium": 6, "low": 2}
    out = flags.copy()
    unresolved = _num(out.get("affected_unresolved_divided_rows", pd.Series("", index=out.index)))
    signal_count = _num(out.get("affected_signal_count", pd.Series("", index=out.index)), default=1)
    distance = _num(out.get("distance_ft", pd.Series("", index=out.index)))
    out["review_priority_score"] = (
        out["diagnostic_category"].map(category_weight).fillna(0)
        + out["diagnostic_confidence"].map(confidence_weight).fillna(0)
        + unresolved.clip(upper=25) * 1.5
        + signal_count.clip(upper=10) * 0.5
        + distance.where(out["diagnostic_category"].eq("near_miss_endpoint"), 0).rdiv(50).clip(lower=0, upper=5)
    ).round(3)
    columns = [
        "review_priority_score",
        "diagnostic_category",
        "diagnostic_confidence",
        "affected_record_id",
        "oriented_segment_id",
        "graph_edge_id",
        "graph_node_id",
        "reference_signal_id",
        "route_name",
        "route_common",
        "route_stem",
        "roadway_role_class",
        "route_type_name",
        "route_category",
        "divided_pairing_status",
        "recovery_status",
        "opposite_anchor_type",
        "opposite_anchor_step5_status",
        "distance_ft",
        "nearby_record_id",
        "nearby_route_common",
        "affected_unresolved_divided_rows",
        "affected_signal_count",
        "evidence_summary",
    ]
    return out[[column for column in columns if column in out.columns]].sort_values(
        ["review_priority_score", "diagnostic_category"], ascending=[False, True]
    )


def _examples(flags: pd.DataFrame) -> pd.DataFrame:
    if flags.empty:
        return flags.copy()
    samples = []
    for category, group in flags.groupby("diagnostic_category", dropna=False):
        samples.append(group.head(8))
    return pd.concat(samples, ignore_index=True)


def _write_layers(flags: pd.DataFrame, layer_dir: Path) -> None:
    mapping = {
        "near_miss_endpoint": "near_miss_endpoints.geojson",
        "unsplit_intersection_candidate": "unsplit_intersection_candidates.geojson",
        "endpoint_cluster": "endpoint_clusters.geojson",
        "source_missing_leg_candidate": "source_missing_leg_candidates.geojson",
        "signal_offset_candidate": "signal_offset_candidates.geojson",
        "divided_carriageway_representation_issue": "divided_carriageway_representation_issues.geojson",
    }
    for category, filename in mapping.items():
        subset = flags[flags["diagnostic_category"].eq(category)].copy() if not flags.empty else flags
        _write_geojson(subset, layer_dir / filename)


def _write_optional_html(flags: pd.DataFrame, path: Path) -> None:
    path.with_suffix(".txt").write_text(
        "Static HTML map was not created because the source GeoJSON layers do not carry a geographic CRS. "
        "Use the GeoJSON review layers or add an explicit projection step before web-map export.\n",
        encoding="utf-8",
    )
    if path.exists():
        path.unlink()


def _write_findings(
    path: Path,
    flags: pd.DataFrame,
    summary: pd.DataFrame,
    signal_summary: pd.DataFrame,
    inputs: list[Path],
) -> None:
    counts = flags["diagnostic_category"].value_counts().sort_index().to_dict() if not flags.empty else {}
    top_signals = signal_summary.head(10) if not signal_summary.empty else pd.DataFrame()
    lines = [
        "# Endpoint/Junction QA Methodology Findings",
        "",
        "**Status: CURRENT ACTIVE REVIEW DIAGNOSTIC.** This is a no-crash, review-only roadway_graph QA pass.",
        "",
        "## Boundary",
        "",
        "This diagnostic reads roadway graph, signal graph, Step 5 segment, role, and pairing/recovery outputs only. It does not read crash records, assign crashes, use crash direction fields, infer upstream/downstream from crashes, overwrite accepted divided pairs, promote recovery candidates, change the default geometric direction model, require QGIS or ArcGIS, or automatically repair graph geometry.",
        "",
        "## Main Counts",
        "",
    ]
    if counts:
        for category, count in counts.items():
            lines.append(f"- `{category}`: {count}")
    else:
        lines.append("- no endpoint/junction QA flags were generated")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The unresolved divided-pairing bottleneck is primarily a graph-build QA question rather than a reason to tune pair thresholds. Endpoint-supported connectivity, signal offset, source leg completeness, and unsplit/crossing geometry cases need to be visible before additional divided-pair candidates can be promoted.",
            "",
            "Source-data incompleteness is represented by source-missing-leg and divided-carriageway-representation flags. Graph-construction limitations are represented by near-miss endpoint, endpoint cluster, unsplit intersection, crossing-without-supported-junction, and signal-offset flags. Valid methodological exclusions remain separate as valid dead-end or one-sided-edge cases.",
            "",
            "Crossing geometry is not treated as connectivity. Near-miss endpoints are not treated as errors by default. These outputs are review queues and QA evidence, not repairs.",
            "",
            "## Highest-Impact Signals",
            "",
        ]
    )
    if top_signals.empty:
        lines.append("No per-signal QA concentration was available.")
    else:
        for _, row in top_signals.iterrows():
            lines.append(
                "- `{}`: unresolved_divided_rows={}, total_endpoint_junction_flags={}".format(
                    row.get("reference_signal_id", ""),
                    int(float(row.get("unresolved_divided_rows", 0))),
                    int(float(row.get("total_endpoint_junction_flags", 0))),
                )
            )
    lines.extend(
        [
            "",
            "## Methodology Implications",
            "",
            "- Add endpoint/junction QA as a first-class graph validation layer before broad divided-pairing recovery.",
            "- Preserve the no-automatic-repair policy: do not split, snap, or connect geometry without reviewed source support.",
            "- Keep digitized direction, route measure direction, allowed/restricted travel evidence, and inferred vehicle movement conceptually separate.",
            "- Use Network Dataset / Network Analyst concepts only as QA vocabulary: endpoint connectivity, junction visibility, and build/rebuild validation.",
            "",
            "## Inputs Read",
            "",
        ]
    )
    for input_path in inputs:
        lines.append(f"- `{input_path.as_posix()}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_recommendations(path: Path) -> None:
    text = """# Endpoint/Junction QA Methodology Recommendations

## Recommendation

Update current roadway_graph methodology docs in a later documentation patch to make endpoint/junction QA an explicit graph-build validation surface. Do not make ArcGIS Network Analyst or QGIS a production dependency, and do not automatically repair geometry from this diagnostic.

## Recommended Documentation Changes

- Add endpoint-supported connectivity language: shared endpoints and explicit source-supported junctions are connectivity evidence; crossings and near misses are review evidence.
- Add node/junction QA as a first-class validation step after roadway graph builds and after any graph-rule change.
- Add review categories for `near_miss_endpoint`, `endpoint_cluster`, `unsplit_intersection_candidate`, `crossing_without_supported_junction`, `source_missing_leg_candidate`, `signal_offset_candidate`, and `divided_carriageway_representation_issue`.
- Explain source-missing-leg handling separately from valid dead ends and one-sided edges.
- State the no-automatic-repair policy: do not snap endpoints, split lines, connect crossings, or promote divided pairs without reviewed source support.
- Require build/rebuild QA comparisons after graph construction rule changes: node counts by type, edge counts, adjacent-edge signal counts, signal offset counts, endpoint clusters, near-miss endpoints, unsplit/crossing review candidates, and Step 5 eligibility counts.

## What Should Not Change

- Do not treat crossing geometry as supported graph connectivity.
- Do not use crash direction fields or crash distributions for endpoint/junction QA.
- Do not promote low-confidence divided-pairing recovery candidates.
- Do not replace the repository-native Python/GeoPandas roadway_graph workflow with ArcGIS Network Analyst.

## Why

The divided-pairing recovery review found no promotable high/medium candidates. The next bottleneck is graph topology, source-leg completeness, and endpoint/junction evidence. Making those categories explicit will improve validation without broadening the method or hiding unresolved cases.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(output_root: Path = OUTPUT_ROOT) -> dict[str, object]:
    tables = output_root / TABLES_DIR
    review = output_root / REVIEW_DIR
    layer_dir = output_root / LAYER_DIR

    input_paths = [
        tables / "roadway_graph_nodes.csv",
        tables / "roadway_graph_edges.csv",
        tables / "signal_graph_nodes.csv",
        tables / "signal_adjacent_edges.csv",
        tables / "signal_oriented_roadway_segments_crash_ready.csv",
        tables / "signal_oriented_roadway_segments_role_enriched.csv",
        tables / "signal_oriented_roadway_segments_divided_pairing_enriched.csv",
        tables / "signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv",
        output_root
        / "review/current/codex_native_divided_pairing_recovery_review/still_unresolved_diagnostic_summary.csv",
        output_root
        / "review/current/codex_native_divided_pairing_recovery_review/recovery_candidate_false_positive_screen.csv",
    ]

    nodes = _read_wkt_csv(input_paths[0])
    edges = _read_wkt_csv(input_paths[1])
    signals = _read_wkt_csv(input_paths[2])
    signal_adjacent_edges = _read_wkt_csv(input_paths[3])
    _ = _read_csv(input_paths[4])
    _ = _read_csv(input_paths[5])
    _ = _read_csv(input_paths[6])
    segments = _read_wkt_csv(input_paths[7])
    _ = _read_csv(input_paths[8])
    _ = _read_csv(input_paths[9])

    pieces = [
        _segment_level_flags(segments),
        _near_miss_endpoint_flags(nodes, edges),
        _endpoint_cluster_flags(nodes),
        _intersection_flags(edges, nodes),
        _signal_offset_flags(signals, signal_adjacent_edges),
    ]
    initial_flags = pd.concat([piece for piece in pieces if not piece.empty], ignore_index=True) if pieces else pd.DataFrame()
    source_missing = _source_missing_leg_flags(segments, signal_adjacent_edges, initial_flags)
    if not source_missing.empty:
        initial_flags = pd.concat([initial_flags, source_missing], ignore_index=True)

    flags = _attach_signal_context(initial_flags, segments)
    summary = _summary(flags)
    signal_summary = _signal_summary(flags, segments, signal_adjacent_edges)
    queue = _ranked_queue(flags)
    examples = _examples(flags)

    _write_csv(summary, review / "endpoint_junction_qa_summary.csv")
    _write_csv(signal_summary, review / "endpoint_junction_qa_signal_summary.csv")
    _write_csv(flags, review / "endpoint_junction_qa_segment_flags.csv")
    _write_csv(queue, review / "endpoint_junction_qa_ranked_review_queue.csv")
    _write_csv(examples, review / "endpoint_junction_qa_examples.csv")
    _write_layers(flags, layer_dir)
    _write_optional_html(flags, review / "endpoint_junction_qa_static_review_map.html")
    _write_findings(review / "endpoint_junction_qa_methodology_findings.md", flags, summary, signal_summary, input_paths)
    _write_recommendations(Path("docs/design/endpoint_junction_qa_methodology_recommendations.md"))

    manifest = {
        "input_paths": [path.as_posix() for path in input_paths],
        "output_dir": review.as_posix(),
        "crash_data_read": False,
        "crashes_assigned": False,
        "crash_direction_used": False,
        "accepted_pairs_overwritten": False,
        "geometric_direction_outputs_modified": False,
        "arcgis_or_qgis_required": False,
        "automatic_graph_repair_performed": False,
        "diagnostic_category_counts": flags["diagnostic_category"].value_counts().sort_index().to_dict()
        if not flags.empty
        else {},
    }
    (review / "endpoint_junction_qa_run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="No-crash endpoint/junction QA diagnostic for roadway_graph.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    manifest = run(args.output_root)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
