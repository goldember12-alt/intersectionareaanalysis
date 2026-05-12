# Roadway Graph Foundation Audit

## Bounded question

This audit answers whether the current roadway inputs can support a full signal/intersection roadway graph that keeps both divided and undivided roadways before crash assignment, true vehicle-direction inference, or analysis-ready gating.

No crash data was read for this audit.

## Outputs produced

Review tables were written to:

- `work/output/directed_segments/review/current/roadway_input_layer_inventory.csv`
- `work/output/directed_segments/review/current/travelway_centerline_field_inventory.csv`
- `work/output/directed_segments/review/current/current_leg_model_vs_graph_model_gap_summary.csv`
- `work/output/directed_segments/review/current/sample_signal_expected_leg_count_review.csv`

An internal JSON summary was also written for traceability:

- `work/output/directed_segments/review/current/roadway_graph_foundation_audit_summary.json`

## Travelway availability

The Travelway source exists in the repository raw input area:

- `Intersection Crash Analysis Layers/Travelway.gdb`
- layer: `Travelway`
- geometry type reported by pyogrio: `MultiLineString`
- feature count reported by pyogrio: `141,152`
- source CRS: `EPSG:3857`

The staged and normalized artifacts are also present:

| Artifact | Rows | Geometry | CRS | Notes |
| --- | ---: | --- | --- | --- |
| `artifacts/staging/roads.parquet` | 141,152 | 140,654 `MultiLineString`, 498 null geometry | EPSG:3857 | staged Travelway copy |
| `artifacts/normalized/roads.parquet` | 140,654 | 140,654 `MultiLineString` | EPSG:3968 | full normalized Travelway roads |
| `work/output/stage1b_study_slice/Study_Roads_Divided.parquet` | 16,495 | 16,495 `MultiLineString` | EPSG:3968 | divided-road filtered slice |

The normalized road artifact has no null, empty, invalid, or zero-length geometries in this audit. It is the best available current artifact for a graph foundation because it preserves the full Travelway road set in the working CRS.

## Centerline and graph suitability

Travelway appears to contain usable linear roadway geometry. The normalized artifact is all `MultiLineString`, and the geometry is valid and non-empty after normalization.

It should be treated as a route-event/travelway linear geometry source, not yet as a ready graph. It is suitable as the base input for both divided and undivided roadway graph construction, but it still needs graph preprocessing:

- convert or explode multipart geometry into graph-ready line parts
- preserve source route/event identity
- split at signal/intersection nodes and relevant topology junctions
- detect route-measure gaps and overlaps
- classify divided, undivided, ramp, endpoint, and support cases
- keep unresolved geometry and topology cases visible

The measure continuity audit found:

- route groups with measure fields: `72,603`
- multirow route groups: `20,033`
- route groups with measure gaps greater than `0.01`: `2,610`
- route groups with measure overlaps less than `-0.01`: `144`

Those counts do not invalidate Travelway as a graph base. They mean route-measure order alone is not enough for a true graph; geometry topology and explicit split/traversal logic are needed.

## Key Travelway fields

Fields available for road identity:

- `RTE_NM`
- `RTE_COMMON`
- `RTE_ID`
- `EVENT_SOUR`

Fields available for route measures or milepoint-like support:

- `FROM_MEASURE`
- `TO_MEASURE`
- `RTE_FROM_M`
- `RTE_TO_MSR`
- `RTE_MEASUR`

Fields available for divided/undivided status:

- `RIM_FACILI`
- `RIM_MEDIAN`
- `RIM_COUPLE`
- `MEDIAN_IND`
- `MEDIAN_OPP`

In the normalized Travelway artifact, `MEDIAN_IND` and `MEDIAN_OPP` are blank for all rows, so the useful current divided/undivided fields are `RIM_FACILI`, `RIM_MEDIAN`, and possibly `RIM_COUPLE`.

Observed `RIM_FACILI` counts:

| Value | Rows |
| --- | ---: |
| `3-Two-Way Undivided` | 118,291 |
| `4-Two-Way Divided` | 16,468 |
| `1-One-Way Undivided` | 5,843 |
| `2-One-Way Divided` | 27 |
| `5-Reversible Exclusively (e.g. 395R)` | 23 |
| `8-Trail` | 2 |

