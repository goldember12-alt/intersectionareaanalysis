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
| Assigned crashes | 38,403 |
| Unresolved crashes | 340,869 |
| Search radius | 75 ft |
| Assigned to non-crash-ready segments | 0 |
| Assigned to non-crash-ready bins | 0 |
| Rows with true vehicle direction inferred | 0 |
| Event direction unresolved rows | 38,403 |
| Upstream/downstream not unresolved where event direction unresolved | 0 |

Unresolved crashes:

| Reason | Crashes |
| --- | ---: |
| outside search radius | 340,645 |
| ambiguous multiple equidistant bins | 224 |

Assigned crashes by roadway directionality:

| Type | Crashes |
| --- | ---: |
| divided | 20,501 |
| undivided | 17,902 |

Assigned crashes by orientation record type:

| Type | Crashes |
| --- | ---: |
| undivided logical centerline | 17,902 |
| review-only reinterpreted for A-centered boundary use | 12,101 |
| endpoint oriented candidate | 6,812 |
| divided oriented candidate | 804 |
| reciprocal orientation candidate | 784 |

Assignment confidence:

| Confidence | Crashes |
| --- | ---: |
| high | 38,403 |

Distance bands:

| Distance to bin | Crashes |
| --- | ---: |
| 0-10 ft | 31,138 |
| 10-25 ft | 1,903 |
| 25-50 ft | 2,231 |
| 50-75 ft | 3,131 |

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

## Crash Assignment QA

Bounded QA module:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment_qa
```

The QA module reads the completed assignment/scaffold outputs and writes review-only files under:

- `work/output/roadway_graph/review/current/crash_assignment_qa/`

It does not read the raw normalized crash file, change crash assignment logic, alter the roadway scaffold, repair geometry, infer direction, or classify upstream/downstream status.

Current QA readout:

| Metric | Value |
| --- | ---: |
| Total crashes considered | 379,272 |
| Assigned crashes | 38,403 |
| Unresolved crashes | 340,869 |
| Assignment rate | 10.125% |
| Median assigned distance to bin | 0.000 ft |
| 95th percentile assigned distance to bin | 60.007 ft |
| Maximum assigned distance to bin | 74.987 ft |
| Assigned crashes over 50 ft | 3,131 |
| Assigned crashes over 70 ft | 631 |
| Assigned crashes on anchor-relaxation segments | 35,016 |
| Assigned crashes on signal-association-tolerance segments | 960 |
| Assigned crashes on geometry review caveat segments | 18,026 |
| Unresolved crashes within 100 ft of crash-ready bins | 3,003 |

The 29 signal-offset recovered TRUE reference cases have 960 assigned crashes. They remain plausible as spatial assignments, but some recovered-signal rows have high p95 distances or geometry review caveats and should be spot checked before any directional interpretation.

The QA recommendation is unchanged: the assignment is ready for spatial QA and descriptive coverage review, not for directional or upstream/downstream interpretation.

## Interpretation-Readiness QA

Bounded interpretation-readiness module:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment_interpretation_readiness
```

The module reads the completed crash assignment, crash assignment QA outputs, endpoint/junction flags, and current scaffold recovery/source flags. It writes review-only files under:

- `work/output/roadway_graph/review/current/crash_assignment_interpretation_readiness/`

It is a classification/stratification layer only. It does not read the raw crash parquet, use crash direction fields, change assignment results, alter the scaffold, repair geometry, or infer upstream/downstream status.

Current interpretation-readiness readout:

| Metric | Count |
| --- | ---: |
| Assigned crashes reviewed | 38,403 |
| High-confidence spatial assignments | 2,306 |
| Medium or caveated spatial assignments | 27,020 |
| Low-confidence or review assignments | 9,077 |
| High-priority assigned-crash review rows | 631 |
| Recovered signal-association assigned crashes | 960 |
| Unresolved-near-scaffold rows reviewed | 3,003 |

Geometry caveat classes:

| Class | Assigned crashes |
| --- | ---: |
| method-allowed anchor relaxation | 21,738 |
| caveated valid dead-end or one-sided boundary | 7,496 |
| review-required unknown endpoint junction | 5,766 |
| no geometry caveat | 2,370 |
| provisional signal-association tolerance | 648 |
| high-risk low-confidence divided recovery | 385 |

The interpretation-readiness output is not a directional crash classification. It identifies what must be reviewed before directional/upstream-downstream interpretation can begin.

## Mapless Review Packets

Bounded mapless review packet module:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.crash_assignment_mapless_review_packets
```

This module exists because GIS inspection is not currently available. It creates tabular/Codex-native review packets from the completed crash assignment, interpretation-readiness classifications, endpoint/junction flags, and scaffold recovery/source flags.

The module writes review-only files under:

- `work/output/roadway_graph/review/current/crash_assignment_mapless_review_packets/`

It does not read the raw crash parquet, use crash direction fields, change assignment results, alter scaffold construction, repair geometry, or infer upstream/downstream status. Nearest-candidate metrics in the packet files are review diagnostics only; they are not a reassignment algorithm.

Current packet readout:

| Packet family | Rows |
| --- | ---: |
| high-priority assigned distance over 70 ft | 631 |
| assigned distance 50-70 ft | 1,746 |
| unknown endpoint review required | 5,766 |
| provisional signal-association assignments | 960 |
| low-confidence divided recovery assignments | 385 |
| unresolved within 75 ft of crash-ready bins | 433 |
| unresolved within 25 ft of crash-ready bins | 312 |

Recommended action highlights:

| Action | Family | Rows |
| --- | --- | ---: |
| review unknown endpoint | unknown endpoint | 5,454 |
| review parallel or divided ambiguity | assigned 50-70 ft | 1,128 |
| review signal association | signal association | 947 |
| keep spatial, exclude directional | assigned 50-70 ft | 618 |
| possible assignment logic issue | high-priority assigned distance | 465 |
| exclude from directional now | low-confidence divided | 385 |
| possible assignment logic issue | unresolved within 75 ft | 312 |

Signal-association packet actions:

- keep: 0
- review: 947
- exclude from directional now: 13

The mapless packets prepare later manual/GIS review and directional eligibility decisions. They do not make any crash ready for upstream/downstream interpretation by themselves.
