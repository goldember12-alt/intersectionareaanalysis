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
<bootstrap-reported-python> -m src.active.roadway_graph --limited-signal-offset-tolerance-ft 75
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
| `TRUE` | 1,214 |
| `CONDITIONAL` | 2,631 |
| `FALSE` | 88 |

The gate is intentionally conservative. Zero-edge and one-edge signals are excluded by default; two-edge and high-adjacent-edge-count signals are review-only; manually diagnosed `source_roadway_incomplete` signals are excluded. Future Step 5 work should consume only `TRUE` rows unless it explicitly documents how `CONDITIONAL` rows are being promoted or handled.

The current build includes a bounded signal-offset association relaxation. A signal with only the `snapped_distance_exceeds_50ft` graph-gap flag may remain TRUE only when it has a normal 3-4 adjacent-edge shape and the nearest roadway branch is within the limited offset tolerance. This promoted 29 low-risk offset cases in the current run. It does not snap endpoints, split crossings, repair linework, or promote high-edge-count/two-edge review cases.

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

It uses only the 1,214 clean TRUE signals from `step5_first_prototype_input_signals.csv` and uses base graph geometry, not the review-only termination-refined geometry.

Current readout:

- 1,214 TRUE input signals represented
- 4,474 oriented segment rows
- 160,300 50-foot oriented segment bins
- 0 FALSE/CONDITIONAL signals entering the prototype
- 0 rows with true vehicle direction inferred
- 0 undivided rows marked as physical directional carriageways
- 233 divided segment families with paired reciprocal records
- 1,874 divided segment families missing reciprocal records
- 163 suspicious short segments under 50 feet

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

- 4,305 segment rows are A-centered ready
- 163 segment rows are excluded
- 6 segment rows need review
- 0 rows use a FALSE/CONDITIONAL signal as the reference signal
- 0 rows infer true vehicle direction

The revision reinterprets 937 of the 942 opposite-signal-not-TRUE divided records as usable for A-centered analysis. It also reinterprets 908 of the 928 endpoint/one-sided divided records as usable for A-centered analysis. Short segments under 50 feet remain excluded unless explicitly justified.

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

- 4,305 crash-ready segment rows
- 159,578 crash-ready 50-foot bin rows
- 1,210 TRUE reference signals represented
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
- 38,403 crashes assigned to the nearest crash-ready segment/bin within 75 ft
- 340,869 crashes unresolved
- 0 crashes assigned to non-crash-ready segments or bins
- 0 rows infer true vehicle direction
- all assigned rows keep event direction and upstream/downstream status unresolved

This is a spatial crash-assignment prototype ready for summary QA, not modeling.

## Crash Assignment QA

The current crash-assignment QA module is documented in:

- `docs/workflow/roadway_graph_crash_assignment_prototype.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment_qa
```

Current review outputs are written under:

- `work/output/roadway_graph/review/current/crash_assignment_qa/`

Current QA readout:

- 38,403 assigned crashes and 340,869 unresolved crashes
- assignment rate: 10.125%
- assigned distance median: 0.000 ft
- assigned distance p95: 60.007 ft
- assigned distance max: 74.987 ft
- 3,131 assigned crashes over 50 ft
- 631 assigned crashes over 70 ft
- 35,016 assigned crashes on anchor-relaxation segments
- 960 assigned crashes on signal-association-tolerance segments
- 18,026 assigned crashes on geometry review caveat segments
- 3,003 unresolved crashes within 100 ft of crash-ready bins in the QA nearest-neighbor screen

The QA is read-only over current assignment/scaffold outputs. It does not change the graph, assignment logic, geometric direction outputs, or upstream/downstream status.

## Crash Assignment Interpretation-Readiness QA

The bounded interpretation-readiness QA module is documented in:

- `docs/workflow/roadway_graph_crash_assignment_prototype.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment_interpretation_readiness
```

Current review outputs are written under:

- `work/output/roadway_graph/review/current/crash_assignment_interpretation_readiness/`

Current readout:

- 38,403 assigned crashes reviewed
- 2,306 high-confidence spatial assignments
- 27,020 medium or caveated spatial assignments
- 9,077 low-confidence or review assignments
- 631 high-priority assigned-crash review rows
- 960 recovered signal-association assigned crashes
- 3,003 unresolved-near-scaffold rows reviewed