Observed `RIM_MEDIAN` counts:

| Value | Rows |
| --- | ---: |
| `1-No median or unprotected area less than 4 feet wide (1)` | 124,057 |
| `2-Curbed Barrier or mountable curbs with a minimum height of 4 inches (4,7)` | 8,999 |
| `4-Grass unprotected Median exists with a width of 4 feet or more (2)` | 6,287 |
| `6-Jersey Barrier or Guard Rail creates a positive barrier(8)` | 960 |
| `3-Painted unprotected Median exists with a width of 4 feet or more (5)` | 280 |
| blank | 55 |
| `5-Painted unprotected center turn lane exists` | 14 |
| `7-Rail or other transport path occupies the median` | 1 |
| `5-Roll Top` | 1 |

Fields available for roadway classification:

- `RTE_CATEGO`
- `RTE_TYPE_N`
- `RTE_RAMP_C`
- `RIM_ACCESS`
- `RIM_FACILI`

The largest route categories are `Secondary`, `Urban Streets`, `US Highway Primary`, `State Highway Primary`, ramps, frontage roads, and interstate rows. Those fields are useful graph context, but they should not replace geometry-based topology.

## Current directed signal-leg model

The current directed signal-leg workflow is still divided-road focused.

Evidence:

- `src/active/directed_segments/builder.py` loads `Study_Roads_Divided.parquet`.
- `Study_Roads_Divided.parquet` has `16,495` rows.
- `artifacts/normalized/roads.parquet` has `140,654` rows.
- The current divided-road filter corresponds to `RIM_FACILI` leading code `2` or `4`, excluding `RIM_MEDIAN` leading code `1`.
- Rows not meeting that current divided filter: `124,159`.
- `directed_signal_legs.csv` has `4,012` rows for `2,006` signal nodes.
- `true_vehicle_direction_inferred` is `False` for all `4,012` current leg rows.

Current leg-type counts:

| Leg type | Rows |
| --- | ---: |
| `signal_to_signal` | 2,816 |
| `signal_to_road_endpoint` | 1,090 |
| `signal_to_access` | 106 |

Current geometry status counts:

| Geometry status | Rows |
| --- | ---: |
| `roadway_substring` | 2,635 |
| `fallback_direct_anchor_line` | 1,377 |

## Why the current workflow produces about two legs per signal

The current builder is not a full intersection graph builder. It:

1. attaches each signal to one nearest divided-road row from `Study_Signals_NearestRoad.parquet`;
2. groups usable signals by `route_name`, `route_id`, and `roadway_carriageway_id`;
3. sorts signals in that group by estimated route measure;
4. creates one lower-side leg and one higher-side leg per signal where possible;
5. uses road endpoints or access anchors only when no adjacent signal exists on that side.

That design naturally produces about two records per signal. It is a linear route/carriageway adjacency model, not a node-edge graph of all roadway branches incident to an intersection.

A normal four-leg intersection can involve multiple nearby Travelway route groups. The current model only uses one nearest divided route group, so it can miss undivided crossing roads, ramps, frontage roads, minor approaches, and other logical legs that should be present in a graph foundation.

The sample review table `sample_signal_expected_leg_count_review.csv` illustrates this. It uses an approximate 75-foot full-Travelway search around selected signal points and compares nearby route-group counts with the current two-leg output. This is a review heuristic only, not a final graph algorithm.

## Desired graph model gap

The required pivot is larger than a small edit to the directed leg builder.

Current model:

- road base is divided-only
- one nearest divided road per signal
- sorted lower/higher route-measure neighbors
- two oriented leg records per signal in the common case
- access and road endpoints as fallback termini
- no crash reads
- no true vehicle-direction inference

Desired graph model:

- road base is full normalized Travelway, including divided and undivided roads
- signal/intersection nodes connect to all nearby/intersecting roadway branches
- roadway geometry is split or traversed into adjacent signal/intersection graph edges
- a normal four-leg intersection can produce legs for all roadway directions where geometry exists
- signal-to-signal is the primary graph edge type
- road endpoint and access remain fallback/support anchors
- divided roadways may later create two directional segment records
- undivided roadways produce one centerline/logical segment record until crash direction is used later
- no crash assignment or true vehicle-direction inference in the graph build

