# Roadway Graph Step 5 Oriented Segment Prototype

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This prototype creates a no-crash Step 5 oriented segment layer from clean TRUE roadway graph signals only.

It does not read crash data, assign crashes, infer true vehicle direction, modify old signal-centered crash/access modules, promote termination-refined outputs as default, or use CONDITIONAL/FALSE signals.

## Inputs

Primary signal input:

- `work/output/roadway_graph/review/current/step5_first_prototype_input_signals.csv`

Base graph inputs:

- `work/output/roadway_graph/tables/current/signal_step5_eligibility.csv`
- `work/output/roadway_graph/tables/current/roadway_graph_edges.csv`
- `work/output/roadway_graph/tables/current/signal_adjacent_edges.csv`
- `work/output/roadway_graph/tables/current/signal_graph_edge_bins_50ft.csv`
- `work/output/roadway_graph/tables/current/roadway_graph_edges_eligible.csv`
- `work/output/roadway_graph/tables/current/divided_edge_directional_candidates.csv`
- `work/output/roadway_graph/tables/current/undivided_edge_candidates.csv`

The prototype uses base `signal_adjacent_edges.csv` geometry. It does not use the review-only termination-refined geometry as the default source.

## Outputs

Tables:

- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_50ft.csv`

Review:

- `work/output/roadway_graph/review/current/step5_oriented_segment_summary.csv`
- `work/output/roadway_graph/review/current/step5_oriented_segment_problem_rows.csv`
- `work/output/roadway_graph/review/current/step5_oriented_segment_pairing_summary.csv`
- `work/output/roadway_graph/review/current/step5_oriented_segment_signal_coverage.csv`

GeoJSON:

- `work/output/roadway_graph/review/geojson/current/signal_oriented_roadway_segments.geojson`
- `work/output/roadway_graph/review/geojson/current/signal_oriented_segment_bins_50ft.geojson`

## Method

The prototype starts from the 1,214 clean TRUE signals in `step5_first_prototype_input_signals.csv`.

Undivided roads:

- create one logical centerline segment family
- do not create two physical directional carriageways
- mark `physical_directional_carriageway = false`
- mark `undivided_event_direction_requires_crash_direction = true`
- leave final upstream/downstream event interpretation for a later workflow that introduces crash direction

Divided roads:

- create paired oriented records only when the base graph supports reciprocal TRUE-signal records on the same graph edge
- mark those records as geometry orientation candidates only
- do not claim actual vehicle travel direction

Endpoint and ambiguous cases:

- rows terminating at non-signalized roadway intersections or road endpoints are labeled `endpoint_oriented_candidate`
- unknown roadway directionality and unpaired divided signal anchors are labeled `review_only`
- access points are not used as termini in this prototype

Every segment has:

- `true_vehicle_direction_inferred = false`
- `segment_orientation_only = true`

## QA Readout

| Metric | Count |
| --- | ---: |
| TRUE input signals | 1,214 |
| TRUE input signals represented | 1,214 |
| Oriented segment rows | 4,474 |
| 50-foot bin rows | 160,300 |
| FALSE/CONDITIONAL signals entering prototype | 0 |
| Zero-length segments | 0 |
| Suspicious short segments under 50 ft | 163 |
| Rows with true vehicle direction inferred | 0 |
| Undivided rows marked as physical directional carriageway | 0 |
| Undivided rows not marked as requiring crash direction | 0 |
| Endpoint or review-only segments | 1,878 |

Segments by roadway directionality type:

| Type | Segments |
| --- | ---: |
| divided | 2,340 |
| undivided | 2,130 |
| unknown | 4 |

Segments by orientation record type:

| Type | Segments |
| --- | ---: |
| undivided logical centerline | 2,130 |
| review only | 950 |
| endpoint oriented candidate | 928 |
| divided oriented candidate | 233 |
| reciprocal orientation candidate | 233 |

Pairing summary:

| Check | Count |
| --- | ---: |
| Divided segment families with paired reciprocal records | 233 |
| Divided segment families missing reciprocal records | 1,874 |
| Undivided segment families incorrectly duplicated | 0 |

Rows requiring manual review:

| Status | Segments |
| --- | ---: |
| `false` | 3,273 |
| `true` | 1,093 |

Problem-row flags:

| Flag | Rows |
| --- | ---: |
| `review_only` | 937 |
| `suspicious_short_under_50ft` | 149 |
| `suspicious_short_under_50ft;review_only` | 7 |

## Interpretation

This is an oriented geometry scaffold, not a vehicle-direction model.

For divided rows, the record orientation is a candidate orientation over a physical carriageway. It is not final vehicle direction. A later workflow must supply additional evidence before using these records for final downstream event classification.

For undivided rows, the segment represents a logical centerline. The prototype intentionally does not create two physical directional records for undivided roads. Later crash/event assignment on undivided roads requires crash direction or another explicit event-direction source.

The high number of divided families missing reciprocal records and the 944 review-only records are expected for a conservative TRUE-only first prototype. They should be summarized and reviewed before using the layer for crash assignment.

## Recommendation

This TRUE-only Step 5 prototype is ready for summary QA.

It is not ready for crash assignment. Before crash assignment, review:

- the 1,093 rows requiring manual review
- the 156 short segments under 50 feet
- the 1,874 divided families missing reciprocal records
- whether endpoint-oriented candidates are acceptable for the first downstream context summary