This module is classification-only. It does not change assignment results, alter scaffold construction, use crash direction fields, or infer upstream/downstream status.

## Crash Assignment Mapless Review Packets

The mapless review packet module is documented in:

- `docs/workflow/roadway_graph_crash_assignment_prototype.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment_mapless_review_packets
```

Current review outputs are written under:

- `work/output/roadway_graph/review/current/crash_assignment_mapless_review_packets/`

This module exists because GIS inspection is not currently available. It creates ranked tabular review packets for high-distance assignments, unknown endpoint caveats, signal-association cases, low-confidence divided recovery rows, and unresolved crashes near the crash-ready scaffold.

Current packet readout:

- 631 high-priority assigned crashes over 70 ft
- 1,746 assigned crashes from 50-70 ft
- 5,766 unknown endpoint review-required assignments
- 960 provisional signal-association assignments
- 385 low-confidence divided recovery assignments
- 433 unresolved rows within 75 ft of crash-ready bins
- 312 unresolved rows within 25 ft of crash-ready bins
- 312 unresolved-within-75-ft rows flagged as possible assignment logic gaps

The packet output is mapless review support only. It does not change assignment, alter the scaffold, use crash direction fields, or make any row ready for upstream/downstream interpretation.

## Crash Assignment Analysis Eligibility

The crash assignment analysis eligibility module is a read-only gatekeeping layer over the current crash assignment QA, interpretation-readiness, and mapless review packet outputs.

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment_analysis_eligibility
```

Current review outputs are written under:

- `work/output/roadway_graph/review/current/crash_assignment_analysis_eligibility/`

Expected outputs:

- `crash_assignment_analysis_eligibility_by_crash.csv`
- `crash_assignment_analysis_eligibility_summary.csv`
- `crash_assignment_analysis_eligibility_by_reference_signal.csv`
- `crash_assignment_analysis_eligibility_by_segment.csv`
- `spatial_descriptive_eligible_crashes.csv`
- `caveated_spatial_review_crashes.csv`
- `directional_excluded_crashes.csv`
- `manual_review_priority_cases.csv`
- `possible_assignment_logic_issue_cases.csv`
- `unresolved_near_scaffold_assignment_gap_cases.csv`
- `crash_assignment_analysis_eligibility_findings.md`
- `crash_assignment_analysis_eligibility_manifest.json`

This module converts existing classifications into conservative analysis flags. Spatial descriptive eligible rows may support non-directional descriptive crash occurrence summaries against the current crash-ready scaffold. Caveated rows, manual/GIS review priorities, high-distance rows, low-confidence divided recovery rows, provisional signal-association rows, possible assignment-logic issue rows, and unresolved near-scaffold gaps must remain traceable and excluded from directional interpretation.

Current readout:

- 38,836 output rows: 38,403 assigned spatial crash rows and 433 unresolved near-scaffold gap rows
- 29,326 assigned crashes are spatial descriptive eligible
- 9,077 assigned crashes remain caveated spatial review rows
- 38,836 rows are excluded from directional interpretation now
- 8,826 rows are manual or GIS review priorities
- 777 rows are possible assignment logic issue cases, including 465 assigned rows and 312 unresolved near-scaffold rows
- 433 rows are unresolved near-scaffold assignment gaps

Nothing in this output is ready for upstream/downstream interpretation. The module does not read raw crash data, use crash direction fields, infer direction from crash distributions, alter scaffold construction, change crash assignment logic, snap endpoints, split crossings, force divided pairs, overwrite accepted pairs, or require GIS inspection.

## Reference-Signal-Centered Directional Scaffold

The reference-signal-centered directional scaffold module is a read-only candidate/audit layer that returns to the core roadway/signal directionality plan without limiting far anchors to TRUE-signal-to-TRUE-signal pairs.

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.reference_signal_directional_scaffold
```

Current review outputs are written under:

- `work/output/roadway_graph/review/current/reference_signal_directional_scaffold/`

Expected outputs:

