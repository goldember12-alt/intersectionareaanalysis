# Roadway Graph Initial QA Readout

## Scope

This readout reviews the current full-roadway graph prototype under `work/output/roadway_graph/`.

It answers whether the current graph is clean enough to support the future no-crash Step 5 oriented segment layer. It does not implement that layer.

No crash data was read. No crashes were assigned. No true vehicle direction was inferred. No old signal-centered crash/access modules were modified.

## QA Outputs

The QA pass produced:

- `work/output/roadway_graph/review/current/signal_unique_count_summary.csv`
- `work/output/roadway_graph/review/current/signal_adjacent_edge_count_distribution.csv`
- `work/output/roadway_graph/review/current/signal_graph_node_multiplicity_summary.csv`
- `work/output/roadway_graph/review/current/graph_gap_reason_summary.csv`
- `work/output/roadway_graph/review/current/high_adjacent_edge_count_signals.csv`
- `work/output/roadway_graph/review/current/low_adjacent_edge_count_signals.csv`
- `work/output/roadway_graph/review/current/manual_graph_review_sample.csv`
- `work/output/roadway_graph/review/current/step5_oriented_segment_readiness_summary.csv`

## A. Signal Accounting

Current normalized signal input:

| Metric | Count | Read |
| --- | ---: | --- |
| `signals.parquet` rows | 3,933 | source signal point rows |
| generated `signal_000000` style IDs | 3,933 | stable only within this normalized artifact/order |
| unique signal IDs in `signal_graph_nodes.csv` | 3,933 | all signals represented, including unresolved rows |
| unique signal IDs in `signal_adjacent_edges.csv` | 3,860 | 73 signals have no adjacent edge rows |
| unique signal IDs represented by graph nodes with `node_type=signal` | 3,860 | signal graph nodes only exist where a road component association was made |

`signal_graph_nodes.csv` has 13,756 rows because its row unit is not one row per signal. Its row unit is one signal-to-road-component snapped graph association, plus unresolved signal rows. Multiple rows per signal are expected at divided roads, ramps, frontage roads, and complex intersections.

Durable source ID review:

| Candidate field | Unique nonblank values | Notes |
| --- | ---: | --- |
| `GLOBALID` | 3,153 | strong when present |
| `REG_SIGNAL_ID` | 3,151 | useful HMMS-style identifier when present |
| `ASSET_ID` | 2,959 | useful where populated |
| `ASSET_NUM` | 3,063 | useful where populated |
| `INTNO` / `SIGNAL_NO` / `INID` / `INTNUM` | about 165-186 | mostly locality-specific rows |

Recommendation: keep `signal_000000` as a run-local graph ID only. For a more durable signal ID, use a composite such as `Stage1_SourceGDB`, `Stage1_SourceLayer`, and `GLOBALID` where present; otherwise fall back to source plus `REG_SIGNAL_ID`, `ASSET_ID`, or `ASSET_NUM`. Retain `source_signal_row_id` as lineage, not as the long-term identifier.

## B. Adjacent Edge Counts

Per-signal adjacent edge fields were written to:

- `signal_adjacent_edge_count_distribution.csv`

That table includes, per signal:

- adjacent graph edge count
- divided adjacent edge count
- undivided adjacent edge count
- unknown adjacent edge count
- unique route-name count
- unique route-ID count
- binned bearing count
- total 50-foot bin count
- signal graph node association count
- snap-distance review counts

Adjacent edge count distribution:

| Adjacent edge band | Signal count |
| --- | ---: |
| `0` | 73 |
| `1` | 3 |
| `2` | 357 |
| `3-4` | 1,220 |
| `5-8` | 1,913 |
| `more_than_8` | 367 |

High edge counts are not failures by default. They often reflect complex intersections, divided roadways, ramps, frontage roads, nearby split geometries, or grade-separated roadway clusters. They are review targets because Step 5 needs to distinguish correct multi-leg connectivity from overmatching.

