from __future__ import annotations

import argparse
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import wkt


OUTPUT_ROOT = Path("work/output/roadway_graph")
NORMALIZED_ROOT = Path("artifacts/normalized")
REVIEW_SAMPLE_SIZE = 600

ROLE_COLUMNS = [
    "roadway_role_class",
    "roadway_role_reason",
    "roadway_role_confidence",
    "requires_manual_review",
]

SEGMENT_PRESERVE_COLUMNS = [
    "oriented_segment_id",
    "segment_family_id",
    "base_graph_edge_id",
    "reference_signal_id",
    "roadway_directionality_type",
    "divided_pairing_status",
]

SOURCE_FIELD_COLUMNS = [
    "route_name",
    "route_common",
    "route_id",
    "event_source",
    "road_component_id",
    "source_road_row_id",
    "facility_code",
    "facility_text",
    "RIM_FACILI",
    "roadway_division_status",
    "logical_segment_mode",
    "median_code",
    "median_text",
    "RIM_MEDIAN",
    "MEDIAN_WID",
    "MEDIAN_W_1",
    "RTE_TYPE_N",
    "rte_type_name",
    "RTE_CATEGO",
    "rte_category",
    "RTE_RAMP_C",
    "rte_ramp_code",
    "RIM_ACCESS",
    "rim_access",
    "RIM_COUPLE",
    "LANE_REVER",
]


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


def _clean(value: object) -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "null", "<null>"}:
        return ""
    return text


def _lower_join(row: pd.Series, columns: list[str]) -> str:
    return " | ".join(_clean(row.get(column)).lower() for column in columns if _clean(row.get(column)))


def _has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, flags=re.I) for pattern in patterns)


def _is_divided_source(row: pd.Series) -> bool:
    facility = _lower_join(row, ["facility_text", "RIM_FACILI", "roadway_directionality_type", "roadway_division_status"])
    median = _lower_join(row, ["median_text", "RIM_MEDIAN"])
    code = _clean(row.get("facility_code"))
    median_code = _clean(row.get("median_code"))
    return (
        _has_any(facility, [r"\btwo-way divided\b", r"\bone-way divided\b", r"\bdivided_source_carriageway\b"])
        or code in {"2", "4"}
        or _clean(row.get("roadway_directionality_type")).lower() == "divided"
        or _clean(row.get("roadway_division_status")).lower() == "divided"
        or median_code in {"2", "3", "4", "6", "7"}
        or _has_any(median, [r"\bmedian exists\b", r"\bbarrier\b", r"\bpositive barrier\b"])
    )


def _is_undivided_source(row: pd.Series) -> bool:
    facility = _lower_join(row, ["facility_text", "RIM_FACILI", "roadway_directionality_type", "roadway_division_status", "logical_segment_mode"])
    code = _clean(row.get("facility_code"))
    median_code = _clean(row.get("median_code"))
    return (
        "undivided" in facility
        or "centerline" in facility
        or code in {"1", "3"}
        or median_code == "1"
        or _clean(row.get("roadway_directionality_type")).lower() == "undivided"
        or _clean(row.get("roadway_division_status")).lower() == "undivided"
    )


