# Roadway Graph Workflow

**Status: CURRENT ACTIVE.** This is the primary current operational contract for the graph-first roadway_graph workflow.

## Bounded Problem

Build a full-roadway graph foundation around signalized intersections using normalized Travelway roads.

This workflow retains both divided and undivided roadways. It creates signal graph nodes, signal-adjacent graph edges, 50-foot edge bins, QA review layers, and explicit pre-Step 5 eligibility gates.

The base graph build does not read crash data, assign crashes, infer true vehicle travel direction, or finalize upstream/downstream interpretation. Later roadway_graph modules add Step 5 crash-ready rows, conservative crash assignment, geometric direction support, divided carriageway pairing, and roadway role classification.

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
8. applies conservative signal and edge eligibility gating for future Step 5 inputs;
9. writes QA summaries and QGIS-ready review layers.

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
- `tables/current/signal_step5_eligibility.csv`
- `tables/current/roadway_graph_edges_eligible.csv`
- `tables/current/roadway_graph_edges_termination_refined.csv`
- `tables/current/signal_adjacent_edges_termination_refined.csv`
- `tables/current/signal_graph_edge_bins_50ft_termination_refined.csv`
- `tables/current/roadway_graph_edges_eligible_termination_refined.csv`
- `tables/current/signal_oriented_roadway_segments.csv`
- `tables/current/signal_oriented_segment_bins_50ft.csv`
- `tables/current/roadway_role_classification.csv`
- `tables/current/signal_oriented_roadway_segments_role_enriched.csv`

Current review tables:

- `review/current/graph_build_summary.csv`
- `review/current/signal_adjacent_edge_count_summary.csv`
- `review/current/sample_signal_graph_review.csv`
- `review/current/manual_graph_review_results.csv`
- `review/current/manual_review_diagnosis_summary.csv`
- `review/current/manual_review_signal_classification.csv`
- `review/current/source_roadway_incomplete_examples.csv`
- `review/current/edge_termination_issue_examples.csv`
- `review/current/step5_candidate_examples_from_manual_review.csv`
- `review/current/step5_eligibility_summary.csv`
- `review/current/step5_excluded_signals.csv`
- `review/current/step5_candidate_signals.csv`
- `review/current/edge_termination_refinement_summary.csv`
- `review/current/edge_termination_before_after_examples.csv`
- `review/current/remaining_edge_termination_issue_candidates.csv`
- `review/current/step5_eligibility_before_after_termination_refinement.csv`
- `review/current/step5_oriented_segment_summary.csv`
- `review/current/step5_oriented_segment_problem_rows.csv`
- `review/current/step5_oriented_segment_pairing_summary.csv`
- `review/current/step5_oriented_segment_signal_coverage.csv`
- `review/current/roadway_role_classification_summary.csv`
- `review/current/roadway_role_by_pairing_status_summary.csv`
- `review/current/unpaired_divided_by_roadway_role_summary.csv`
- `review/current/roadway_role_review_examples.csv`

Current GeoJSON review layers:

- `review/geojson/current/roadway_graph_nodes.geojson`
- `review/geojson/current/roadway_graph_edges.geojson`
- `review/geojson/current/signal_graph_nodes.geojson`
- `review/geojson/current/signal_adjacent_edges.geojson`
- `review/geojson/current/signal_graph_edge_bins_50ft.geojson`
- `review/geojson/current/graph_gap_review.geojson`
- `review/geojson/current/divided_edge_directional_candidates.geojson`
- `review/geojson/current/undivided_edge_candidates.geojson`
- `review/geojson/current/step5_candidate_signals.geojson`
- `review/geojson/current/step5_excluded_signals.geojson`
- `review/geojson/current/step5_candidate_edges.geojson`
- `review/geojson/current/edge_termination_refined_edges.geojson`
- `review/geojson/current/remaining_edge_termination_issue_candidates.geojson`
- `review/geojson/current/signal_oriented_roadway_segments.geojson`
- `review/geojson/current/signal_oriented_segment_bins_50ft.geojson`
- `review/geojson/current/roadway_role_review_examples.geojson`

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
- 3,933 signal Step 5 eligibility rows
- 17,374 roadway graph edge eligibility rows

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

