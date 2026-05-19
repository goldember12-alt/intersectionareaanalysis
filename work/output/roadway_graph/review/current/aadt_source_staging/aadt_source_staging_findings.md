# AADT Source Staging Findings

## Bounded Question

Find, inspect, and stage the AADT source only. No AADT-to-directional-bin context join is implemented.

## Candidate Files Found

- `Intersection Crash Analysis Layers\HMMS_Traffic_Signals.gdb`
- `Intersection Crash Analysis Layers\New_AADT.gdb`
- `Intersection Crash Analysis Layers\Traffic_Signals_-_City_of_Norfolk.gdb`
- `Intersection Crash Analysis Layers\VDOT_Bidirectional_Traffic_Volume_2024 (1)`
- `artifacts\normalized\aadt.parquet`

## Selected Source

- selected source: `Intersection Crash Analysis Layers\New_AADT.gdb`
- selected layer: `New_AADT`
- row count: 677597
- CRS: EPSG:3857
- geometry type: MultiLineString
- likely AADT fields: AADT
- likely year fields: AADT_YR
- likely route/road fields: RTE_NM|MASTER_RTE_NM|EDGE_RTE_KEY
- likely directionality fields: DIRECTION_FACTOR|DIRECTIONALITY
- likely source ID fields: LINKID|EDGE_RTE_KEY

## Normalized Artifact

- `artifacts/normalized/aadt.parquet` created: True
- normalized geometry CRS: EPSG:3968 when written
- source GDB, layer, source CRS, and normalized CRS metadata fields are preserved on each row

## Files Created

- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_inventory.csv`
- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_schema.csv`
- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_geometry_qa.csv`
- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_crs_sanity.csv`
- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_field_role_candidates.csv`
- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_duplicate_null_qa.csv`
- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_staging_findings.md`
- `work\output\roadway_graph\review\current\aadt_source_staging\aadt_source_staging_manifest.json`

## Boundary Checks

- crash data read: False
- crash direction fields read or used: False
- AADT-to-bin join implemented: False
- directional bin context table modified: False
- roadway graph scaffold modified: False
- QA checks passed: 13 of 13

## Recommended Next Step

Implement a separate read-only AADT-to-directional-bin context join using `artifacts/normalized/aadt.parquet`, exact route support, documented route measures, local geometry-distance QA, and explicit unresolved/ambiguous statuses.
