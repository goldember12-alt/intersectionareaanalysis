from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd


OUTPUT_ROOT = Path("work/output/roadway_graph")
TABLES_CURRENT = Path("tables/current")
REVIEW_CURRENT = Path("review/current")
REVIEW_GEOJSON_CURRENT = Path("review/geojson/current")


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _write_geojson(frame: gpd.GeoDataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        return path
    frame.to_file(path, driver="GeoJSON")
    return path


def _first_signal_points(signal_graph_nodes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    ordered = signal_graph_nodes.copy()
    if "match_distance_ft" in ordered.columns:
        ordered["match_distance_ft_sort"] = pd.to_numeric(ordered["match_distance_ft"], errors="coerce")
        ordered = ordered.sort_values(["signal_id", "match_distance_ft_sort", "matched_graph_node_id"])
        ordered = ordered.drop(columns=["match_distance_ft_sort"])
    else:
        ordered = ordered.sort_values(["signal_id"])
    return ordered.drop_duplicates("signal_id").copy()


def _join_signal_points(
    review_rows: pd.DataFrame,
    signal_points: gpd.GeoDataFrame,
    layer_filename: str,
    unmapped_rows: list[dict[str, object]],
) -> gpd.GeoDataFrame:
    review = review_rows.drop(columns=["geometry"], errors="ignore").copy()
    point_cols = [col for col in signal_points.columns if col not in review.columns and col != "geometry"]
    merged = review.merge(signal_points[["signal_id", *point_cols, "geometry"]], on="signal_id", how="left")
    missing = merged["geometry"].isna()
    if missing.any():
        for row in merged.loc[missing].itertuples(index=False):
            row_dict = row._asdict()
            unmapped_rows.append(
                {
                    "layer_filename": layer_filename,
                    "source_table": row_dict.get("source_table", ""),
                    "signal_id": row_dict.get("signal_id", ""),
                    "graph_edge_id": row_dict.get("graph_edge_id", ""),
                    "reason": "signal_id did not join to signal_graph_nodes geometry",
                }
            )
        merged = merged.loc[~missing].copy()
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=signal_points.crs)


def _join_edges(
    review_rows: pd.DataFrame,
    adjacent_edges: gpd.GeoDataFrame,
    layer_filename: str,
    unmapped_rows: list[dict[str, object]],
    use_signal_and_edge: bool = True,
) -> gpd.GeoDataFrame:
    review = review_rows.drop(columns=["geometry"], errors="ignore").copy()
    edge_cols = [col for col in adjacent_edges.columns if col not in review.columns and col != "geometry"]
    if use_signal_and_edge and {"signal_id", "graph_edge_id"}.issubset(review.columns):
        join_keys = ["signal_id", "graph_edge_id"]
    elif "signal_id" in review.columns:
        join_keys = ["signal_id"]
    else:
        join_keys = ["graph_edge_id"]
    merged = review.merge(adjacent_edges[[*join_keys, *edge_cols, "geometry"]], on=join_keys, how="left")
    missing = merged["geometry"].isna()
    if missing.any():
        for row in merged.loc[missing].itertuples(index=False):
            row_dict = row._asdict()
            unmapped_rows.append(
                {
                    "layer_filename": layer_filename,
                    "source_table": row_dict.get("source_table", ""),
                    "signal_id": row_dict.get("signal_id", ""),
                    "graph_edge_id": row_dict.get("graph_edge_id", ""),
                    "reason": f"{'/'.join(join_keys)} did not join to signal_adjacent_edges geometry",
                }
            )
        merged = merged.loc[~missing].copy()
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=adjacent_edges.crs)


def _manual_edge_rows(manual: pd.DataFrame, adjacent_edges: gpd.GeoDataFrame) -> pd.DataFrame:
    manual = manual.copy()
    edge_rows = manual.loc[manual["graph_edge_id"].astype(str).ne("")].copy()
    signal_only_columns = [col for col in ["source_table", "review_group", "signal_id"] if col in manual.columns]
    signal_only = manual.loc[manual["graph_edge_id"].astype(str).eq(""), signal_only_columns].drop_duplicates()
    if not signal_only.empty:
        expanded = signal_only.merge(
            pd.DataFrame(adjacent_edges.drop(columns="geometry", errors="ignore")),
            on="signal_id",
            how="left",
        )
        expanded = expanded.loc[expanded["graph_edge_id"].astype(str).ne("")].copy()
        edge_rows = pd.concat([edge_rows, expanded], ignore_index=True, sort=False)
    return edge_rows.drop_duplicates(["review_group", "signal_id", "graph_edge_id"]).copy()


