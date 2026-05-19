# Context Source Inventory Findings

## Bounded Question

Step 6 Stage A inventory and schema audit for access and speed context sources. This module does not implement access or speed joins.

## Files Inspected

- `artifacts/normalized/access.parquet`
- `artifacts/normalized/speed.parquet`
- `work/output/stage1b_study_slice/Study_Signals_SpeedContext.parquet`
- speed-name candidates under `artifacts/` and `work/output/`
- `work\output\roadway_graph\review\current\crash_directional_assignment_analysis_readiness\crash_directional_assignment_readiness_by_crash.csv` (present)
- `work\output\roadway_graph\review\current\reference_signal_directional_scaffold_qa\directional_scaffold_prototype_usable_bins_50ft.csv` (present)
- `work\output\roadway_graph\review\current\reference_signal_directional_bin_catchments\directional_bin_catchment_index.csv` (present)
- `work\output\roadway_graph\review\current\reference_signal_directional_bin_catchments\directional_bin_catchment_polygons.geojson` (present)
- `work\output\roadway_graph\review\current\crash_directional_catchment_assignment_prototype\crash_directional_catchment_assignments.csv` (present)

## Files Created

- `work\output\roadway_graph\review\current\context_source_inventory\context_source_inventory_summary.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\access_source_schema.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\access_source_geometry_qa.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\access_source_crs_sanity.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\access_source_field_role_candidates.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\access_source_duplicate_null_qa.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\access_source_stable_universe_proximity_diagnostic.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\speed_source_inventory.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\speed_source_missing_or_candidate_files.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\context_source_inventory_findings.md`
- `work\output\roadway_graph\review\current\context_source_inventory\context_source_inventory_manifest.json`
- `work\output\roadway_graph\review\current\context_source_inventory\speed_source_schema.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\speed_source_geometry_qa.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\speed_source_crs_sanity.csv`
- `work\output\roadway_graph\review\current\context_source_inventory\speed_source_field_role_candidates.csv`

## Access Source

- `access.parquet` exists: True
- access row count: 70595
- access CRS: EPSG:3968
- access geometry types: Point=70595
- coordinate compatibility with stable universe: compatible_range
- likely ID fields: id, _editId, _layerId, _featureId
- likely route/road/name fields: CROSS_STREET, TURN_LANES_PRIMARY_ROUTE, _rte_nm
- likely access type/category fields: INDUSTRIAL, RESIDENTIAL, ACCESS_CONTROL, ACCESS_DIRECTION, COMMERCIAL_RETAIL, NUMBER_OF_APPROACHES, GOV_SCHOOL_INSTITUTIONAL, TURN_LANES_PRIMARY_ROUTE
- side/direction context fields found but not used for upstream/downstream: ACCESS_DIRECTION

## Access Proximity Diagnostic

- proximity_diagnostic_status: completed_diagnostic_only_not_join
- access_crs_handling: reprojected_to_stable_crs_for_diagnostic
- access_features_considered:  70595
- usable_directional_catchments_considered:  200061
- access_features_within_100ft_of_usable_directional_catchment:  5780
- access_features_within_250ft_of_usable_directional_catchment:  6281
- access_features_nearest_to_high_priority_0_1000ft_stable_universe_within_250ft:  2832
- access_features_nearest_to_sensitivity_1000_2500ft_stable_universe_within_250ft:  1275
- access_features_nearest_to_review_only_over_2500ft_stable_universe_within_250ft:  2196
- access_features_nearest_to_unknown_stable_universe_within_250ft:  0
- access_features_nearest_to_stable_universe_by_signal_relative_direction_within_250ft: downstream_of_reference_signal 3312
- access_features_nearest_to_stable_universe_by_signal_relative_direction_within_250ft: upstream_of_reference_signal 3190

These counts are diagnostic only. They are not access assignments and do not alter the stable universe.

## Speed Source

- `speed.parquet` exists: False
- `Study_Signals_SpeedContext.parquet` exists: False
- candidate speed-name files found elsewhere: 4

No final speed join rule is designed here because Stage A only records source availability and schema basics.

## Methodological Boundary Checks

- access joins implemented: False
- speed joins implemented: False
- scaffold construction modified: False
- directional catchments modified: False
- crash assignment or readiness modified: False
- crash direction fields read or used: False

## Recommended Next Step

- If access geometry and CRS are usable, implement the bounded access context join as the next available context layer.
- If speed remains missing, recover or restage a posted-speed source before implementing speed context.
