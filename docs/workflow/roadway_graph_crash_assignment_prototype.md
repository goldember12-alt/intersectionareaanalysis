# Roadway Graph Crash Assignment Prototype

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This prototype spatially assigns normalized crash records to the approved Step 5 crash-ready oriented segment/bin subset.

It does not modify old signal-centered crash/access modules, use non-crash-ready Step 5 segments, infer true vehicle direction from roadway geometry, force upstream/downstream classification when crash direction evidence is missing or ambiguous, or use CONDITIONAL/FALSE reference signals.

## Inputs

- `artifacts/normalized/crashes.parquet`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`

Command:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment
```

Default search radius:

- 75 ft from crash point to nearest crash-ready 50-foot bin geometry

## Outputs

Tables:

- `work/output/roadway_graph/tables/current/crash_oriented_segment_bin_assignment.csv`
- `work/output/roadway_graph/tables/current/crash_oriented_segment_assignment_unresolved.csv`

Review:

- `work/output/roadway_graph/review/current/crash_assignment_summary.csv`
- `work/output/roadway_graph/review/current/crash_assignment_by_directionality_type.csv`
- `work/output/roadway_graph/review/current/crash_assignment_by_bin_summary.csv`
- `work/output/roadway_graph/review/current/crash_assignment_unresolved_summary.csv`
- `work/output/roadway_graph/review/current/crash_direction_field_inventory.csv`
- `work/output/roadway_graph/review/current/crash_assignment_problem_rows.csv`

GeoJSON:

- `work/output/roadway_graph/review/geojson/current/crash_assigned_to_oriented_segments.geojson`
- `work/output/roadway_graph/review/geojson/current/crash_assignment_unresolved.geojson`

## Method

The prototype uses nearest-neighbor spatial assignment from each crash point to the nearest crash-ready oriented segment bin within 75 ft.

Assignment is conservative:

- crashes outside the radius remain unresolved
- crashes with multiple equidistant nearest bins remain unresolved as ambiguous
- only crash-ready bins and their crash-ready parent segments are eligible
- direction fields are inventoried but not used as final travel-direction evidence
- event direction remains unresolved
- upstream/downstream status remains unresolved when event direction is unresolved

This preserves the distinction between:

- spatial segment/bin assignment
- crash direction interpretation
- upstream/downstream event interpretation

## Assignment Readout

| Metric | Count |
| --- | ---: |
| Total crash records considered | 379,272 |
| Assigned crashes | 37,579 |
| Unresolved crashes | 341,693 |
| Search radius | 75 ft |
| Assigned to non-crash-ready segments | 0 |
| Assigned to non-crash-ready bins | 0 |
| Rows with true vehicle direction inferred | 0 |
| Event direction unresolved rows | 37,579 |
| Upstream/downstream not unresolved where event direction unresolved | 0 |

Unresolved crashes:

| Reason | Crashes |
| --- | ---: |
| outside search radius | 341,469 |
| ambiguous multiple equidistant bins | 224 |

Assigned crashes by roadway directionality:

| Type | Crashes |
| --- | ---: |
| divided | 20,119 |
| undivided | 17,460 |

Assigned crashes by orientation record type:

| Type | Crashes |
| --- | ---: |
| undivided logical centerline | 17,460 |
| review-only reinterpreted for A-centered boundary use | 12,024 |
| endpoint oriented candidate | 6,507 |
| divided oriented candidate | 804 |
| reciprocal orientation candidate | 784 |

Assignment confidence:

| Confidence | Crashes |
| --- | ---: |
| high | 37,579 |

Distance bands:

| Distance to bin | Crashes |
| --- | ---: |
| 0-10 ft | 30,463 |
| 10-25 ft | 1,870 |
| 25-50 ft | 2,202 |
| 50-75 ft | 3,044 |

## Direction Inventory

The normalized crash table does not expose a validated true crash travel-direction field for this prototype.

Inventoried support/candidate fields include:

- `ROADWAY_DESCRIPTION`
- `RD_TYPE`
- `MAINLINE_YN`
- `RTE_NM`

These fields were not used to infer true vehicle direction. They remain support-only or candidate-name-only fields until separately validated.

## Interpretation Limits

For divided roads:

- crashes are assigned spatially to the nearest crash-ready oriented segment/bin
- direction match is `not_evaluated`
- event direction remains `unresolved`
- upstream/downstream status remains `unresolved`

For undivided roads:

- crashes are assigned spatially to the logical centerline/bin
- final upstream/downstream event interpretation requires crash direction or another explicit event-direction source
- missing or ambiguous direction keeps `event_direction_interpretation = unresolved`

This table is not a crash-rate table and is not modeling-ready.

## Recommendation

The crash-assignment prototype is ready for summary QA.

It is not ready for modeling. Before modeling or crash-rate summaries, the next bounded task should review assignment coverage and distance bands, then decide whether a validated crash-direction source exists for event-direction and upstream/downstream interpretation.