Low edge counts are higher-priority failures. The 73 zero-edge signals and 3 one-edge signals are not sufficient for a reliable intersection graph without review.

## C. Graph Gap Review

`graph_gap_review.csv` contains 741 rows. Reason flags can overlap, so the reason counts below are not mutually exclusive.

| Reason category | Flag | Signal count | Read |
| --- | --- | ---: | --- |
| high connectivity or overmatch review | `suspiciously_high_adjacent_edge_count` | 367 | may be legitimate complexity or overmatching |
| grade separation or nearby-road problem | `candidate_grade_separation_or_geometry_fragment_issue` | 252 | likely interchange/ramp/nearby-route clusters |
| no or zero connectivity | `zero_adjacent_edges` | 73 | likely no usable adjacent graph edge from prototype logic |
| snap-distance problem | `snapped_distance_exceeds_50ft` | 72 | signal-road association beyond review threshold |
| topology fragmentation or split problem | `candidate_nearest_roads_not_split_or_intersected_correctly` | 16 | branch candidates exist but edge count is low |
| low connectivity | `one_adjacent_edge` | 3 | under-connected intersection graph candidate |

The 741 rows are mostly high-connectivity and grade-separation/nearby-road review cases, not no-match failures. The true no/low-connectivity set is much smaller: 73 zero-edge signals plus 3 one-edge signals.

Review order should be:

1. zero-edge and one-edge signals
2. snap-distance over 50 ft
3. topology fragmentation / not-split cases
4. high-connectivity and grade-separation clusters

## D. Divided/Undivided Classification

Graph-edge classification summary:

| Roadway division status | Graph edge count |
| --- | ---: |
| `divided` | 9,717 |
| `undivided` | 7,645 |
| `unknown` | 12 |

Candidate review files:

- `divided_edge_directional_candidates.csv`: 9,717 rows
- `undivided_edge_candidates.csv`: 7,645 rows

Classification uses descriptive Travelway fields carried into `roadway_graph_edges.csv`:

- `facility_code`
- `facility_text`
- `median_code`
- `median_text`
- `roadway_division_status`
- `logical_segment_mode`
- `is_divided_source`
- `is_undivided_source`

Observed graph-edge facility split:

- divided edges are mostly `facility_code=4`, with a small `facility_code=2` set
- undivided edges are `facility_code=3` and `facility_code=1`
- unknown edges are `facility_code=5` or `facility_code=8`

This is complete enough for review and for Step 5 design, but it still needs manual validation before being treated as analysis-ready. Unknown edges must be retained and flagged rather than dropped.

## E. Step 5 Oriented Segment Readiness

Readiness summary:

| Question | Answer |
| --- | --- |
| Can adjacent signal-to-signal relationships be identified? | Partly yes. 3,783 graph edges have signal nodes at both endpoints. |
| Can signal-to-road-endpoint relationships be identified? | Yes for support edges. 13,591 graph edges connect a signal node to a road endpoint or road-intersection endpoint node. |
| Can undivided logical centerline segments be generated? | Mostly yes after grouping. There are 7,645 undivided graph edges. |
| Can divided roadway edges be paired into reciprocal orientation records yet? | Not reliably yet. There are 9,717 divided candidates, but pairing logic is not implemented. |
| Are unknown roads retained? | Yes. 12 graph edges are unknown. |
| Are formal upstream/downstream endpoint semantics available? | Not yet. |
| Is the graph ready for Step 5 implementation? | Ready for design and limited prototype after QGIS review, not production-oriented segment creation. |
| Is the graph ready for crash assignment? | No. |

Current fields are enough to start Step 5 design:

- `graph_edge_id`
- `from_graph_node_id`
- `to_graph_node_id`
- `signal_id`
- `signal_graph_node_id`
- `adjacent_node_id`
- `adjacent_node_type`
- `bearing_degrees`
- route/name/id fields
- divided/undivided classification
- geometry
- 50-foot bins

Missing or weak fields for formal Step 5 semantics:

- consolidated intersection node ID, separate from signal-road-component association IDs
- segment family ID connecting reciprocal/paired graph records
- explicit signal endpoint pair fields
- explicit `from_signal_id` and `to_signal_id` when both endpoints are signals
- formal `downstream_of_signal_id` / `upstream_of_signal_id` as segment-orientation semantics
- divided carriageway pairing logic
- duplicate/component-fragment grouping logic
- explicit review status for whether an edge is usable for later crash assignment

QA issues to resolve before Step 5:

- zero adjacent-edge signals
- one adjacent-edge signals
- signal-road snaps over 50 ft
- candidate topology fragmentation / not-split cases
- high-connectivity clusters where nearby roads may be over-associated
- divided carriageway pairing behavior
- unknown/reversible/trail classifications

### Proposed Future Step 5 Table Schema

Do not implement this yet. The recommended future table is:

- `signal_oriented_roadway_segments.csv`

Suggested fields:

- `oriented_segment_id`
- `base_graph_edge_id`
- `segment_family_id`
- `segment_type`: `signal_to_signal`, `signal_to_endpoint`, `signal_to_unknown`
- `roadway_directionality_type`: `divided`, `undivided`, `unknown`
- `orientation_record_type`: `logical_centerline`, `divided_carriageway_candidate`, `reciprocal_orientation_candidate`, `review_only`
- `from_signal_id`
- `to_signal_id`
- `from_anchor_type`
- `from_anchor_id`
- `to_anchor_type`
- `to_anchor_id`
- `downstream_of_signal_id`
- `upstream_of_signal_id`
- `true_vehicle_direction_inferred=False`
- `route_name`
- `route_common`
- `route_id`
- `event_source`
- `road_component_id`
- `source_road_row_id`
- `facility_code`
- `facility_text`
- `median_code`
- `median_text`
- `length_ft`
- `geometry`
- `qa_status`
- `requires_manual_review`
- `usable_for_later_crash_assignment`

Important semantic boundary: for divided roads, `Signal 1 -> Signal 2` and `Signal 2 -> Signal 1` should be segment-orientation records only. They are downstream/upstream relative to the segment endpoints, not true vehicle travel direction until crash direction is added later.

## F. Manual Review Sample

`manual_graph_review_sample.csv` contains 103 rows across these groups:

| Review group | Rows |
| --- | ---: |
| `zero_adjacent_edges` | 10 |
| `one_adjacent_edge` | 3 |
| `two_adjacent_edges` | 10 |
| `three_to_four_adjacent_edges` | 10 |
| `five_to_eight_adjacent_edges` | 10 |
| `more_than_eight_adjacent_edges` | 10 |
| `divided_road_examples` | 10 |
| `undivided_road_examples` | 10 |
| `graph_gap_review_examples` | 10 |
| `most_suitable_step5_candidates` | 10 |
| `least_suitable_step5_candidates` | 10 |

Only 3 one-edge signals exist in the current graph, so that group cannot reach 10 without duplication.

The sample includes QGIS-useful join and review fields:

- `review_group`
- `signal_id`
- `graph_node_id`
- `graph_edge_id`
- route/name/id fields
- divided/undivided/unknown classification
- adjacent edge counts
- match distance fields
- QA status and issue flags
- geometry join keys
- blank `manual_review_status`
- blank `issue_notes`

## G. Recommendation

The graph is ready for manual QGIS review.

The graph is not yet ready for production Step 5 oriented segment implementation. It is ready for Step 5 design and a limited no-crash prototype after the first QGIS review pass, especially after checking low-connectivity and high-connectivity cases.

The graph is not ready for crash assignment.

Review first:

1. zero adjacent-edge signals
2. one adjacent-edge signals
3. snap-distance over 50 ft cases
4. topology fragmentation / not-split cases
5. high adjacent-edge count and grade-separation clusters

High edge counts should be interpreted carefully. They are not failures by default. The review question is whether each high-count signal is correctly connected, under-connected, or over-connected.

