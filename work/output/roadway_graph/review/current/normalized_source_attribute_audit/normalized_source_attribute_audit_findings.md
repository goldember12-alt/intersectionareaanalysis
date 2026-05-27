# Normalized Source Attribute Audit Findings

## Bounded Question

Do the core normalized parquets preserve useful attributes from their likely source geodatabase layers, and does the access type gap reflect staging loss or an empty source layer?

## Datasets Audited

- roads: Travelway (Intersection Crash Analysis Layers\Travelway.gdb)
- access: layer_lrspoint (Intersection Crash Analysis Layers\accesspoints.gdb)
- speed: SDE_VDOT_SPEED_LIMIT_MSTR_RTE (Intersection Crash Analysis Layers\postedspeedlimits.gdb)
- aadt: New_AADT (Intersection Crash Analysis Layers\New_AADT.gdb)
- crashes: CrashData_Basic (Intersection Crash Analysis Layers\crashdata.gdb)
- signals: HMMS_TrafficSignals_Flat|Hampton_Signals|Norfolk_Signals (Intersection Crash Analysis Layers\HMMS_Traffic_Signals.gdb|Intersection Crash Analysis Layers\Hampton_Analysis.gdb|Intersection Crash Analysis Layers\Traffic_Signals_-_City_of_Norfolk.gdb)

## Main Findings

- Access source rows: 70,595; access parquet rows: 70,595.
- Access source type/context fields are present in the source schema, but the audited source layer has no populated values for the requested access type fields. The current access type gap is therefore not explained by parquet attribute loss from `layer_lrspoint`.
- High-severity preservation-loss datasets: none.
- The problem appears access-source-content-specific, not a broad normalized parquet preservation failure across speed, AADT, roads, crashes, and signals.
- Crash direction-like fields were not used for value profiling.

## Field Loss Flags

none

## Restaging Recommendations

- roads: not_required_for_attribute_preservation; priority `review`; impact: Travelway configuration, route, measure, median, lane, and identity fields appear preserved; improvements are more likely semantic decoding than restaging.
- access: do_not_restage_from_same_layer_for_type_values; priority `low`; impact: Same source layer has no populated access type/context fields; restaging from it alone is unlikely to enable typed access summaries.
- speed: not_required_for_attribute_preservation; priority `low`; impact: Posted-speed route, directionality, event, and measure fields appear preserved; missing/review speed bins likely need matching logic review, not source restaging.
- aadt: not_required_for_attribute_preservation; priority `low`; impact: AADT, year, direction factor, directionality, route, link, edge, and measure fields appear preserved; denominator policy remains a later analytical decision.
- crashes: not_required_for_attribute_preservation; priority `low`; impact: Basic crash context fields appear preserved; crash direction-like fields were not profiled or used.
- signals: not_required_for_attribute_preservation; priority `review`; impact: Normalized signals are a union of available signal sources; row-count and source-specific completeness should be reviewed before any signal restaging.

## Regeneration Implications

- If access is restaged from the same `layer_lrspoint` source, typed summaries are still unlikely because the source values are empty.
- If a different populated access type source is found and staged, rerun access staging, `access_context_join`, `access_type_inventory`, `directional_bin_context_table`, and downstream descriptive summaries after QA.
- If roads or signals are restaged, rerun the graph/scaffold/catchment/crash-assignment/context lineage because those inputs define the roadway universe.
- If speed or AADT are restaged, rerun their staging modules, corresponding context joins, the combined context table, and dependent descriptive/rate audit outputs.

## QA

- normalized_parquets_overwritten: PASS (unchanged)
- graph_context_rate_model_outputs_modified: PASS (module writes only normalized_source_attribute_audit review outputs)
- crash_direction_fields_used: PASS (crash direction-like fields excluded from value profiling)
- source_vs_parquet_comparisons_documented: PASS (schema and non-null comparison CSVs written)
- restaging_recommendations_executed: PASS (recommendations only; no restaging run)
- output_written_summary: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_attribute_audit_summary.csv)
- output_written_schema: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_schema_comparison.csv)
- output_written_nonnull: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_non_null_comparison.csv)
- output_written_flags: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_field_loss_flags.csv)
- output_written_access: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\access_source_attribute_preservation_audit.csv)
- output_written_speed: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\speed_source_attribute_preservation_audit.csv)
- output_written_aadt: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\aadt_source_attribute_preservation_audit.csv)
- output_written_roads: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\roads_source_attribute_preservation_audit.csv)
- output_written_crashes: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\crash_source_attribute_preservation_audit.csv)
- output_written_recommendations: PASS (work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_restaging_recommendations.csv)

## Outputs

- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_attribute_audit_summary.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_schema_comparison.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_non_null_comparison.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_field_loss_flags.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\access_source_attribute_preservation_audit.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\speed_source_attribute_preservation_audit.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\aadt_source_attribute_preservation_audit.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\roads_source_attribute_preservation_audit.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\crash_source_attribute_preservation_audit.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_restaging_recommendations.csv`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_attribute_audit_findings.md`
- `work\output\roadway_graph\review\current\normalized_source_attribute_audit\normalized_source_attribute_audit_manifest.json`
