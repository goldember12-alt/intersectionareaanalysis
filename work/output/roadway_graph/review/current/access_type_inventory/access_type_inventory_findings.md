# Access Type Inventory Findings

## Bounded Question

Can the existing access base layer support typed access summaries for the roadway-derived directional-bin context universe without changing the access join or final context tables?

## Source Fields Found

- Access source rows: 70,595
- Source fields: 27
- Candidate access type fields inspected: ACCESS_DIRECTION, ACCESS_CONTROL, NUMBER_OF_APPROACHES, INDUSTRIAL, RESIDENTIAL, COMMERCIAL_RETAIL, GOV_SCHOOL_INSTITUTIONAL, TURN_LANES_PRIMARY_ROUTE, CROSS_STREET
- Populated candidate access type fields: none

## Full vs RIRO Feasibility

- Full vs right-in/right-out directly available: no
- Full vs right-in/right-out inferable from field combinations: no
- Matched stable-universe access points with usable type: 0 of 3,040
- Directional-bin access context upgrade recommendation: do not implement typed access summaries yet; retain counts-only context until a populated movement-permission/type source is available.

## Limitations

- The explicit access type and movement fields are present but unpopulated in `artifacts/normalized/access.parquet`.
- Land-use/access point type fields cannot be used as policy or movement-permission evidence when empty.
- `NUMBER_OF_APPROACHES` and turn-lane fields cannot distinguish full access from RIRO or one-way restrictions without populated values and validation.
- Existing access-context join outputs were read only for coverage; no source join or final context table was modified.
- No crash direction fields were used.

## QA

- crash_direction_fields_read_or_used: PASS (none)
- source_joins_modified: PASS (read_only_existing_access_join_outputs)
- final_context_tables_overwritten: PASS (no_writes_to_analysis_current_directional_bin_context_table)
- full_vs_riro_inference_labeled: PASS (direct=not_supported;combination=not_supported)
- unknown_and_not_inferable_preserved: PASS (unknown|not_inferable)
- candidate_access_type_mapping_written: PASS (False)
- output_written_source_schema: PASS (work\output\roadway_graph\review\current\access_type_inventory\access_type_source_schema.csv)
- output_written_candidate_fields: PASS (work\output\roadway_graph\review\current\access_type_inventory\access_type_candidate_fields.csv)
- output_written_value_counts: PASS (work\output\roadway_graph\review\current\access_type_inventory\access_type_value_counts.csv)
- output_written_missingness: PASS (work\output\roadway_graph\review\current\access_type_inventory\access_type_missingness_summary.csv)
- output_written_feasibility: PASS (work\output\roadway_graph\review\current\access_type_inventory\access_type_inference_feasibility.csv)
- output_written_coverage: PASS (work\output\roadway_graph\review\current\access_type_inventory\matched_access_type_coverage.csv)
- output_written_join_preview: PASS (work\output\roadway_graph\review\current\access_type_inventory\access_type_join_preview.csv)

## Outputs

- `work\output\roadway_graph\review\current\access_type_inventory\access_type_source_schema.csv`
- `work\output\roadway_graph\review\current\access_type_inventory\access_type_candidate_fields.csv`
- `work\output\roadway_graph\review\current\access_type_inventory\access_type_value_counts.csv`
- `work\output\roadway_graph\review\current\access_type_inventory\access_type_missingness_summary.csv`
- `work\output\roadway_graph\review\current\access_type_inventory\access_type_inference_feasibility.csv`
- `work\output\roadway_graph\review\current\access_type_inventory\matched_access_type_coverage.csv`
- `work\output\roadway_graph\review\current\access_type_inventory\access_type_join_preview.csv`
- `work\output\roadway_graph\review\current\access_type_inventory\access_type_inventory_findings.md`
- `work\output\roadway_graph\review\current\access_type_inventory\access_type_inventory_manifest.json`