## Manual Review Diagnosis

The first 30-row manual QGIS review is summarized in:

- `docs/workflow/roadway_graph_manual_review_diagnosis.md`

Main interpretation:

- many failed signals are source-roadway-incomplete cases where the Travelway/base roadway source is missing one or more important legs
- zero-edge and one-edge signals should be excluded from Step 5 by default unless manually promoted
- two-edge signals should be treated as suspect unless review confirms the intersection is truly two-legged or the bounded analysis only needs one roadway
- edge termini should stop at the first valid roadway-network anchor, including non-signalized intersections, before using access fallback or a maximum cutoff

The manual diagnosis remains pre-crash and pre-directional. It does not implement Step 5 oriented segments or change the existing signal-centered crash/access modules.

## Step 5 Eligibility Gating

The current graph run now writes explicit Step 5 input gates documented in:

- `docs/workflow/roadway_graph_step5_eligibility_gating.md`

Gate status values:

- `TRUE`: usable as a future Step 5 input candidate under the current graph evidence
- `CONDITIONAL`: visible candidate only after manual review or graph-rule improvement
- `FALSE`: excluded from Step 5 by default

Current signal gate counts:

| `usable_for_step5` | Signals |
| --- | ---: |
| `TRUE` | 1,185 |
| `CONDITIONAL` | 2,660 |
| `FALSE` | 88 |

The gate is intentionally conservative. Zero-edge and one-edge signals are excluded by default; two-edge and high-adjacent-edge-count signals are review-only; manually diagnosed `source_roadway_incomplete` signals are excluded. Future Step 5 work should consume only `TRUE` rows unless it explicitly documents how `CONDITIONAL` rows are being promoted or handled.

## Edge Termination Refinement

Candidate edge-termination refinement outputs are documented in:

- `docs/workflow/roadway_graph_edge_termination_refinement.md`

The refinement is review-only. It shortens signal-adjacent edges only when an existing graph-supported `road_intersection` node lies between the signal and the current endpoint. It does not use access points as primary termini and does not treat simple geometric crossings as true intersections.

Current readout:

- 830 signal-adjacent edges were shortened
- 50-foot bin rows decreased by 26,608
- 0 refined rows still appear to cross a supported intermediate intersection
- 235 newly suspicious short segments were created
- the four manually identified edge-termination issue signals were not fixed by this refinement

Recommendation: keep the refined termination outputs as review-only and revise the refinement logic before promoting them as default graph outputs.

## TRUE-Only Step 5 Oriented Segment Prototype

The first no-crash Step 5 oriented segment prototype is documented in:

- `docs/workflow/roadway_graph_step5_oriented_segment_prototype.md`

It uses only the 1,185 clean TRUE signals from `step5_first_prototype_input_signals.csv` and uses base graph geometry, not the review-only termination-refined geometry.

Current readout:

- 1,185 TRUE input signals represented
- 4,366 oriented segment rows
- 155,045 50-foot oriented segment bins
- 0 FALSE/CONDITIONAL signals entering the prototype
- 0 rows with true vehicle direction inferred
- 0 undivided rows marked as physical directional carriageways
- 233 divided segment families with paired reciprocal records
- 1,838 divided segment families missing reciprocal records
- 156 suspicious short segments under 50 feet

The prototype is ready for summary QA only. It is not ready for crash assignment.

## Step 5 Oriented Segment QA

The TRUE-only Step 5 oriented segment QA readout is documented in:

- `docs/workflow/roadway_graph_step5_oriented_segment_qa.md`

Current QA interpretation:

- the prototype is structurally sound for summary QA
- 2,395 segment rows are classified as ready for a future crash-assignment-ready subset
- 1,027 segment rows require review before crash assignment
- 944 segment rows should be excluded from crash assignment under current fields
- missing reciprocal divided families are mixed endpoint, TRUE-scope, grouping-key, and review-only cases rather than one single failure mode
- short segments under 50 feet should be gated out unless manually reviewed

Crash assignment should wait until a formal crash-assignment-ready subset is implemented and reviewed.

## Step 5 Readiness Revision

The revised no-crash readiness classification is documented in:

- `docs/workflow/roadway_graph_step5_readiness_revision.md`

Revision principle:

- the reference signal must be TRUE
- the opposite anchor does not need to be TRUE if it is a valid signal, roadway-intersection, or endpoint boundary
- non-TRUE signal endpoints may serve as boundaries, but not as analysis reference signals

Current revised readout:

- 4,204 segment rows are A-centered ready
- 154 segment rows are excluded
- 8 segment rows need review
- 0 rows use a FALSE/CONDITIONAL signal as the reference signal
- 0 rows infer true vehicle direction

The revision reinterprets 931 of the 936 opposite-signal-not-TRUE divided records as usable for A-centered analysis. It also reinterprets 878 of the 898 endpoint/one-sided divided records as usable for A-centered analysis. Short segments under 50 feet remain excluded unless explicitly justified.

## Step 5 Crash-Ready Subset

The official no-crash Step 5 crash-assignment-ready subset is documented in:

- `docs/workflow/roadway_graph_step5_crash_ready_subset.md`

Current subset outputs:

- `tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`
- `review/current/step5_crash_ready_subset_summary.csv`
- `review/current/step5_crash_ready_exclusion_summary.csv`
- `review/current/step5_crash_ready_signal_coverage.csv`
- `review/current/step5_crash_ready_anchor_type_summary.csv`
- `review/current/step5_crash_ready_a_centered_b_centered_summary.csv`
- `review/geojson/current/signal_oriented_roadway_segments_crash_ready.geojson`
- `review/geojson/current/signal_oriented_segment_bins_50ft_crash_ready.geojson`

Current readout:

- 4,204 crash-ready segment rows
- 154,330 crash-ready 50-foot bin rows
- 1,181 TRUE reference signals represented
- 0 non-TRUE reference signals
- 0 rows with true vehicle direction inferred
- 0 review/exclude rows entering the subset
- every crash-ready bin maps to exactly one crash-ready segment

This subset is the only approved Step 5 segment/bin input for a future crash-assignment prototype.

## Step 5 Crash-Ready Summary QA

The final no-crash summary QA for the crash-ready subset is documented in:

- `docs/workflow/roadway_graph_step5_crash_ready_summary_qa.md`

Current QA outputs:

- `review/current/step5_crash_ready_missing_true_signals.csv`
- `review/current/step5_crash_ready_final_consistency_checks.csv`
- `review/current/step5_crash_ready_bin_distribution_summary.csv`
- `review/current/step5_crash_ready_segment_length_summary.csv`
- `review/current/step5_crash_ready_directionality_summary.csv`

All hard consistency checks passed: no non-TRUE reference signals, no true vehicle direction inference, no zero/short crash-ready segments, no duplicate segment or bin ids, no orphan bins, and no review/exclude rows entering the subset. Four TRUE input signals are not represented as crash-ready reference signals because their rows were short/excluded or appeared only as opposite anchors.

## Crash Assignment Prototype

The conservative crash assignment prototype is documented in:

- `docs/workflow/roadway_graph_crash_assignment_prototype.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment
```

It uses only:

- `tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`

Current readout:

- 379,272 crash records considered
- 37,579 crashes assigned to the nearest crash-ready segment/bin within 75 ft
- 341,693 crashes unresolved
- 0 crashes assigned to non-crash-ready segments or bins
- 0 rows infer true vehicle direction
- all assigned rows keep event direction and upstream/downstream status unresolved

This is a spatial crash-assignment prototype ready for summary QA, not modeling.

## Geometric Direction Model

The roadway-geometry-derived direction model is documented in:

- `docs/workflow/roadway_graph_geometric_direction_model.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.geometric_direction
```

It reads only the Step 5 crash-ready segment/bin subset and roadway graph candidate tables. It does not read crash records, infer roadway direction from crashes, or promote the termination-refined outputs.

Current outputs:

- `tables/current/signal_oriented_roadway_segments_geometric_direction.csv`
- `tables/current/signal_oriented_segment_bins_geometric_direction.csv`
- `review/current/geometric_direction_summary.csv`
- `review/current/geometric_direction_divided_pairing_summary.csv`
- `review/current/geometric_direction_undivided_centerline_summary.csv`
- `review/current/geometric_direction_problem_rows.csv`
- `review/geojson/current/geometric_direction_divided_review.geojson`
- `review/geojson/current/geometric_direction_undivided_review.geojson`