- `reference_signal_directional_scaffold_summary.csv`
- `reference_signal_node_inventory.csv`
- `reference_signal_anchor_inventory.csv`
- `reference_signal_directional_segment_candidates.csv`
- `reference_signal_directional_segment_pairs.csv`
- `reference_signal_directional_bins_50ft_candidates.csv`
- `undivided_centerline_pseudo_direction_records.csv`
- `divided_physical_direction_records.csv`
- `signal_to_nontrue_anchor_direction_records.csv`
- `signal_to_endpoint_direction_records.csv`
- `directional_blockers.csv`
- `directional_scaffold_qa_by_reference_signal.csv`
- `directional_scaffold_qa_by_anchor_type.csv`
- `reference_signal_directional_scaffold_findings.md`
- `reference_signal_directional_scaffold_manifest.json`

Current readout:

- 1,214 TRUE reference signals exist in `signal_step5_eligibility.csv`
- 1,210 TRUE reference signals are represented in the candidate scaffold
- 7,800 reference-signal-centered directional segment candidates
- 3,900 downstream-of-reference records
- 3,900 upstream-of-reference records
- 939 TRUE-signal far-anchor records
- 2,251 non-TRUE-signal far-anchor records
- 3,806 non-signal-intersection far-anchor records
- 804 endpoint or valid one-sided-boundary far-anchor records
- 810 divided physical carriageway records from accepted divided pairing
- 4,024 undivided centerline pseudo-direction records
- 304,552 50-foot directional bin records
- 2,972 blocked/review records, primarily unpaired divided physical direction candidates

The bin-ordering rule is reference-signal-centered: `bin_index_from_reference_signal = 1` is nearest TRUE reference signal A for both downstream records (`A -> B`) and upstream records (`B -> A`). Optional travel-order bin fields are present separately.

This is candidate/audit output only. It does not read crash data, read crash assignment outputs, use crash direction fields, infer direction from crash distributions, modify scaffold construction, or change crash assignment logic. Use only non-review, non-blocked directional records for any later directional crash-assignment prototype.

## Reference-Signal Directional Scaffold QA

The reference-signal directional scaffold QA module validates the candidate directional scaffold and writes a conservative prototype usable surface for a later crash-assignment-by-direction prototype.

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.reference_signal_directional_scaffold_qa
```

Current review outputs are written under:

- `work/output/roadway_graph/review/current/reference_signal_directional_scaffold_qa/`

Expected outputs:

- `directional_scaffold_qa_summary.csv`
- `directional_scaffold_prototype_usable_segments.csv`
- `directional_scaffold_prototype_usable_bins_50ft.csv`
- `directional_scaffold_excluded_segments.csv`
- `directional_scaffold_excluded_bins_50ft.csv`
- `directional_scaffold_pair_symmetry_qa.csv`
- `directional_scaffold_bin_ordering_qa.csv`
- `directional_scaffold_id_uniqueness_qa.csv`
- `directional_scaffold_qa_by_reference_signal.csv`
- `directional_scaffold_qa_by_anchor_type.csv`
- `directional_scaffold_qa_by_roadway_representation_type.csv`
- `directional_scaffold_blocker_summary.csv`
- `directional_scaffold_missing_true_signal_summary.csv`
- `directional_scaffold_qa_findings.md`
- `directional_scaffold_qa_manifest.json`

Current readout:

- 4,828 prototype usable directional segments
- 208,340 prototype usable 50-foot bins
- 2,972 excluded directional segments
- 96,212 excluded directional bins
- 976 TRUE reference signals represented in the prototype usable surface
- 2,414 usable downstream-of-reference records
- 2,414 usable upstream-of-reference records
- 810 usable divided physical carriageway records
- 4,018 usable undivided pseudo-direction records
- 4,285 usable records with a non-TRUE/non-signal/endpoint far anchor
- 0 segment ID uniqueness failures
- 0 bin ID uniqueness failures
- 0 prototype pair-symmetry failures
- 0 prototype bin-ordering failures
- 0 blocked/review/low-confidence-recovery/unknown-role rows leaked into the usable surface

Excluded rows remain visible. Main exclusion reasons are `review_flag_true`, `divided_physical_direction_not_accepted_or_unpaired`, `roadway_representation_not_prototype_usable`, `low_confidence_divided_recovery_review_only`, and `unknown_roadway_role`.

This QA is prototype-output only. It does not read crash data, read crash assignment outputs, use crash direction fields, infer direction from crashes, repair geometry, force divided pairs, promote review-only divided recovery rows, or change scaffold construction logic. The prototype usable surface is ready for a later crash-assignment-by-direction prototype only if that later module keeps excluded rows out and remains spatial/directional-assignment only.

## Reference-Signal Directional Bin Catchments

The reference-signal directional bin catchment module creates roadway-only directional catchment polygons from the conservative prototype usable directional bins. It prepares a later crash-point assignment surface without reading crashes or using crash direction fields.

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.reference_signal_directional_bin_catchments
```

