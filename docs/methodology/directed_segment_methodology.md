# Directed Signal-Leg Methodology: Road-Network-First Downstream Analysis

## Bounded Question

This methodology pass answers a road-network geometry question:

- model signalized intersections as nodes
- build oriented roadway legs anchored at those signal nodes
- use adjacent signal, access-point, or roadway endpoint anchors as leg termini
- cut each oriented leg into fixed 50-foot bins

This workflow does not infer true vehicle travel direction. It only creates oriented geometries so an anchor order such as A-to-B can be distinguished from the reciprocal B-to-A geometry. Crash records and crash direction fields are intentionally excluded.

## Method Pivot

The previous first pass produced signal-pair-only segments between adjacent signalized intersections. That approach is now superseded by signal-anchored directed legs.

A signalized intersection may have multiple roadway legs. A normal four-leg divided intersection may produce up to eight oriented legs: an inbound and outbound oriented geometry for each roadway approach/departure side. Three-legged intersections may produce fewer. The workflow should preserve those legs as geometry scaffolds without interpreting them as true vehicle movements.

Leg types are explicit:

- `signal_to_signal`: an oriented leg from a reference signal to an adjacent signal on the same route/carriageway sequence
- `signal_to_access`: an oriented leg from a reference signal to a same-route access point when no adjacent signal anchor exists on that side
- `signal_to_road_endpoint`: a support leg from a reference signal to the available divided-road route endpoint
- `signal_to_search_cutoff`: reserved for later bounded cutoff logic
- `access_to_signal`: reserved if a later pass needs reciprocal access-anchored geometry

`signal_to_signal` legs can support between-signal bins. `signal_to_access` legs can support downstream access-spacing and access-context bins. Endpoint and cutoff legs are QA/support objects.

## Orientation Meaning

`orientation_label` means only that the row geometry is ordered from one anchor to another. It does not mean the roadway carries vehicles in that direction.

Current labels:

- `from_anchor_to_to_anchor`
- `to_anchor_to_from_anchor`

Current QA fields:

- `orientation_method`
- `qa_orientation_status`
- `orientation_review.csv`

The older `direction_conflict_review` naming is superseded because there is no vehicle-travel direction claim in this workflow.

## Evidence Sources

This workflow uses:

- `Study_Roads_Divided.parquet` for divided roadway geometry, route fields, measure ranges, and roadway context
- `Study_Signals_NearestRoad.parquet` for signal nodes and nearest divided-road match QA fields
- `artifacts/normalized/access.parquet` for optional same-route access termini
- route/carriageway grouping and roadway measure order to build oriented geometry

This workflow does not use:

- crash records
- crash direction of travel
- crash maneuver fields
- prior upstream/downstream crash classification outputs

## Output Meaning

The first stable output units are:

- one row per usable signal node
- one row per oriented signal-anchored roadway leg
- one row per 50-foot bin along each oriented leg
- QA rows for unresolved signal legs, short/problem legs, and orientation review cases
- anchor summaries showing signal, access, and endpoint use

The outputs are descriptive and review-oriented. They are not regression-ready and do not make policy claims. They are a road-network scaffold for later crash, access, AADT, speed, and median joins once geometry and orientation QA have been reviewed.

## Unresolved Cases

If a leg cannot be created from available anchors and geometry, the reference signal is retained in `rejected_or_unresolved_signal_legs.csv`. If a leg exists but uses fallback geometry, is very short, has zero length, or terminates at a support endpoint, it is retained and surfaced in `orientation_review.csv` or `short_or_problem_legs.csv`.

Manual map review or a later trusted roadway-orientation source may improve these rows. Crash data must not be used for that promotion in this no-crash pass.

