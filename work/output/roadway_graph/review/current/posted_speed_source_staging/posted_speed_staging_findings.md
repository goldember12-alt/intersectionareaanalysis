# Posted Speed Source Staging Findings

## Bounded Question

Recover and stage the posted-speed source only. No speed-to-bin context join is implemented.

## Files And Layers Inspected

- `Intersection Crash Analysis Layers\postedspeedlimits.gdb`
- layer `SDE_VDOT_SPEED_LIMIT_MSTR_RTE` (MultiLineString)

## Selected Layer

- selected speed layer: `SDE_VDOT_SPEED_LIMIT_MSTR_RTE`
- row count: 38723
- CRS: EPSG:3857
- geometry type: MultiLineString
- likely speed fields: CAR_SPEED_LIMIT|TRUCK_SPEED_LIMIT
- likely route/road fields: ROUTE_COMMON_NAME|LOC_COMP_DIRECTIONALITY_NAME|ROUTE_FROM_MEASURE|FROM_JURISDICTION|ROUTE_TO_MEASURE|TO_JURISDICTION|SUB_DIVISION_NAME|RTE_TYPE_CD|RTE_TYPE_NM|FROM_DISTRICT|TO_DISTRICT
- likely ID fields: EVENT_SOURCE_ID|RESOLUTION_ID|EVENT_LOCATION_ID|EVENT_COMPONENT_ID

## Normalized Artifact

- `artifacts/normalized/speed.parquet` created: True
- normalized geometry CRS: EPSG:3968 when written
- source GDB, layer, and source CRS metadata fields are preserved on each row

## Files Created

- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_source_inventory.csv`
- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_schema.csv`
- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_geometry_qa.csv`
- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_crs_sanity.csv`
- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_field_role_candidates.csv`
- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_duplicate_null_qa.csv`
- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_staging_findings.md`
- `work\output\roadway_graph\review\current\posted_speed_source_staging\posted_speed_staging_manifest.json`

## Boundary Checks

- crash data read: False
- crash direction fields read or used: False
- speed-to-bin join implemented: False
- roadway graph scaffold modified: False
- directional catchments modified: False
- crash assignment modified: False
- QA checks passed: 10 of 10

## Recommended Next Step

Implement a read-only speed-to-directional-bin context join using `artifacts/normalized/speed.parquet`, with route/measure and spatial support reported as QA. Keep it separate from scaffold, catchment, crash-assignment, and access-context logic.