Current review outputs are written under:

- `work/output/roadway_graph/review/current/reference_signal_directional_bin_catchments/`

Expected outputs:

- `directional_bin_catchment_summary.csv`
- `directional_bin_catchment_index.csv`
- `directional_bin_catchment_polygons.geojson`
- `directional_bin_catchment_crs_metadata.json`
- `catchment_crs_coordinate_sanity.csv`
- `divided_physical_catchment_bins.csv`
- `undivided_side_catchment_bins.csv`
- `catchment_blocked_or_unstable_bins.csv`
- `catchment_local_vector_qa.csv`
- `catchment_overlap_qa.csv`
- `catchment_qa_by_reference_signal.csv`
- `catchment_qa_by_roadway_representation_type.csv`
- `reference_signal_directional_bin_catchments_findings.md`
- `reference_signal_directional_bin_catchments_manifest.json`

Current readout:

- 208,340 input prototype usable directional bins
- 208,340 catchments created
- 200,061 usable catchments
- 7,281 unstable/review catchments
- 998 blocked catchments
- 104,268 downstream catchments
- 104,072 upstream catchments
- 14,604 divided physical catchments
- 193,736 undivided pseudo-direction catchments
- 0 unflagged overlap QA failures

Main instability reasons:

- `near_reference_or_far_anchor`: 8,036 catchments
- `local_vector_too_short`: 998 catchments
- `sharp_bearing_change_or_kink`: 125 catchments
- `unexpected_side_catchment_overlap`: 2 catchments

Divided physical records use a conservative two-sided buffer around the physical directional bin geometry. Undivided pseudo-direction records use single-sided polygons from the local bin vector: right side for A-to-B downstream and left side for B-to-A upstream, following the existing roadway-geometry convention. Bins remain indexed from the TRUE reference signal A.

CRS convention:

- catchment GeoJSON coordinates are projected repository working coordinates in `EPSG:3968` (`NAD83 / Virginia Lambert`), not longitude/latitude
- `directional_bin_catchment_crs_metadata.json` is the authoritative CRS sidecar for downstream consumers
- `catchment_crs_coordinate_sanity.csv` compares source bin WKT, pre-export catchments, and GeoJSON reload bounds against `EPSG:3968`
- the current GeoJSON reloads as `EPSG:3968`; downstream assignment modules should use the shared metadata convention rather than assignment-local CRS overrides

The output is roadway-only. It does not read crash data, read crash assignment outputs, use crash direction fields, use crash distributions, modify scaffold construction, recover excluded directional records, force divided pairs, or perform crash analysis. Use only `catchment_status = usable` polygons for any later crash-point assignment prototype; carry `unstable_review` and `blocked` catchments separately unless explicitly accepted after review.

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

- 4,305 segment rows and 159,578 bin rows annotated
- 2,293 divided rows remain unresolved because the current crash-ready geometry does not expose left/right bracketing carriageway pairs
- 2,012 undivided centerline rows are prepared for later side-of-centerline interpretation
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

- 2,293 divided rows reviewed
- 810 divided rows paired into 405 accepted right/left carriageway pairs
- 335 high-confidence pairs and 70 medium-confidence pairs
- 1,483 divided rows remain unpaired and unresolved
- 0 rows infer true vehicle direction

The paired divided rows are ready for small QGIS spot check. They should not be promoted into crash direction or upstream/downstream interpretation until that review confirms the pairing behavior.

## Divided Pairing Recovery Prototype

The no-crash divided-pairing recovery prototype is documented in:

- `docs/workflow/roadway_graph_divided_pairing_recovery.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.divided_pairing_recovery
```

