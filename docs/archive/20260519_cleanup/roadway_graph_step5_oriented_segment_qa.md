# Roadway Graph Step 5 Oriented Segment QA

**Status: CURRENT ACTIVE.** This is a current roadway_graph result/readout summary retained under workflow for this pass.

## Bounded Question

This QA readout evaluates whether the TRUE-only Step 5 oriented segment prototype is structurally sound enough for summary QA, and what must be fixed before crash assignment.

It does not read crash data, assign crashes, infer true vehicle direction, modify old signal-centered crash/access modules, or expand to CONDITIONAL/FALSE signals.

## QA Outputs

- `work/output/roadway_graph/review/current/step5_oriented_segment_type_summary.csv`
- `work/output/roadway_graph/review/current/step5_divided_pairing_failure_summary.csv`
- `work/output/roadway_graph/review/current/step5_missing_reciprocal_divided_examples.csv`
- `work/output/roadway_graph/review/current/step5_short_segment_summary.csv`
- `work/output/roadway_graph/review/current/step5_short_segment_examples.csv`
- `work/output/roadway_graph/review/current/step5_signal_coverage_diagnostics.csv`
- `work/output/roadway_graph/review/current/step5_ready_for_crash_assignment_candidates.csv`
- `work/output/roadway_graph/review/current/step5_not_ready_for_crash_assignment_reasons.csv`
- `work/output/roadway_graph/review/geojson/current/step5_missing_reciprocal_divided_examples.geojson`
- `work/output/roadway_graph/review/geojson/current/step5_short_segment_examples.geojson`

## Overall Structure

| Check | Count |
| --- | ---: |
| TRUE input signals represented | 1,214 |
| FALSE/CONDITIONAL signal rows present | 0 |
| Oriented segment rows | 4,474 |
| 50-foot bin rows | 160,300 |
| Requires manual review | 1,103 |
| Does not require manual review | 3,371 |
| Usable for later crash assignment field = true | 3,371 |
| Usable for later crash assignment field = false | 1,103 |
| Endpoint or review-only rows | 1,878 |

By roadway directionality:

| Type | Segments |
| --- | ---: |
| divided | 2,340 |
| undivided | 2,130 |
| unknown | 4 |

By orientation record type:

| Type | Segments |
| --- | ---: |
| undivided logical centerline | 2,130 |
| review only | 950 |
| endpoint oriented candidate | 928 |
| divided oriented candidate | 233 |
| reciprocal orientation candidate | 233 |

The prototype is structurally sound as a TRUE-only geometry scaffold: all TRUE input signals are represented, no non-TRUE signals entered, no vehicle direction was inferred, and undivided rows were not treated as physical directional carriageways.

## Divided Pairing Diagnostics

The prototype has 233 divided segment families with paired reciprocal records and 1,874 divided families missing reciprocal records.

Those 1,874 missing reciprocal rows should not be interpreted as one single failure mode:

| Interpretation | Segments |
| --- | ---: |
| Reciprocal signal not in TRUE input or not grouped under same family | 942 |
| Endpoint or one-sided graph edge | 928 |
| Review-only unpaired divided record | 4 |

By orientation record type:

| Type | Segments |
| --- | ---: |
| review only | 940 |
| endpoint oriented candidate | 898 |

By endpoint type:

| Endpoint | Segments |
| --- | ---: |
| signalized intersection | 940 |
| non-signalized roadway intersection | 821 |
| road endpoint / dead end | 77 |

By readiness fields:

| Field | Value | Segments |
| --- | --- | ---: |
| requires manual review | true | 960 |
| requires manual review | false | 878 |
| usable for later crash assignment | false | 960 |
| usable for later crash assignment | true | 878 |

By length band:

| Band | Segments |
| --- | ---: |
| 1000+ ft | 786 |
| 500-1000 ft | 625 |
| 250-500 ft | 245 |
| 50-250 ft | 155 |
| 0-50 ft | 27 |

The top route-common samples are broad statewide arterial names rather than a single route concentration: US-460E has 38, US-1N has 36, US-250E has 34, US-60E has 33, and US-60W/US-460W have 30 each.

Likely meanings:

- Some are true one-sided or endpoint segments where no reciprocal divided carriageway should be expected.
- Some are paired physically in the source graph but the opposite side is not represented by a TRUE signal in this first prototype.
- Some may be caused by the current `segment_family_id` definition using base graph edge identity rather than a broader corridor/carriageway pairing key.
- Some may reflect overly broad divided classification or route/source representation issues.

These missing reciprocal divided families do not invalidate the prototype, but they must be gated before crash assignment.

## Short Segment Diagnostics

There are 156 suspicious short segments under 50 feet.

| Interpretation | Segments |
| --- | ---: |
| short graph piece needing review | 95 |
| short intersection connector or split artifact | 48 |
| short review-only piece | 7 |
| short endpoint stub | 6 |

By roadway directionality:

| Type | Segments |
| --- | ---: |
| undivided | 111 |
| divided | 45 |

By endpoint type:

| Endpoint | Segments |
| --- | ---: |
| road endpoint / dead end | 75 |
| non-signalized roadway intersection | 48 |
| signalized intersection | 33 |

All 156 short segments have `requires_manual_review = true` and `usable_for_later_crash_assignment = false`. They are not concentrated on one route; the largest route-common samples have five rows each.

Recommendation for short segments: gate them out of crash assignment by default and retain them for targeted review. Some may be valid small connector pieces, but they should not enter crash assignment without review.

## Crash-Assignment Readiness

A readiness classification was added in the QA outputs, using existing Step 5 fields only:

| Readiness | Segments |
| --- | ---: |
| ready_for_crash_assignment | 2,395 |
| review_before_crash_assignment | 1,027 |
| exclude_from_crash_assignment | 944 |

Main not-ready reasons:

| Reason | Segments |
| --- | ---: |
| review-only/unknown directionality plus missing divided reciprocal | 933 |
| divided family missing reciprocal record | 878 |
| short undivided segment requiring review | 111 |
| short divided segment with missing reciprocal record | 20 |
| short segment requiring review | 18 |
| short review-only divided segment with missing reciprocal record | 7 |
| review-only/unknown directionality | 4 |

The ready subset is a geometry-readiness subset only. For undivided rows, final upstream/downstream event classification still requires crash direction or another explicit event-direction source.

## Recommendations

The TRUE-only Step 5 prototype is structurally sound for summary QA.

Before crash assignment:

1. Implement a formal `crash-assignment-ready` segment subset using `step5_ready_for_crash_assignment_candidates.csv` as the starting point.
2. Gate out short segments under 50 feet unless manually reviewed.
3. Keep `review_only` and unknown-directionality rows excluded from crash assignment.
4. Treat divided families missing reciprocal records as review-before-crash-assignment, not automatic failures.
5. Add a better divided pairing key before trying to repair all 1,874 missing reciprocal families; many appear to be endpoint/one-sided graph cases or TRUE-signal-scope artifacts, not necessarily missing opposite carriageways.
6. Do a small QGIS spot check only, focused on:
   - 10 missing reciprocal divided examples from `step5_missing_reciprocal_divided_examples.geojson`
   - 10 short segment examples from `step5_short_segment_examples.geojson`
   - a few ready divided paired families to confirm the pairing interpretation

Do not proceed to crash assignment until the crash-assignment-ready subset is explicitly defined and reviewed.