def _classify_row(row: pd.Series) -> dict[str, object]:
    route_text = _lower_join(row, ["route_name", "RTE_NM", "route_common", "RTE_COMMON"])
    type_text = _lower_join(row, ["RTE_TYPE_N", "rte_type_name", "RTE_CATEGO", "rte_category"])
    facility_text = _lower_join(row, ["facility_text", "RIM_FACILI", "median_text", "RIM_MEDIAN", "logical_segment_mode"])
    all_text = " | ".join([route_text, type_text, facility_text])
    ramp_code = _clean(row.get("RTE_RAMP_C")) or _clean(row.get("rte_ramp_code"))
    rim_couple = _clean(row.get("RIM_COUPLE")).upper()

    if ramp_code or _has_any(type_text, [r"\bramp\b", r"\bconnector\b", r"\binterchange\b"]) or _has_any(
        route_text, [r"\bramp\b", r"\bconnector\b", r"\bloop\b", r"\bslip\b", r"\binterchange\b"]
    ):
        return {
            "roadway_role_class": "ramp_or_connector",
            "roadway_role_reason": "ramp_or_connector_source_field",
            "roadway_role_confidence": "high" if ramp_code or "ramp" in type_text else "medium",
            "requires_manual_review": False,
        }

    if _has_any(type_text, [r"\bfrontage\b"]) or _has_any(route_text, [r"\bfrontage\b", r"\bservice road\b", r"\bserv(?:ice)? rd\b", r"\bcollector[- ]?distributor\b", r"\bc-d\b"]):
        return {
            "roadway_role_class": "frontage_or_service_road",
            "roadway_role_reason": "frontage_or_service_source_field",
            "roadway_role_confidence": "high" if "frontage" in type_text else "medium",
            "requires_manual_review": False,
        }

    lane_reversible = _clean(row.get("LANE_REVER"))
    if _has_any(all_text, [r"\bturn lane\b", r"\bauxiliary\b", r"\breversible\b", r"\bmedian crossover\b", r"\bcrossover\b"]) or lane_reversible not in {"", "0", "0.0", "N"}:
        return {
            "roadway_role_class": "turn_lane_or_auxiliary",
            "roadway_role_reason": "turn_auxiliary_or_reversible_source_field",
            "roadway_role_confidence": "medium",
            "requires_manual_review": False,
        }

    one_way_facility = _has_any(facility_text, [r"\bone-way\b", r"\bone way\b"])
    if rim_couple == "Y" or one_way_facility:
        return {
            "roadway_role_class": "one_way_pair_candidate",
            "roadway_role_reason": "one_way_facility_or_rim_couple",
            "roadway_role_confidence": "high" if rim_couple == "Y" else "medium",
            "requires_manual_review": False,
        }

    if _is_divided_source(row):
        directionality = _clean(row.get("roadway_directionality_type")).lower()
        division_status = _clean(row.get("roadway_division_status")).lower()
        if _is_undivided_source(row) and directionality != "divided" and division_status != "divided":
            return {
                "roadway_role_class": "unknown_review",
                "roadway_role_reason": "conflicting_divided_undivided_source_fields",
                "roadway_role_confidence": "low",
                "requires_manual_review": True,
            }
        return {
            "roadway_role_class": "mainline_divided_carriageway",
            "roadway_role_reason": "remaining_divided_source_field_after_exclusions",
            "roadway_role_confidence": "medium",
            "requires_manual_review": False,
        }

    if _is_undivided_source(row):
        return {
            "roadway_role_class": "undivided_centerline",
            "roadway_role_reason": "remaining_undivided_or_centerline_source_field",
            "roadway_role_confidence": "medium",
            "requires_manual_review": False,
        }

    return {
        "roadway_role_class": "unknown_review",
        "roadway_role_reason": "missing_or_weak_roadway_role_evidence",
        "roadway_role_confidence": "low",
        "requires_manual_review": True,
    }


def _load_roads_source_fields(path: Path) -> pd.DataFrame:
    columns = [
        "RTE_NM",
        "RTE_COMMON",
        "RTE_ID",
        "EVENT_SOUR",
        "RIM_FACILI",
        "RIM_MEDIAN",
        "MEDIAN_WID",
        "MEDIAN_W_1",
        "RTE_TYPE_N",
        "RTE_CATEGO",
        "RTE_RAMP_C",
        "RIM_ACCESS",
        "RIM_COUPLE",
        "LANE_REVER",
    ]
    roads = pd.read_parquet(path, columns=[column for column in columns if column])
    roads = roads.reset_index(names="source_road_row_id")
    roads["source_road_row_id"] = roads["source_road_row_id"].astype(str)
    return roads.astype("object")


def _merge_source_fields(edges: pd.DataFrame, roads: pd.DataFrame) -> pd.DataFrame:
    out = edges.copy()
    out["source_road_row_id"] = out.get("source_road_row_id", pd.Series("", index=out.index)).astype(str)
    return out.merge(roads, on="source_road_row_id", how="left", suffixes=("", "_source"))


def _classify(frame: pd.DataFrame) -> pd.DataFrame:
    role_rows = frame.apply(_classify_row, axis=1, result_type="expand")
    return pd.concat([frame.reset_index(drop=True), role_rows.reset_index(drop=True)], axis=1)


def _classification_table(segments: pd.DataFrame, graph_edges: pd.DataFrame) -> pd.DataFrame:
    segment_cols = [column for column in SEGMENT_PRESERVE_COLUMNS + SOURCE_FIELD_COLUMNS + ROLE_COLUMNS if column in segments.columns]
    edge_cols = [column for column in ["base_graph_edge_id", "graph_edge_id"] + SOURCE_FIELD_COLUMNS + ROLE_COLUMNS if column in graph_edges.columns]

    segment_rows = segments[segment_cols].copy()
    segment_rows.insert(0, "roadway_role_record_type", "step5_crash_ready_segment")
    segment_rows["graph_edge_id"] = segment_rows.get("base_graph_edge_id", "")

    edge_rows = graph_edges[edge_cols].copy()
    edge_rows.insert(0, "roadway_role_record_type", "roadway_graph_edge")
    if "base_graph_edge_id" not in edge_rows.columns:
        edge_rows["base_graph_edge_id"] = edge_rows.get("graph_edge_id", "")
    for column in SEGMENT_PRESERVE_COLUMNS:
        if column not in edge_rows.columns:
            edge_rows[column] = ""

    ordered = [
        "roadway_role_record_type",
        "oriented_segment_id",
        "segment_family_id",
        "base_graph_edge_id",
        "graph_edge_id",
        "reference_signal_id",
        "roadway_directionality_type",
        "divided_pairing_status",
    ]
    for column in SOURCE_FIELD_COLUMNS + ROLE_COLUMNS:
        if column not in ordered:
            ordered.append(column)
    for column in ordered:
        if column not in segment_rows.columns:
            segment_rows[column] = ""
        if column not in edge_rows.columns:
            edge_rows[column] = ""
    return pd.concat([segment_rows[ordered], edge_rows[ordered]], ignore_index=True)