It uses roadway role classification to test conservative recovery candidates only among `mainline_divided_carriageway` rows. It preserves accepted pairs, excludes ramp/frontage/auxiliary/unknown roles from generic recovery, and does not promote recovered candidates into the default geometric direction model.

Current readout:

- 810 existing accepted pair rows preserved
- 405 existing accepted pairs preserved
- 0 newly recovered high rows
- 0 newly recovered medium rows
- 44 low-confidence review-only rows
- 22 low-confidence review-only candidate pairs
- 1,439 divided rows still unresolved
- 0 generic recovery rows with ramp/frontage/auxiliary/unknown roles
- 0 rows infer true vehicle direction
- crash data read: `False`

The output is candidate-only. Do not promote it into the default geometric direction model.

## Roadway Role Classification

The no-crash roadway-role classification prototype is documented in:

- `docs/workflow/roadway_graph_roadway_role_classification.md`

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.roadway_role_classification
```

It classifies the crash-ready Step 5 segment rows and their referenced graph edges into `mainline_divided_carriageway`, `undivided_centerline`, `ramp_or_connector`, `frontage_or_service_road`, `turn_lane_or_auxiliary`, `one_way_pair_candidate`, or `unknown_review`.

Current readout:

- 4,305 crash-ready segment rows classified
- 4,081 referenced graph edge rows classified
- 2,293 segment rows classified as `mainline_divided_carriageway`
- 1,911 segment rows classified as `undivided_centerline`
- 98 segment rows classified into ramp/frontage/auxiliary/one-way support roles
- 3 segment rows classified as `unknown_review`
- 810 paired divided rows remain `mainline_divided_carriageway`
- 1,483 unpaired divided rows remain `mainline_divided_carriageway`
- 0 accepted divided-pair fields overwritten
- 0 rows infer true vehicle direction
- crash data read: `False`

Recommended future pairing-recovery classes are `mainline_divided_carriageway` first, and `one_way_pair_candidate` only through a separate reviewed one-way couplet method.

## Current Approved Inputs For Crash Assignment

Only the official no-crash Step 5 crash-ready subset is approved as input to the current crash assignment prototype:

- `tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`

Direction/upstream-downstream interpretation is not final. Assigned crashes remain unresolved for event direction and upstream/downstream status until the roadway-geometry and divided-pairing interpretation path is validated.

## Readiness-Gated Directional Crash Descriptive Summary

The read-only descriptive summary for roadway-derived directional crash assignments runs after the crash directional assignment analysis-readiness filter:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_directional_assignment_descriptive_summary
```

It reads only readiness outputs under `work/output/roadway_graph/review/current/crash_directional_assignment_analysis_readiness/` and writes current analysis summaries under `work/output/roadway_graph/analysis/current/crash_directional_assignment_descriptive_summary/`.

Current readout:

- core 0-500 ft: 5,767 assigned crashes; 2,884 downstream; 2,883 upstream
- standard 0-1,000 ft: 9,170 assigned crashes; 4,641 downstream; 4,529 upstream
- extended 0-2,500 ft: 13,216 assigned crashes; 6,673 downstream; 6,543 upstream
- ambiguous kept separate: 1,055
- unresolved kept separate: 360,583
- rows over 5,000 ft remain long-distance review: 2,513
- crash direction fields read or used: `False`
- scaffold, catchment, assignment, and readiness logic changed: `False`

Use `core_0_500ft` as the safest first descriptive subset, `standard_0_1000ft` as the next conservative summary, and `extended_0_2500ft` as sensitivity only. Rows over 2,500 ft should remain assignment-only or review-focused until functional relevance is reviewed.

## Next Recommended Implementation Step

The next technical task is QGIS review of the divided-pairing recovery prototype.

Do this before broad graph repair, modeling, or policy-facing claims. The review should:

- inspect low-confidence recovery candidates
- inspect still-unresolved mainline divided rows by route type and unresolved reason
- preserve accepted high/medium-confidence divided pairs
- keep roadway role classification as the guardrail against treating ramps, frontage roads, auxiliary lanes, and one-way candidates as the same recovery problem
- keep unresolved and review-only cases visible
- avoid crash direction as an upstream/downstream source