def _candidate_review_layer(
    rows: pd.DataFrame,
    adjacent_edges: gpd.GeoDataFrame,
    signal_points: gpd.GeoDataFrame,
    layer_filename: str,
    unmapped_rows: list[dict[str, object]],
) -> gpd.GeoDataFrame:
    edge_rows = _manual_edge_rows(rows, adjacent_edges)
    edge_layer = _join_edges(edge_rows, adjacent_edges, layer_filename, unmapped_rows, use_signal_and_edge=True)
    if not edge_layer.empty:
        return edge_layer
    return _join_signal_points(rows.drop_duplicates("signal_id"), signal_points, layer_filename, unmapped_rows)


def build_qgis_review_layers(output_root: Path = OUTPUT_ROOT) -> dict[str, int]:
    root = output_root
    tables = root / TABLES_CURRENT
    review = root / REVIEW_CURRENT
    geojson = root / REVIEW_GEOJSON_CURRENT
    geojson.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)

    signal_graph_nodes = gpd.read_file(geojson / "signal_graph_nodes.geojson")
    adjacent_edges = gpd.read_file(geojson / "signal_adjacent_edges.geojson")
    signal_points = _first_signal_points(signal_graph_nodes)

    manual = _read_csv(review / "manual_graph_review_sample.csv")
    high = _read_csv(review / "high_adjacent_edge_count_signals.csv")
    low = _read_csv(review / "low_adjacent_edge_count_signals.csv")
    gap = _read_csv(tables / "graph_gap_review.csv")
    distribution = _read_csv(review / "signal_adjacent_edge_count_distribution.csv")

    for name, frame in [
        ("manual_graph_review_sample.csv", manual),
        ("high_adjacent_edge_count_signals.csv", high),
        ("low_adjacent_edge_count_signals.csv", low),
        ("graph_gap_review.csv", gap),
        ("signal_adjacent_edge_count_distribution.csv", distribution),
    ]:
        frame["source_table"] = name

    unmapped_rows: list[dict[str, object]] = []
    inventory: list[dict[str, object]] = []

    def write_layer(
        filename: str,
        frame: gpd.GeoDataFrame,
        source_table: str,
        intended_review_purpose: str,
        join_key: str,
        category_scope: str,
    ) -> None:
        _write_geojson(frame, geojson / filename)
        inventory.append(
            {
                "layer_filename": filename,
                "feature_count": len(frame),
                "source_table": source_table,
                "intended_review_purpose": intended_review_purpose,
                "join_key": join_key,
                "category_scope": category_scope,
            }
        )

    manual_signals = _join_signal_points(
        manual.drop_duplicates("signal_id"),
        signal_points,
        "manual_graph_review_sample_signals.geojson",
        unmapped_rows,
    )
    write_layer(
        "manual_graph_review_sample_signals.geojson",
        manual_signals,
        "manual_graph_review_sample.csv",
        "Signal points for all sampled graph QA review groups.",
        "signal_id",
        "sample-only",
    )

    manual_edges = _join_edges(
        _manual_edge_rows(manual, adjacent_edges),
        adjacent_edges,
        "manual_graph_review_sample_edges.geojson",
        unmapped_rows,
        use_signal_and_edge=True,
    )
    write_layer(
        "manual_graph_review_sample_edges.geojson",
        manual_edges,
        "manual_graph_review_sample.csv joined to signal_adjacent_edges.geojson",
        "Adjacent roadway graph edges for all sampled signals.",
        "signal_id; graph_edge_id",
        "sample-only",
    )

    zero_rows = low.loc[pd.to_numeric(low["adjacent_graph_edge_count"], errors="coerce").eq(0)].copy()
    zero_points = _join_signal_points(zero_rows, signal_points, "zero_edge_signal_review.geojson", unmapped_rows)
    write_layer(
        "zero_edge_signal_review.geojson",
        zero_points,
        "low_adjacent_edge_count_signals.csv",
        "Signals with zero adjacent graph edges.",
        "signal_id",
        "full-category",
    )

    one_rows = low.loc[pd.to_numeric(low["adjacent_graph_edge_count"], errors="coerce").eq(1)].copy()
    one_points = _join_signal_points(one_rows, signal_points, "one_edge_signal_review.geojson", unmapped_rows)
    write_layer(
        "one_edge_signal_review.geojson",
        one_points,
        "low_adjacent_edge_count_signals.csv",
        "Signals with exactly one adjacent graph edge.",
        "signal_id",
        "full-category",
    )

    high_points = _join_signal_points(high, signal_points, "high_edge_signal_review.geojson", unmapped_rows)
    write_layer(
        "high_edge_signal_review.geojson",
        high_points,
        "high_adjacent_edge_count_signals.csv",
        "Signals with more than eight adjacent graph edges; review for valid complexity vs overmatch.",
        "signal_id",
        "full-category",
    )

    gap_points = _join_signal_points(gap, signal_points, "graph_gap_review_signals.geojson", unmapped_rows)
    write_layer(
        "graph_gap_review_signals.geojson",
        gap_points,
        "graph_gap_review.csv",
        "Signal points from graph gap/count review.",
        "signal_id",
        "full-category",
    )

    gap_edge_rows = gap[["source_table", "signal_id", "issue_flags", "adjacent_edge_count", "matched_branch_count", "min_match_distance_ft", "matched_route_sample", "qa_status"]].merge(
        pd.DataFrame(adjacent_edges.drop(columns="geometry", errors="ignore")),
        on="signal_id",
        how="left",
        suffixes=("", "_edge"),
    )
    gap_edge_rows = gap_edge_rows.loc[gap_edge_rows["graph_edge_id"].astype(str).ne("")].copy()
    gap_edges = _join_edges(gap_edge_rows, adjacent_edges, "graph_gap_review_edges.geojson", unmapped_rows, use_signal_and_edge=True)
    write_layer(
        "graph_gap_review_edges.geojson",
        gap_edges,
        "graph_gap_review.csv joined to signal_adjacent_edges.geojson",
        "Relevant matched/adjacent graph edges for graph gap review signals where available.",
        "signal_id; graph_edge_id",
        "full-category where adjacent edges exist",
    )

    best_rows = manual.loc[manual["review_group"].eq("most_suitable_step5_candidates")].copy()
    best_edges = _candidate_review_layer(
        best_rows,
        adjacent_edges,
        signal_points,
        "step5_best_candidate_review.geojson",
        unmapped_rows,
    )
    write_layer(
        "step5_best_candidate_review.geojson",
        best_edges,
        "manual_graph_review_sample.csv",
        "Sample graph edges/signals that appear most suitable for future Step 5 oriented segment design.",
        "signal_id; graph_edge_id",
        "sample-only",
    )

    worst_rows = manual.loc[manual["review_group"].eq("least_suitable_step5_candidates")].copy()
    worst_edges = _candidate_review_layer(
        worst_rows,
        adjacent_edges,
        signal_points,
        "step5_worst_candidate_review.geojson",
        unmapped_rows,
    )
    write_layer(
        "step5_worst_candidate_review.geojson",
        worst_edges,
        "manual_graph_review_sample.csv",
        "Sample graph edges/signals that appear least suitable for future Step 5 oriented segment design.",
        "signal_id; graph_edge_id",
        "sample-only",
    )

    pd.DataFrame(inventory).to_csv(review / "qgis_graph_review_layer_inventory.csv", index=False)
    unmapped = pd.DataFrame(
        unmapped_rows,
        columns=["layer_filename", "source_table", "signal_id", "graph_edge_id", "reason"],
    ).drop_duplicates()
    unmapped.to_csv(review / "qgis_graph_review_unmapped_rows.csv", index=False)

    return {row["layer_filename"]: int(row["feature_count"]) for row in inventory}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build QGIS review GeoJSON layers from roadway graph QA outputs.")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)

    counts = build_qgis_review_layers(args.output_root)
    for filename, count in counts.items():
        print(f"{filename}: {count}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