def _count_summary(frame: pd.DataFrame, group_cols: list[str], count_col: str = "row_count") -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=group_cols + [count_col])
    return frame.groupby(group_cols, dropna=False).size().reset_index(name=count_col).sort_values(group_cols)


def _build_summary(segments: pd.DataFrame, graph_edges: pd.DataFrame, roads_rows: int) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(metric: str, value: object, notes: str = "") -> None:
        rows.append({"metric": metric, "value": value, "notes": notes})

    add("bounded_question", "roadway_role_classification_before_divided_pairing_recovery", "Uses roadway source fields and graph fields only.")
    add("crash_data_read", False, "No crash table or crash assignment output is read by this prototype.")
    add("normalized_roads_rows_read", roads_rows, "Read only source roadway fields from artifacts/normalized/roads.parquet.")
    add("crash_ready_step5_segment_rows_classified", len(segments), "")
    add("relevant_graph_edge_rows_classified", len(graph_edges), "Graph edges referenced by the crash-ready Step 5 segments.")
    add("accepted_divided_pair_rows_overwritten", 0, "Existing divided_pair_id and divided_pairing_status fields are preserved only.")
    for role, count in segments["roadway_role_class"].value_counts(dropna=False).sort_index().items():
        add(f"segment_role_{role}", int(count), "")
    paired = segments.loc[segments["divided_pairing_status"].eq("paired")]
    unpaired = segments.loc[segments["divided_pairing_status"].eq("unpaired")]
    for role, count in paired["roadway_role_class"].value_counts(dropna=False).sort_index().items():
        add(f"paired_divided_segment_role_{role}", int(count), "")
    for role, count in unpaired["roadway_role_class"].value_counts(dropna=False).sort_index().items():
        add(f"unpaired_divided_segment_role_{role}", int(count), "")

    secondary_street = unpaired.loc[
        unpaired["rte_type_name"].isin(["Secondary Route", "Street Route"])
        | unpaired["RTE_TYPE_N"].isin(["Secondary Route", "Street Route"])
    ]
    for route_type, group in secondary_street.groupby(secondary_street["rte_type_name"].where(secondary_street["rte_type_name"].ne(""), secondary_street["RTE_TYPE_N"]), dropna=False):
        for role, count in group["roadway_role_class"].value_counts(dropna=False).sort_index().items():
            add(f"unpaired_divided_{route_type}_{role}", int(count), "Required Secondary/Street Route unpaired role split.")

    add(
        "future_pairing_recovery_eligible_roles",
        "mainline_divided_carriageway; one_way_pair_candidate",
        "Use mainline_divided_carriageway first. one_way_pair_candidate needs a separate reviewed one-way couplet method, not divided-carriageway assumptions.",
    )
    add(
        "future_pairing_recovery_ineligible_roles",
        "ramp_or_connector; frontage_or_service_road; turn_lane_or_auxiliary; undivided_centerline; unknown_review",
        "Keep these out of divided-carriageway recovery unless a later manual review explicitly promotes a case.",
    )
    return pd.DataFrame(rows)


