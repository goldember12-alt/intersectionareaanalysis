# Roadway Graph Edge Termination Refinement

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This refinement tests whether signal-adjacent roadway graph edges can be shortened to the first valid roadway-network anchor when an existing graph-supported `road_intersection` node lies between the signal and the current endpoint.

It does not read crash data, assign crashes, infer true vehicle direction, implement Step 5 oriented segments, modify old signal-centered crash/access modules, or fabricate missing Travelway geometry.

The base graph tables remain unchanged. All outputs from this task are candidate refinement outputs.

## Method

The refinement uses:

- `roadway_graph_edges.csv`
- `roadway_graph_nodes.csv`
- `signal_adjacent_edges.csv`
- `signal_graph_edge_bins_50ft.csv`
- `signal_step5_eligibility.csv`
- `roadway_graph_edges_eligible.csv`
- `manual_review_signal_classification.csv`
- `edge_termination_issue_examples.csv`
- `step5_first_prototype_input_signals.csv`

For each signal-adjacent edge, the geometry is already ordered from the signal toward the current adjacent anchor. The refinement searches along that geometry for existing roadway graph nodes with `node_type = road_intersection`.

Rules:

- use only existing graph-supported `road_intersection` nodes
- do not treat simple geometric crossings as true intersections
- ignore candidate intersection nodes at the start or current endpoint
- truncate the signal-adjacent edge to the first supported intermediate `road_intersection` node
- preserve roadway division status as divided, undivided, likely divided, or unknown source context
- keep true vehicle direction uninferred
- do not use access points as primary termini

## Outputs

Candidate table outputs:

- `work/output/roadway_graph/tables/current/roadway_graph_edges_termination_refined.csv`
- `work/output/roadway_graph/tables/current/signal_adjacent_edges_termination_refined.csv`
- `work/output/roadway_graph/tables/current/signal_graph_edge_bins_50ft_termination_refined.csv`
- `work/output/roadway_graph/tables/current/roadway_graph_edges_eligible_termination_refined.csv`

Review outputs:

- `work/output/roadway_graph/review/current/edge_termination_refinement_summary.csv`
- `work/output/roadway_graph/review/current/edge_termination_before_after_examples.csv`
- `work/output/roadway_graph/review/current/remaining_edge_termination_issue_candidates.csv`
- `work/output/roadway_graph/review/current/step5_eligibility_before_after_termination_refinement.csv`
- `work/output/roadway_graph/review/geojson/current/edge_termination_refined_edges.geojson`
- `work/output/roadway_graph/review/geojson/current/remaining_edge_termination_issue_candidates.geojson`

## Validation Readout

| Metric | Count |
| --- | ---: |
| Base signal-adjacent edge rows | 21,119 |
| Refined signal-adjacent edge rows | 21,119 |
| Edges shortened to existing intermediate `road_intersection` nodes | 830 |
| Edges still appearing to cross a supported intermediate intersection | 0 |
| Base 50-foot bin rows | 682,475 |
| Refined 50-foot bin rows | 655,867 |
| Bin row delta | -26,608 |
| Zero-length rows after refinement | 0 |
| Rows shorter than 25 feet after refinement | 1,717 |
| Newly short rows created by refinement | 235 |

Termination anchor types after refinement:

| Anchor type | Edges |
| --- | ---: |
| Non-signalized roadway intersection | 10,980 |
| Signalized intersection | 7,133 |
| Road endpoint / dead end | 3,006 |
| Access fallback/support | 0 |
| Unresolved/cutoff | 0 |

Termination statuses after refinement:

| Status | Edges |
| --- | ---: |
| Terminated at non-signalized roadway intersection | 10,150 |
| Terminated at signalized intersection | 7,133 |
| Terminated at road endpoint / dead end | 3,006 |
| Refined to first non-signalized intersection | 830 |

## Step 5 Gate Impact

The refinement is review-only and does not promote or demote signal-level Step 5 eligibility.

| Status | Before | After | Delta |
| --- | ---: | ---: | ---: |
| TRUE | 1,214 | 1,214 | 0 |
| CONDITIONAL | 2,660 | 2,660 | 0 |
| FALSE | 88 | 88 | 0 |

The 1,214 first-prototype TRUE input signals retained their signal-level eligibility status.

Refined edge eligibility rows are one row per signal-adjacent refined edge, so their counts are not directly comparable to the base unique graph-edge eligibility table.

## Manual Termination Examples

The four manually identified edge-termination issue signals were checked:

| Signal | Manual issue rows | Refined by existing `road_intersection` node |
| --- | ---: | ---: |
| `signal_000134` | 4 | 0 |
| `signal_000161` | 4 | 0 |
| `signal_000426` | 4 | 0 |
| `signal_000643` | 4 | 0 |

This is an important negative result. The current refinement did not fix the known manual edge-termination examples. That suggests those cases may require better source line splitting, a stronger intersection-node build, or targeted manual review rather than simple truncation to already-present `road_intersection` nodes.

## Remaining Review Candidates

`remaining_edge_termination_issue_candidates.csv` contains 1,733 rows:

- 1,717 rows shorter than 25 feet after refinement
- 235 rows newly shortened below 25 feet by this refinement
- 16 rows from the manual edge-termination issue signals
- 0 rows still crossing a graph-supported intermediate intersection

The large number of short fragments is a warning. Many are likely pre-existing short graph pieces, but 235 were newly created by the refinement and should be reviewed before promotion.

## Recommendation

Keep the refined termination outputs as review-only.

Do not promote them as the new default graph outputs yet. The refinement is directionally useful because it shortens 830 edges and removes supported intermediate-intersection crossings under the current rule, but it does not resolve the manual termination examples and it creates 235 new suspicious short fragments.

Recommended next step:

- revise the refinement logic before promotion, focusing on source-supported intersection-node construction, short-fragment suppression, and targeted spot checks of the 830 shortened edges and four manual issue signals.

Step 5 should not be considered ready on the basis of this refinement alone.
