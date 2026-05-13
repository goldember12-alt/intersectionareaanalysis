# Step 5 Oriented Segment Readiness Revision

**Status: CURRENT ACTIVE.** This is a current roadway_graph result/readout summary retained under workflow for this pass.

## Bounded Question

This revision rechecks Step 5 oriented segment readiness by separating the TRUE reference signal from the opposite segment anchor.

It does not read crash data, assign crashes, infer true vehicle direction, expand the reference signal universe beyond TRUE signals, or modify old signal-centered crash/access modules.

## Why The Revision Was Needed

The prior QA treated divided segment families without reciprocal TRUE-signal records as not ready. That was too strict for A-centered analysis.

If Signal A is TRUE and Signal B is not TRUE, the A-B segment can still be usable for A-centered analysis when B is a valid boundary anchor. B does not need to be a TRUE analysis signal. The same applies when the opposite anchor is a non-signalized roadway intersection or road endpoint.

The revised readiness fields therefore distinguish:

- `reference_signal_eligibility`
- `opposite_anchor_validity`
- `reciprocal_pairing_status`
- `roadway_directionality_type`
- `segment geometry validity`
- `later crash assignment readiness`

## Outputs

- `work/output/roadway_graph/review/current/step5_readiness_revision_summary.csv`
- `work/output/roadway_graph/review/current/step5_oriented_segment_readiness_revised.csv`
- `work/output/roadway_graph/review/current/step5_missing_reciprocal_reinterpreted_summary.csv`
- `work/output/roadway_graph/review/current/step5_ready_revised_candidates.csv`
- `work/output/roadway_graph/review/current/step5_still_review_or_exclude_reasons.csv`

## Revised Readiness Counts

| Revised status | Segments |
| --- | ---: |
| ready_for_crash_assignment_revised | 4,204 |
| exclude_from_crash_assignment | 154 |
| review_before_crash_assignment | 8 |

Reference-signal safeguards:

| Check | Count |
| --- | ---: |
| Reference signal not TRUE | 0 |
| `true_vehicle_direction_inferred != false` | 0 |
| Opposite anchor valid as segment boundary | 4,366 |
| A-centered use allowed | 4,204 |
| B-centered use allowed | 466 |

This preserves the rule that no FALSE or CONDITIONAL signal is used as the reference signal. Non-TRUE signal endpoints may be used only as opposite boundary anchors.

## Missing Reciprocal Reinterpretation

The 1,838 divided records previously called missing reciprocal families split as follows:

| Missing reciprocal reason | Total | A-centered ready | Review/exclude |
| --- | ---: | ---: | ---: |
| Opposite signal not TRUE but valid boundary | 936 | 931 | 5 |
| Non-signal or endpoint boundary | 898 | 878 | 20 |
| Review-only unpaired divided record | 4 | 0 | 4 |

The 936 signal-boundary records are no longer treated as failures solely because the opposite signal is outside the TRUE reference universe. The 5 that remain excluded are short segments under 50 ft.

The 898 endpoint or one-sided graph edges are valid for A-centered analysis when geometry is not short. The 20 excluded rows are short segments under 50 ft.

The 4 review-only unpaired divided rows remain review/exclude.

## Remaining Review Or Exclude Reasons

| Reason | Segments |
| --- | ---: |
| Short undivided segment under 50 ft | 111 |
| Short divided/other segment under 50 ft | 38 |
| Short opposite-signal-boundary segment under 50 ft | 5 |
| Review-only or unknown directionality | 4 |
| Short review-only reciprocal-required row | 2 |
| Review-only reciprocal-required row | 2 |

Short segments under 50 ft remain excluded unless explicitly justified. Unknown directionality and unresolved review-only rows remain review/exclude.

## Interpretation

The readiness revision does not make a vehicle-direction claim. It only says the segment is structurally usable for the TRUE reference signal as a geometry boundary.

For divided roads, a missing reciprocal record no longer blocks A-centered use if:

- the reference signal is TRUE
- the opposite anchor is a valid signal, non-signalized roadway intersection, or endpoint
- the segment is not short or zero-length
- the row is not unknown/review-only for another reason

For undivided roads, ready rows still require crash direction later for final upstream/downstream event interpretation.

## Recommendation

Use `step5_ready_revised_candidates.csv` as the starting point for a future crash-assignment-ready segment subset.

Before crash assignment:

- keep short segments under 50 ft excluded unless manually justified
- keep unknown and unresolved review-only rows out
- preserve `true_vehicle_direction_inferred = false`
- keep the reference signal universe limited to TRUE signals
- document that non-TRUE opposite signals are valid boundaries, not analysis-reference signals

This revision makes the TRUE-only Step 5 prototype more structurally sound for A-centered analysis, but it still does not authorize crash assignment.
