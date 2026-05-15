# Step 5 Crash-Assignment-Ready Subset

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This subset defines the official no-crash Step 5 segment and bin input for a future crash-assignment prototype.

It does not read crash data, assign crashes, infer true vehicle direction, expand the reference signal universe beyond TRUE signals, or modify old signal-centered crash/access modules.

## Source

The subset is built from:

- `work/output/roadway_graph/review/current/step5_oriented_segment_readiness_revised.csv`
- `work/output/roadway_graph/review/current/step5_ready_revised_candidates.csv`
- `work/output/roadway_graph/review/current/step5_still_review_or_exclude_reasons.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_50ft.csv`

Only rows with `ready_for_crash_assignment_revised = ready_for_crash_assignment_revised` are included.

## Outputs

Tables:

- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`

Review:

- `work/output/roadway_graph/review/current/step5_crash_ready_subset_summary.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_exclusion_summary.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_signal_coverage.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_anchor_type_summary.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_a_centered_b_centered_summary.csv`

GeoJSON:

- `work/output/roadway_graph/review/geojson/current/signal_oriented_roadway_segments_crash_ready.geojson`
- `work/output/roadway_graph/review/geojson/current/signal_oriented_segment_bins_50ft_crash_ready.geojson`

## Subset Rules

Included:

- only revised-ready segment rows
- only TRUE reference signals
- valid opposite anchors, including non-TRUE signals, non-signalized roadway intersections, and road endpoints
- only bins whose `oriented_segment_id` appears in the ready segment subset

Excluded:

- short segments under 50 feet
- review-only rows that remain review-only after the readiness revision
- unknown roadway directionality rows
- all review/exclude rows from the revised readiness table

## QA Readout

| Check | Count |
| --- | ---: |
| Crash-ready segment rows | 4,305 |
| Crash-ready 50-foot bin rows | 159,578 |
| TRUE reference signals represented | 1,210 |
| Reference signal not TRUE | 0 |
| Rows with true vehicle direction inferred | 0 |
| Review/exclude rows entering subset | 0 |
| A-centered use allowed rows | 4,305 |
| B-centered use allowed rows | 448 |

The subset covers 1,210 of the 1,214 TRUE reference signals. The remaining TRUE signals are not forced in because their segment rows remain short, review-only, or excluded under the readiness rules.

## Anchor And Orientation Profile

Opposite anchor type:

| Anchor | Segments |
| --- | ---: |
| Non-signalized roadway intersection | 2,029 |
| Signalized intersection | 1,870 |
| Road endpoint / dead end | 406 |

Roadway directionality:

| Type | Segments |
| --- | ---: |
| divided | 2,293 |
| undivided | 2,012 |

Orientation record type:

| Type | Segments |
| --- | ---: |
| undivided logical centerline | 2,012 |
| review-only reinterpreted for A-centered boundary use | 937 |
| endpoint oriented candidate | 908 |
| divided oriented candidate | 224 |
| reciprocal orientation candidate | 224 |

A-centered and B-centered interpretation:

| Field | Value | Segments |
| --- | --- | ---: |
| A-centered use allowed | true | 4,305 |
| B-centered use allowed | true | 448 |
| B-centered use allowed | false | 3,857 |
| Both endpoint signals TRUE | true | 595 |
| Both endpoint signals TRUE | false | 3,710 |

The subset is reference-signal-centered. A TRUE signal may use a segment ending at a non-TRUE signal, non-signalized intersection, or road endpoint. The opposite anchor does not need to be a TRUE analysis signal.

## Exclusions

| Reason | Rows |
| --- | ---: |
| Short undivided segment under 50 ft | 118 |
| Short divided/other segment under 50 ft | 43 |
| Unknown directionality | 4 |
| Review-only reciprocal-required row | 2 |
| Short review-only reciprocal-required row | 2 |

These 169 rows remain outside the crash-ready subset.

## Methodological Notes

No true vehicle direction has been inferred. `segment_orientation_only` remains the operative interpretation.

For divided roads, A-centered use means the segment is structurally usable for the TRUE reference signal. It is not a final true vehicle direction claim.

For undivided roads, the segment is a logical centerline. Final upstream/downstream crash interpretation still requires crash direction or another explicit event-direction source.

Non-TRUE signal endpoints are allowed only as opposite anchors. They are not promoted into the reference signal universe.

## Recommendation

This crash-ready subset is the current input to the conservative crash-assignment prototype.

Before crash assignment, perform a small verification pass on:

- a few non-TRUE opposite signal anchors
- a few non-signalized intersection anchors
- a few road endpoint anchors
- a few undivided logical centerline rows

Crash assignment should use only `signal_oriented_roadway_segments_crash_ready.csv` and `signal_oriented_segment_bins_50ft_crash_ready.csv` as Step 5 inputs.
