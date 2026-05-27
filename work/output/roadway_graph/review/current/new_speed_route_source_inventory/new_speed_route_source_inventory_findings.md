# New Speed/Route Source Inventory Findings

## Bounded Question

Can `VDOT_Routes.geojson` or `Speed_Limit_RNS` improve speed coverage or roadway identity for the existing roadway-derived directional-bin universe without modifying accepted speed v4 or downstream outputs?

## Source Utility

- VDOT_Routes useful: route_identity_supplement_only. It has route identity fields but no candidate speed-limit values.
- Speed_Limit_RNS useful: speed_source_supplement. It has speed values, route keys, edge IDs, and measure fields.

## Candidate Fields

- Candidate speed fields supporting speed values: Speed_Limit_RNS.CAR_SPEED_LIMIT, Speed_Limit_RNS.TRUCK_SPEED_LIMIT
- Candidate route identity overlap:
- VDOT_Routes: missing/review route match share 0.641115; source route keys 32046
- Speed_Limit_RNS: missing/review route match share 0.989547; source route keys 44794

## Recovery Estimate

- Current speed v4 missing/review bins with possible Speed_Limit_RNS route+measure speed candidates: 24,865
- Estimate is diagnostic only. It does not test all v4 directionality semantics and does not promote any speed value.

## Recommendation

- VDOT_Routes: Useful for route identity review/bridge diagnostics, not for speed values. Next module candidate: `vdot_routes_identity_bridge.py`.
- Speed_Limit_RNS: Promising as a supplement for current missing/review speed bins; do not replace v4 until directionality/measure semantics are validated. Next module candidate: `speed_context_join_v5_new_source_supplement.py`.

## QA

- existing_normalized_artifacts_overwritten: PASS (unchanged)
- current_speed_v4_outputs_overwritten: PASS (read_only)
- graph_context_rate_model_outputs_modified: PASS (module writes only new_speed_route_source_inventory review outputs)
- crash_direction_fields_read_or_used: PASS (none)
- source_coverage_estimates_diagnostic_only: PASS (diagnostic_only_no_join_output)
- recommendation_distinguishes_replacement_supplement_identity_bridge: PASS (replacement_vs_supplement column written)
- output_written_summary: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_inventory_summary.csv)
- output_written_schema: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_schema.csv)
- output_written_geometry: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_geometry_qa.csv)
- output_written_roles: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_field_role_candidates.csv)
- output_written_nonnull: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_non_null_profile.csv)
- output_written_route_overlap: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_route_identity_overlap.csv)
- output_written_speed_fields: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_speed_field_diagnostic.csv)
- output_written_recovery: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\speed_v4_missing_review_recovery_estimate.csv)
- output_written_comparison: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\speed_source_comparison_current_vs_new.csv)
- output_written_recommendation: PASS (work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_recommendation.csv)

## Outputs

- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_inventory_summary.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_schema.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_geometry_qa.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_field_role_candidates.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_non_null_profile.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_route_identity_overlap.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_speed_field_diagnostic.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\speed_v4_missing_review_recovery_estimate.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\speed_source_comparison_current_vs_new.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_recommendation.csv`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_inventory_findings.md`
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_inventory_manifest.json`