Current readout:

- 4,204 segment rows and 154,330 bin rows annotated
- 2,257 divided rows remain unresolved because the current crash-ready geometry does not expose left/right bracketing carriageway pairs
- 1,947 undivided centerline rows are prepared for later side-of-centerline interpretation
- 0 rows infer true vehicle direction

This output is ready for summary QA and small mapped review. It is not yet a final divided-road crash-direction interpretation layer.

## Divided Carriageway Pairing Diagnostic

The no-crash divided carriageway pairing diagnostic is documented in:

- `docs/workflow/roadway_graph_divided_carriageway_pairing.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.divided_carriageway_pairing
```

It reads roadway graph and Step 5 geometry outputs only. It does not read crash records, use crash direction fields, infer direction from crash distributions, or modify old signal-centered crash/access modules.

Current outputs:

- `tables/current/divided_carriageway_pair_candidates.csv`
- `tables/current/signal_oriented_roadway_segments_divided_pairing_enriched.csv`
- `review/current/divided_carriageway_pairing_summary.csv`
- `review/current/divided_carriageway_pairing_problem_rows.csv`
- `review/current/divided_carriageway_unpaired_rows.csv`
- `review/current/divided_carriageway_pairing_examples.csv`
- `review/geojson/current/divided_carriageway_pairing_review.geojson`
- `review/geojson/current/divided_carriageway_unpaired_review.geojson`

Current readout:

- 2,257 divided rows reviewed
- 810 divided rows paired into 405 accepted right/left carriageway pairs
- 335 high-confidence pairs and 70 medium-confidence pairs
- 1,447 divided rows remain unpaired and unresolved
- 0 rows infer true vehicle direction

The paired divided rows are ready for small QGIS spot check. They should not be promoted into crash direction or upstream/downstream interpretation until that review confirms the pairing behavior.

## Roadway Role Classification

The no-crash roadway-role classification prototype is documented in:

- `docs/workflow/roadway_graph_roadway_role_classification.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.roadway_role_classification
```

It classifies the crash-ready Step 5 segment rows and their referenced graph edges into `mainline_divided_carriageway`, `undivided_centerline`, `ramp_or_connector`, `frontage_or_service_road`, `turn_lane_or_auxiliary`, `one_way_pair_candidate`, or `unknown_review`.

Current readout:

- 4,204 crash-ready segment rows classified
- 3,980 referenced graph edge rows classified
- 2,257 segment rows classified as `mainline_divided_carriageway`
- 1,849 segment rows classified as `undivided_centerline`
- 95 segment rows classified into ramp/frontage/auxiliary/one-way support roles
- 3 segment rows classified as `unknown_review`
- 810 paired divided rows remain `mainline_divided_carriageway`
- 1,447 unpaired divided rows remain `mainline_divided_carriageway`
- 0 accepted divided-pair fields overwritten
- 0 rows infer true vehicle direction
- crash data read: `False`

Recommended future pairing-recovery classes are `mainline_divided_carriageway` first, and `one_way_pair_candidate` only through a separate reviewed one-way couplet method.

## Current Approved Inputs For Crash Assignment

Only the official no-crash Step 5 crash-ready subset is approved as input to the current crash assignment prototype:

- `tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`

Direction/upstream-downstream interpretation is not final. Assigned crashes remain unresolved for event direction and upstream/downstream status until the roadway-geometry and divided-pairing interpretation path is validated.

## Next Recommended Implementation Step

The next technical task is divided-pairing recovery using roadway role classification.

Do this before broad graph repair, modeling, or policy-facing claims. The recovery pass should:

- start with unpaired `mainline_divided_carriageway` rows
- preserve accepted high/medium-confidence divided pairs
- use roadway role classification to avoid treating ramps, frontage roads, auxiliary lanes, and one-way candidates as the same recovery problem
- keep unresolved and review-only cases visible
- avoid crash direction as an upstream/downstream source
