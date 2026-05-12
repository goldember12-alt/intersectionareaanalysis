# Roadway Graph Foundation Methodology

## Bounded Purpose

The roadway graph foundation builds a full-roadway, signal-adjacent scaffold for later downstream functional area analysis.

This phase answers a graph construction question only:

- which roadway geometry branches are adjacent to each signalized intersection, while preserving both divided and undivided roadway evidence?

It does not answer:

- which direction vehicles are traveling
- which side of a signal is downstream
- which crashes belong to a signal or segment
- which graph edges are analysis-ready

## Active Scope

The graph foundation uses the full normalized Travelway road artifact:

- `artifacts/normalized/roads.parquet`

This is different from the older directed signal-leg prototype, which used:

- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`

The graph foundation retains both divided and undivided roadways. That is now the correct foundation for intersection mapping.

## Divided and Undivided Roads

Divided/undivided classification is descriptive at this stage.

The prototype uses available Travelway fields such as:

- `RIM_FACILI`
- `RIM_MEDIAN`
- `RIM_COUPLE`

Current descriptive classes include:

- `divided`
- `undivided`
- `likely_divided`
- `unknown`

These classes describe the source roadway geometry and candidate future treatment. They are not true vehicle-direction assignments.

For divided roadways, later workflow may create directional or carriageway-specific analysis records.

For undivided roadways, the graph should preserve a centerline or logical segment record. Directional crash assignment for undivided segments comes later and should use crash direction information when that phase is explicitly implemented.

## Graph Construction Principle

Signals are intersection anchors, but each signal may connect to multiple nearby Travelway branches.

The graph foundation must not limit a signal to one nearest route or one nearest carriageway. A normal four-leg intersection should generally have multiple adjacent graph edges where the geometry supports them.

The prototype therefore:

1. explodes normalized Travelway `MultiLineString` geometry into graph components;
2. keeps route, measure, facility, median, and classification fields;
3. associates each signal point to every nearby Travelway component within a documented tolerance;
4. creates snapped signal graph nodes on those components;
5. creates signal-adjacent graph edges from each snapped signal graph node to nearby signal nodes or roadway endpoints on the same source component;
6. writes QA layers for zero, one, and high adjacent-edge counts.

This is a graph-foundation prototype, not the final routable roadway network.

## Anchor Types

Graph node types may include:

- `signal`
- `road_intersection`
- `road_endpoint`
- `synthetic_split_node`
- `unresolved`

In the first prototype, signal nodes are snapped signal-road component associations. Road endpoint/intersection nodes come from source Travelway component endpoints. An endpoint coordinate shared by more than one component is marked as `road_intersection`; otherwise it is marked as `road_endpoint`.

Access points are not primary termini in this prototype. Access fallback should remain separate and explicitly marked as support-only if added later.

## Directionality Boundary

The graph foundation does not infer true vehicle travel direction.

Line order in geometries is only source geometry order or signal-to-adjacent-anchor order for review. It must not be interpreted as vehicle movement.

The field `true_vehicle_direction_inferred` remains `False`.

## Crash Boundary

The graph foundation does not read crash data and does not assign crashes.

Crash assignment, directional crash interpretation, upstream/downstream labeling, and analysis-ready gating are later phases. They should only be added after graph QA review confirms the foundation is suitable.

## Relationship To Prior Directed Segments

The prior `directed_segments` workflow is superseded for graph foundation purposes because it is divided-road-only and creates lower/higher measure-side signal legs from one nearest divided route/carriageway.

It remains useful as historical/prototype output and as a comparison point for the divided-road vertical slice. It should not be deleted by the graph prototype.

## Validation Expectations

Each graph build should report:

- full road input row count
- exploded graph component count
- signal input row count
- graph node count
- graph edge count
- signal graph node count
- signal adjacent edge count
- 50-foot bin count
- graph gap review count
- divided and undivided candidate counts
- confirmation that crash data was not used
- confirmation that true vehicle direction was not inferred

Review should focus first on:

- signals with zero adjacent edges
- signals with one adjacent edge
- signals with unusually high adjacent-edge counts
- signals whose snapped road distance exceeds the review threshold
- interchange, ramp, frontage-road, or grade-separated cases
- cases where nearby roads appear not to split or intersect correctly

