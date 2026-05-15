# Roadway Graph Geometric Direction Model

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This pass adds a roadway-geometry-derived movement-orientation model to the Step 5 crash-ready segment and bin subset.

It answers a narrower question than crash assignment:

- can the crash-ready roadway scaffold identify movement-orientation candidates from roadway geometry and signal/anchor relationships without using crash data?

It does not assign crashes, infer vehicle direction from crash records, validate direction from crash distributions, or change the old signal-centered crash/access modules.

## Command

Run with the bootstrap-reported interpreter:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.geometric_direction
```

## Inputs

The model reads only roadway graph outputs:

- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`
- `work/output/roadway_graph/tables/current/divided_edge_directional_candidates.csv`
- `work/output/roadway_graph/tables/current/undivided_edge_candidates.csv`

Crash records are not read.

## Outputs

Tables:

- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_geometric_direction.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_geometric_direction.csv`

Review tables:

- `work/output/roadway_graph/review/current/geometric_direction_summary.csv`
- `work/output/roadway_graph/review/current/geometric_direction_divided_pairing_summary.csv`
- `work/output/roadway_graph/review/current/geometric_direction_undivided_centerline_summary.csv`
- `work/output/roadway_graph/review/current/geometric_direction_problem_rows.csv`

Review GeoJSON:

- `work/output/roadway_graph/review/geojson/current/geometric_direction_divided_review.geojson`
- `work/output/roadway_graph/review/geojson/current/geometric_direction_undivided_review.geojson`

## Method

### Divided Roads

For divided rows, the model derives a geometry direction family from the unordered anchor pair and route name. It then defines a family reference vector from anchor A to anchor B.

Candidate carriageways are tested against that reference vector:

- right side of A to B = `A_to_B` movement candidate
- left side of A to B = `B_to_A` movement candidate
- center, ambiguous, or unsupported cases remain unresolved

The model requires candidate geometries to bracket the reference vector with both left and right side evidence before assigning divided movement candidates. This avoids treating a single curved carriageway, or reciprocal records of the same physical carriageway, as if they were opposing divided-road carriageways.

### Undivided Roads

Undivided roads remain one logical centerline segment. They are not duplicated into two physical directional carriageways.

For undivided rows, the model prepares later side-of-centerline event interpretation:

- `centerline_reference_orientation = A_to_B`
- `right_side_event_candidate = A_to_B`
- `left_side_event_candidate = B_to_A`
- `geometric_direction_method = undivided_centerline_side_rule`
- `physical_directional_carriageway = false`

No crash event direction is assigned in this pass.

## Current Results

The current crash-ready subset contains:

- 4,305 geometric-direction segment rows
- 159,578 geometric-direction bin rows
- 2,293 divided rows
- 2,012 undivided rows

Divided movement orientation:

- `A_to_B`: 0
- `B_to_A`: 0
- `unresolved`: 2,293

The divided rows remain unresolved because the current crash-ready subset does not contain geometry families with both left and right candidate carriageways bracketing the reference vector. Problem reasons:

- 1,845 `single_carriageway_no_side_reference`
- 272 `geometry_too_close_to_reference_line`
- 176 `candidate_geometries_do_not_bracket_reference`

Undivided centerline preparation:

- 2,012 rows prepared for centerline-side interpretation
- 0 undivided rows marked as physical directional carriageways
- 0 rows with `true_vehicle_direction_inferred != false`

## Interpretation

This is a roadway-geometry-derived orientation model, not crash-derived validation. It preserves the correction that crashes should later be assigned to roadway direction candidates, while crashes must not define the roadway direction model.

The current divided result is intentionally conservative. The crash-ready segment subset is useful for reference-signal-centered spatial assignment, but it does not yet expose paired opposite-carriageway geometry in a way that supports high-confidence right-hand-side movement orientation. That should be fixed in the roadway geometry layer or pairing logic, not by reading crash records.

The undivided result is ready as a side-rule scaffold for later event interpretation, but final upstream/downstream crash interpretation still requires a later crash-side or crash-direction workflow.

## Recommendation

Do not use the current divided geometric direction fields for final crash-direction or upstream/downstream classification. Use the outputs for review and for designing a better divided-carriageway pairing step.

Crash assignment should be rerun or updated only after the geometric direction model is reviewed. Until divided carriageway pairing improves, downstream crash interpretation should remain unresolved for divided rows rather than forced.
