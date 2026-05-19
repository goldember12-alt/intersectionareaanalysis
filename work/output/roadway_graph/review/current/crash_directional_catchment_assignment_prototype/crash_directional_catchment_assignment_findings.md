# Crash Directional Catchment Assignment Prototype

## Bounded Question

Assign normalized crash points to the existing usable roadway-only directional catchment surface.
This is assignment-only and is not final crash analysis.

## Method

- Crash source read columns: DOCUMENT_NBR, geometry.
- Usable catchments only: `catchment_status = usable`.
- Spatial predicate: `covered_by`.
- Catchment CRS handling: `catchment_crs_matches_authoritative_metadata`.
- Unique point-in-catchment matches inherit signal-relative direction from the catchment row.
- Multiple usable containing catchments are ambiguous; no containing usable catchment is unresolved.
- No nearest-bin assignment, crash direction fields, crash distributions, or crash-derived upstream/downstream logic were used.

## Counts

- Total crashes considered: 379272
- Uniquely assigned crashes: 17634
- Ambiguous crashes: 1055
- Unresolved crashes: 360583
- Assigned downstream crashes: 8791
- Assigned upstream crashes: 8843
- Assigned divided physical crashes: 4967
- Assigned undivided pseudo-direction crashes: 12667

## Top Ambiguity Reasons

- ambiguous_multiple_usable_directional_catchments: 1055

## Top Unresolved Reasons

- no_usable_directional_catchment_contains_point: 360583

## QA

- Usable catchment rows loaded: 200061
- Unstable or blocked catchment rows used: 0
- Crash direction fields read or used: False
- Scaffold or catchment construction changed: False
- Assigned rows inherit upstream/downstream only from `signal_relative_direction` on matched catchments.

## Remaining Uncertainty

- Boundary behavior follows the available GeoPandas spatial predicate listed above.
- Ambiguous overlaps are preserved for review rather than resolved by nearest-distance logic.
- Unresolved rows are not interpreted as absence of downstream relevance; they only failed containment in the current usable surface.
