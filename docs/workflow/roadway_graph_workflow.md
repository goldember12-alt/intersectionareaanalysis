# Roadway Graph Workflow

## Bounded Problem

Build a full-roadway graph foundation around signalized intersections using normalized Travelway roads.

This workflow retains both divided and undivided roadways. It creates signal graph nodes, signal-adjacent graph edges, 50-foot edge bins, and QA review layers.

It does not read crash data, assign crashes, infer true vehicle travel direction, or implement analysis-ready gating.

## Command

Use the bootstrap-reported interpreter:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph
```

Optional arguments:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph --normalized-root artifacts/normalized
<bootstrap-reported-python> -m src.active.roadway_graph --output-root work/output/roadway_graph
<bootstrap-reported-python> -m src.active.roadway_graph --signal-road-tolerance-ft 75
```

## Inputs

Required:

- `artifacts/normalized/roads.parquet`
- `artifacts/normalized/signals.parquet`

Not used:

- crash data
- access points
- current `directed_segments` outputs

The first prototype intentionally keeps access fallback out of the primary graph. Access can be added later as a support-only/fallback layer after graph QA.

## Method Summary

The workflow:

1. loads the full normalized Travelway roads;
2. explodes `MultiLineString` roads into graph components;
3. classifies each component descriptively as divided, undivided, likely divided, or unknown using Travelway facility/median fields;
4. associates each signal to all nearby road components within the configured tolerance;
5. creates snapped signal graph nodes on those road components;
6. creates adjacent graph edges from each signal graph node to the nearest same-component signal node or source road endpoint in each supported geometric direction;
7. creates 50-foot bins along each signal-adjacent graph edge;
8. writes QA summaries and QGIS-ready review layers.

Line order is not vehicle direction. `true_vehicle_direction_inferred` remains `False`.

## Output Contract

Root:

- `work/output/roadway_graph/`

Current tables:

- `tables/current/roadway_graph_nodes.csv`
- `tables/current/roadway_graph_edges.csv`
- `tables/current/signal_graph_nodes.csv`
- `tables/current/signal_adjacent_edges.csv`
- `tables/current/signal_graph_edge_bins_50ft.csv`
- `tables/current/graph_gap_review.csv`
- `tables/current/divided_edge_directional_candidates.csv`
- `tables/current/undivided_edge_candidates.csv`

Current review tables:

- `review/current/graph_build_summary.csv`
- `review/current/signal_adjacent_edge_count_summary.csv`
- `review/current/sample_signal_graph_review.csv`

Current GeoJSON review layers:

- `review/geojson/current/roadway_graph_nodes.geojson`
- `review/geojson/current/roadway_graph_edges.geojson`
- `review/geojson/current/signal_graph_nodes.geojson`
- `review/geojson/current/signal_adjacent_edges.geojson`
- `review/geojson/current/signal_graph_edge_bins_50ft.geojson`
- `review/geojson/current/graph_gap_review.geojson`
- `review/geojson/current/divided_edge_directional_candidates.geojson`
- `review/geojson/current/undivided_edge_candidates.geojson`

Run metadata:

- `runs/current/run_summary.json`

## Current Prototype Readout

The current run used:

- 140,654 normalized Travelway road rows
- 145,151 exploded road components
- 3,933 normalized signal points

It produced:

- 25,736 roadway graph nodes
- 17,374 roadway graph edges
- 13,756 signal graph node rows
- 21,119 signal-adjacent edge rows
- 682,475 50-foot bin rows
- 741 graph gap review rows
- 9,717 divided edge directional candidate rows
- 7,645 undivided edge candidate rows

Signal adjacent-edge count summary:

| Adjacent edge count band | Signals |
| --- | ---: |
| `0` | 73 |
| `1` | 3 |
| `2` | 357 |
| `3-4` | 1,220 |
| `more_than_4` | 2,280 |

The high number of more-than-four cases is expected in a broad first graph prototype because the matching step keeps every nearby Travelway branch within tolerance. Those rows are review evidence, not final analysis-ready graph acceptance.

## Relationship To Directed Segments

The prior `work/output/directed_segments/` family remains untouched. It is now superseded for graph foundation purposes because it uses only `Study_Roads_Divided.parquet` and attaches each signal to a nearest divided route/carriageway.

The new `roadway_graph` family is the active prototype for a full-roadway graph foundation. The older directed segment outputs remain useful historical/prototype evidence for the divided-road vertical slice.

## Review Priorities

Review first:

- `graph_gap_review.geojson`
- signals with zero adjacent edges
- signals with one adjacent edge
- signals with more than four adjacent edges
- divided/undivided candidate layers side by side
- interchange/ramp/frontage-road clusters
- signals where snapped distance exceeds 50 feet

Do not use these outputs for crash assignment until graph QA is complete and an explicit crash-assignment phase is implemented.

