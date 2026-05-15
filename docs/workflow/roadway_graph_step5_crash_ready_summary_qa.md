# Step 5 Crash-Ready Subset Final Summary QA

**Status: CURRENT ACTIVE.** This is a current roadway_graph result/readout summary retained under workflow for this pass.

## Bounded Question

This no-crash QA confirms internal consistency of the official Step 5 crash-assignment-ready segment and bin subset.

It does not read crash data, assign crashes, infer true vehicle direction, or modify old signal-centered crash/access modules.

## Outputs

- `work/output/roadway_graph/review/current/step5_crash_ready_missing_true_signals.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_final_consistency_checks.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_bin_distribution_summary.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_segment_length_summary.csv`
- `work/output/roadway_graph/review/current/step5_crash_ready_directionality_summary.csv`

## Consistency Checks

| Check | Count |
| --- | ---: |
| Crash-ready segments | 4,305 |
| Crash-ready bins | 159,578 |
| Original TRUE input signals | 1,214 |
| TRUE reference signals represented | 1,210 |
| Missing TRUE reference signals | 4 |
| Non-TRUE reference signal rows | 0 |
| Rows with true vehicle direction inferred | 0 |
| Undivided physical-directional-carriageway violations | 0 |
| Undivided missing crash-direction requirement | 0 |
| Zero-length segments | 0 |
| Short segments under 50 ft | 0 |
| Duplicate `oriented_segment_id` rows | 0 |
| Duplicate `bin_id` rows | 0 |
| Bins without matching segment | 0 |
| Bins not mapping to exactly one segment | 0 |
| Segments without bins | 0 |
| Review/exclude rows entering subset | 0 |
| A-centered rows not allowed | 0 |

All hard internal consistency checks passed.

## Missing TRUE Signals

Four TRUE input signals are not represented as crash-ready reference signals:

| Signal | Reason |
| --- | --- |
| `signal_003449` | Its only reference row was a short undivided segment under 50 ft, so it stayed excluded. It still appears as an opposite anchor in two crash-ready rows. |
| `signal_003638` | It had no reference rows in the revised readiness table, but appears as an opposite anchor in four crash-ready rows. |
| `signal_003687` | All four reference rows were short segments under 50 ft, so they stayed excluded. |
| `signal_003781` | It had no reference rows in the revised readiness table, but appears as an opposite anchor in four crash-ready rows. |

This is acceptable for the first crash-assignment prototype because no short/review rows were forced into the subset and no non-TRUE reference signals were added. The two signals that appear only as opposite anchors should be reviewed later if full reference-signal coverage is required.

## Segment Profile

By roadway directionality:

| Type | Segments |
| --- | ---: |
| divided | 2,293 |
| undivided | 2,012 |

By opposite anchor type:

| Anchor type | Segments |
| --- | ---: |
| non-signalized roadway intersection | 2,029 |
| signalized intersection | 1,870 |
| road endpoint / dead end | 406 |

By orientation record type:

| Type | Segments |
| --- | ---: |
| undivided logical centerline | 2,012 |
| review-only reinterpreted for A-centered boundary use | 937 |
| endpoint oriented candidate | 908 |
| divided oriented candidate | 224 |
| reciprocal orientation candidate | 224 |

Length profile:

| Length band | Segments |
| --- | ---: |
| 50-250 ft | 441 |
| 250-500 ft | 611 |
| 500-1000 ft | 1,242 |
| 1000+ ft | 2,011 |

Minimum segment length is 50.165 ft. No crash-ready segment is shorter than 50 ft.

## Bin Profile

By roadway directionality:

| Type | Bins |
| --- | ---: |
| undivided | 95,134 |
| divided | 64,444 |

By orientation record type:

| Type | Bins |
| --- | ---: |
| undivided logical centerline | 95,134 |
| review-only reinterpreted for A-centered boundary use | 26,111 |
| endpoint oriented candidate | 28,261 |
| divided oriented candidate | 5,086 |
| reciprocal orientation candidate | 5,086 |

There are 155,273 full 50-foot bins and 4,305 final partial bins. No bin has zero or negative length.

## Directionality Boundary

No true vehicle direction has been inferred.

For undivided rows:

- `physical_directional_carriageway = false`
- `undivided_event_direction_requires_crash_direction = true`

For divided rows:

- the rows are A-centered geometry records only
- true vehicle direction still requires a later, explicit evidence source

## Recommendation

Proceed with the conservative crash-assignment prototype using only:

- `tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`

Do not broaden the reference signal universe or reintroduce short/review rows before crash assignment. The four missing TRUE reference signals are acceptable for the current prototype because they were excluded by documented structural gates rather than by silent data loss.