def _review_examples(segments: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    priority = {
        "unknown_review": 0,
        "ramp_or_connector": 1,
        "frontage_or_service_road": 2,
        "turn_lane_or_auxiliary": 3,
        "one_way_pair_candidate": 4,
        "mainline_divided_carriageway": 5,
        "undivided_centerline": 6,
    }
    out = segments.copy()
    out["_priority"] = out["roadway_role_class"].map(priority).fillna(99)
    out["_review_order_status"] = out["divided_pairing_status"].map({"unpaired": 0, "paired": 1, "not_applicable": 2}).fillna(3)
    return out.sort_values(["_priority", "_review_order_status", "reference_signal_id", "route_common"]).head(REVIEW_SAMPLE_SIZE).drop(
        columns=["_priority", "_review_order_status"], errors="ignore"
    )


def build_roadway_role_classification(
    *,
    output_root: Path = OUTPUT_ROOT,
    normalized_root: Path = NORMALIZED_ROOT,
) -> dict[str, str]:
    tables = output_root / "tables/current"
    review = output_root / "review/current"
    geojson = output_root / "review/geojson/current"

    roads = _load_roads_source_fields(normalized_root / "roads.parquet")
    segments = _read_wkt_csv(tables / "signal_oriented_roadway_segments_divided_pairing_enriched.csv")
    crash_ready_ids = pd.read_csv(
        tables / "signal_oriented_roadway_segments_crash_ready.csv",
        usecols=["oriented_segment_id"],
        dtype=str,
        keep_default_na=False,
    )
    segments = segments.loc[segments["oriented_segment_id"].isin(set(crash_ready_ids["oriented_segment_id"]))].copy()

    graph_edge_ids = sorted(set(segments["base_graph_edge_id"].dropna().astype(str)))
    graph_edges = _read_wkt_csv(tables / "roadway_graph_edges.csv")
    graph_edges = graph_edges.loc[graph_edges["graph_edge_id"].isin(graph_edge_ids)].copy()
    graph_edges = graph_edges.rename(columns={"graph_edge_id": "base_graph_edge_id"})
    graph_edges["graph_edge_id"] = graph_edges["base_graph_edge_id"]

    graph_edges = _classify(_merge_source_fields(graph_edges, roads))
    role_by_edge = graph_edges[["base_graph_edge_id"] + ROLE_COLUMNS + [column for column in SOURCE_FIELD_COLUMNS if column in graph_edges.columns]].copy()
    segments = segments.merge(role_by_edge, on="base_graph_edge_id", how="left", suffixes=("", "_edge_role"))
    for column in ROLE_COLUMNS:
        edge_column = f"{column}_edge_role"
        if edge_column in segments.columns:
            segments[column] = segments[edge_column]
    for column in SOURCE_FIELD_COLUMNS:
        edge_column = f"{column}_edge_role"
        if edge_column in segments.columns and column not in segments.columns:
            segments[column] = segments[edge_column]
    segments = segments.drop(columns=[column for column in segments.columns if column.endswith("_edge_role")], errors="ignore")

    classification = _classification_table(pd.DataFrame(segments.drop(columns="geometry")), pd.DataFrame(graph_edges.drop(columns="geometry")))
    summary = _build_summary(pd.DataFrame(segments.drop(columns="geometry")), pd.DataFrame(graph_edges.drop(columns="geometry")), len(roads))
    by_pairing = _count_summary(
        pd.DataFrame(segments.drop(columns="geometry")),
        ["divided_pairing_status", "roadway_directionality_type", "roadway_role_class", "roadway_role_confidence", "requires_manual_review"],
    )
    unpaired_divided = pd.DataFrame(segments.loc[segments["divided_pairing_status"].eq("unpaired")].drop(columns="geometry"))
    unpaired_summary = _count_summary(
        unpaired_divided,
        ["rte_type_name", "rte_category", "roadway_role_class", "roadway_role_reason", "roadway_role_confidence", "requires_manual_review"],
    )
    role_counts = _count_summary(pd.DataFrame(segments.drop(columns="geometry")), ["roadway_role_class", "roadway_role_confidence", "requires_manual_review"])
    examples = _review_examples(segments)

    _write_csv(classification, tables / "roadway_role_classification.csv")
    _write_csv(segments, tables / "signal_oriented_roadway_segments_role_enriched.csv")
    _write_csv(summary, review / "roadway_role_classification_summary.csv")
    _write_csv(by_pairing, review / "roadway_role_by_pairing_status_summary.csv")
    _write_csv(unpaired_summary, review / "unpaired_divided_by_roadway_role_summary.csv")
    _write_csv(examples, review / "roadway_role_review_examples.csv")
    _write_csv(role_counts, review / "roadway_role_counts.csv")
    _write_geojson(gpd.GeoDataFrame(examples, geometry="geometry"), geojson / "roadway_role_review_examples.geojson")

    return {
        "classification_csv": str(tables / "roadway_role_classification.csv"),
        "role_enriched_segments_csv": str(tables / "signal_oriented_roadway_segments_role_enriched.csv"),
        "summary_csv": str(review / "roadway_role_classification_summary.csv"),
        "pairing_status_summary_csv": str(review / "roadway_role_by_pairing_status_summary.csv"),
        "unpaired_divided_summary_csv": str(review / "unpaired_divided_by_roadway_role_summary.csv"),
        "review_examples_csv": str(review / "roadway_role_review_examples.csv"),
        "review_examples_geojson": str(geojson / "roadway_role_review_examples.geojson"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify roadway roles for roadway graph Step 5 rows without crash data.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--normalized-root", type=Path, default=NORMALIZED_ROOT)
    args = parser.parse_args(argv)
    outputs = build_roadway_role_classification(output_root=args.output_root, normalized_root=args.normalized_root)
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