## Code changes needed

Recommended implementation changes for the next phase:

1. Add a new full-road graph workflow rather than mutating the current divided-road builder in place.
2. Load `artifacts/normalized/roads.parquet` or a new full-road study slice instead of `Study_Roads_Divided.parquet`.
3. Preserve both divided and undivided facility classes with explicit fields such as `roadway_division_status`, `facility_code`, `median_code`, and `logical_segment_mode`.
4. Build graph-ready road edges from Travelway geometry:
   - explode multipart geometry;
   - normalize line direction only as source geometry order, not vehicle direction;
   - retain `RTE_NM`, `RTE_ID`, `EVENT_SOUR`, measure fields, facility fields, and class fields;
   - detect geometry/measure gaps and overlaps.
5. Build signal/intersection nodes independently from one nearest road row:
   - find all Travelway branches within a documented tolerance;
   - snap/project each signal to candidate road branches;
   - preserve branch-candidate evidence and ambiguity.
6. Split or traverse road geometry between adjacent graph anchors:
   - signal to signal where possible;
   - signal to road endpoint as support;
   - signal to access only as fallback/support, not as the primary graph unit.
7. Emit graph-edge records before directional analysis:
   - one logical centerline segment for undivided roads;
   - divided carriageway records where the source geometry supports them;
   - optional later direction-specific records separated from graph-edge identity.
8. Keep unresolved, ambiguous, fallback, and support-only statuses explicit.
9. Do not read crash data or infer true vehicle travel direction in this graph build.

## Recommended next output contract

A next implementation should write a new output family, not overwrite the current directed-leg outputs. Suggested root:

- `work/output/roadway_graph/`

Suggested current tables:

- `tables/current/roadway_graph_edges.csv`
- `tables/current/roadway_graph_edge_bins_50ft.csv`
- `tables/current/signal_intersection_nodes.csv`
- `tables/current/signal_road_branch_candidates.csv`
- `tables/current/roadway_graph_endpoint_support.csv`
- `tables/current/roadway_graph_build_summary.csv`
- `review/current/roadway_graph_gap_overlap_review.csv`
- `review/current/signal_branch_ambiguity_review.csv`
- `review/current/graph_edge_qa_summary.csv`

Suggested current GeoJSON layers:

- `review/geojson/current/roadway_graph_edges.geojson`
- `review/geojson/current/roadway_graph_edge_bins_50ft.geojson`
- `review/geojson/current/signal_intersection_nodes.geojson`
- `review/geojson/current/signal_road_branch_candidates.geojson`
- `review/geojson/current/roadway_graph_endpoint_support.geojson`
- `review/geojson/current/graph_unresolved_review.geojson`

Minimum graph-edge fields:

- `graph_edge_id`
- `from_anchor_id`
- `to_anchor_id`
- `from_anchor_type`
- `to_anchor_type`
- `edge_anchor_pair_type`
- `source_route_name`
- `source_route_id`
- `source_event_id`
- `route_common`
- `facility_code`
- `facility_text`
- `median_code`
- `median_text`
- `roadway_division_status`
- `logical_segment_mode`
- `is_divided_source`
- `is_undivided_source`
- `measure_start`
- `measure_end`
- `length_ft`
- `geometry_status`
- `qa_status`
- `problem_flags`
- `true_vehicle_direction_inferred`

For this phase, `true_vehicle_direction_inferred` should remain `False`.

## Audit conclusion

Travelway exists and appears suitable as the base geometry source for a full roadway graph that includes both divided and undivided roads. It has route identity, measure support, facility/median fields, classification fields, and valid normalized multiline geometry.

The current directed signal-leg workflow does not satisfy the new graph requirement because it is intentionally built from the divided-road study slice and attaches each signal to one nearest divided route/carriageway. Its roughly two legs per signal are a consequence of the lower/higher measure-side design, not evidence that the intersection graph has only two legs.

The next step should be a new full-roadway graph foundation workflow and output family. Crash assignment, directional crash interpretation, and true vehicle-direction inference should remain out of scope until the graph edges have been built and reviewed.
