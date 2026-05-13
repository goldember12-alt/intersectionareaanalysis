# Roadway Graph Step 5 Eligibility Audit

**Status: CURRENT ACTIVE.** This is a current roadway_graph result/readout summary retained under workflow for this pass.

## Bounded Question

This audit reviews the explicit Step 5 eligibility gate before any oriented segment implementation.

It does not read crash data, assign crashes, infer true vehicle direction, implement Step 5 oriented segments, modify old signal-centered crash/access modules, or fabricate missing Travelway geometry.

## Inputs Reviewed

- `work/output/roadway_graph/tables/current/signal_step5_eligibility.csv`
- `work/output/roadway_graph/tables/current/roadway_graph_edges_eligible.csv`
- `work/output/roadway_graph/review/current/step5_eligibility_summary.csv`
- `work/output/roadway_graph/review/current/step5_candidate_signals.csv`
- `work/output/roadway_graph/review/current/step5_excluded_signals.csv`
- `work/output/roadway_graph/review/current/manual_review_signal_classification.csv`
- `work/output/roadway_graph/tables/current/signal_adjacent_edges.csv`

## Audit Outputs

- `work/output/roadway_graph/review/current/step5_signal_gate_reason_summary.csv`
- `work/output/roadway_graph/review/current/step5_edge_gate_reason_summary.csv`
- `work/output/roadway_graph/review/current/true_step5_candidate_profile.csv`
- `work/output/roadway_graph/review/current/conditional_step5_candidate_profile.csv`
- `work/output/roadway_graph/review/current/false_step5_exclusion_profile.csv`
- `work/output/roadway_graph/review/current/step5_first_prototype_input_signals.csv`

## Gate Rules Observed

Signal gate counts:

| `usable_for_step5` | Signals | Interpretation |
| --- | ---: | --- |
| `TRUE` | 1,185 | Clean first-prototype candidates under current graph evidence. |
| `CONDITIONAL` | 2,660 | Visible but review-only or rule-dependent. |
| `FALSE` | 88 | Excluded from Step 5 by default. |

Rules causing `TRUE`:

- adjacent edge count is 3-4
- no graph-gap flag
- `source_roadway_complete_enough = TRUE`
- no Step 5 exclusion reason
- no manual source-roadway-incomplete, signal-location-questionable, or edge-termination diagnosis

Rules causing `CONDITIONAL`:

| Primary reason category | Signals |
| --- | ---: |
| high edge count | 2,280 |
| low edge count, from two-edge suspect cases | 347 |
| other graph review required | 29 |
| termination issue | 4 |
| unknown directionality type as primary reason | 0 |

Two conditional signals contain at least one source roadway edge with unknown roadway type, but both are conditional for other primary reasons.

Rules causing `FALSE`:

| Exclusion reason | Signals |
| --- | ---: |
| adjacent-leg count zero | 63 |
| source roadway incomplete | 24 |
| signal location questionable | 1 |

## TRUE Candidate Profile

Roadway mix among TRUE signals:

| Roadway mix | Signals |
| --- | ---: |
| undivided only | 500 |
| divided only | 475 |
| mixed divided/undivided | 208 |
| mixed with unknown roadway type | 2 |
| unknown only | 0 |

Adjacent edge count among TRUE signals:

| Adjacent edge band | Signals |
| --- | ---: |
| 3-4 | 1,185 |
| 5-8 | 0 |
| more than 8 | 0 |

TRUE signals with candidate manual edge-termination issues: 0.

The TRUE set is large enough for a first Step 5 prototype. It provides 1,185 source-sufficient, clean-gated signals before any conditional promotion.

## CONDITIONAL Candidate Profile

Conditional signals are not discarded, but they should not feed Step 5 by default.

Roadway mix among CONDITIONAL signals:

| Roadway mix | Signals |
| --- | ---: |
| mixed divided/undivided | 1,521 |
| undivided only | 592 |
| divided only | 545 |
| mixed with unknown roadway type | 2 |

Main interpretation:

- most conditional rows are high-edge-count review cases
- two-edge signals remain suspect because the manual review found many low-edge cases were source-incomplete
- four manual edge-termination cases remain conditional until first-valid-anchor termination logic is implemented
- unknown roadway type exists but is not currently the primary reason any signal is conditional

## FALSE Exclusion Profile

FALSE rows are retained for review but blocked from Step 5.

Roadway mix among FALSE signals:

| Roadway mix | Signals |
| --- | ---: |
| no adjacent edges | 73 |
| undivided only | 9 |
| divided only | 5 |
| mixed divided/undivided | 1 |

Manual diagnoses among FALSE signals:

| Manual diagnosis | Signals |
| --- | ---: |
| source roadway incomplete | 24 |
| signal location questionable | 1 |
| blank / not manually diagnosed | 63 |

No manually diagnosed `source_roadway_incomplete` rows are marked `TRUE` or `CONDITIONAL`.

## Edge Gate Readout

Edge gate counts:

| `usable_for_step5` | Edges |
| --- | ---: |
| `TRUE` | 4,132 |
| `CONDITIONAL` | 13,226 |
| `FALSE` | 16 |

Roadway directionality type on eligible edge rows:

| Type | Edges |
| --- | ---: |
| divided | 9,717 |
| undivided | 7,645 |
| unknown | 12 |

Current edge termination status:

| Status | Edges |
| --- | ---: |
| valid non-signalized intersection anchor | 10,517 |
| valid signal anchor | 3,783 |
| valid roadway endpoint anchor | 3,074 |

The current graph output does not yet derive first-valid-anchor crossing checks. Therefore all `intermediate_intersection_crossed_flag` values remain `UNKNOWN`. This is acceptable for the gate audit, but Step 5 should not treat it as proof that no intermediate intersection was crossed.

## Concentration Check

The TRUE set does not show an obvious route-sample concentration problem in this audit. The most common exact `route_common_sample` combination contains 17 of 1,185 TRUE signals, about 1.4 percent. Coordinate extents also span the broad working graph area rather than a single small cluster.

This is a coarse check only. A stronger geographic concentration audit would need a locality, district, or other roadway-area source. The current gate should not use crash `AREA_TYPE` for roadway geography.

## First Prototype Input

`step5_first_prototype_input_signals.csv` includes only clean `TRUE` signals.

No `CONDITIONAL` rows were included because there is not yet a documented promotion rule for them. That file should be the default signal input universe for the first Step 5 prototype.

Included fields:

- signal identifiers and source row keys
- observed adjacent, divided, undivided, and unknown edge counts
- audit adjacent-edge band
- roadway mix class
- gate fields
- route/name samples from adjacent graph edges
- geometry join field

## Recommendation

Proceed to a first Step 5 prototype using only `step5_first_prototype_input_signals.csv`.

Do not use `CONDITIONAL` signals until a later task implements and validates one of these promotion paths:

- high-edge-count review resolution
- two-edge valid-case confirmation
- first-valid-anchor termination logic
- manual promotion with documented reason
- better source roadway geometry or signal inventory correction
