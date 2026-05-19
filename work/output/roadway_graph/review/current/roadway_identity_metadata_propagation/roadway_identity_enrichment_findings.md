# Roadway Identity Metadata Propagation Findings

## Bounded Question

Propagate upstream roadway identity metadata into the stable directional segment/bin universe and estimate whether AADT or speed matching should be reworked against enriched identity fields. This does not alter scaffold topology, catchments, crash assignment, access, speed, AADT, or upstream/downstream logic.

## Key Results

- best propagation path: artifacts/normalized/roads.parquet source_road_row_id -> role_enriched_segments.source_road_row_id -> usable base_segment_id/reference_directional_segment_id -> usable bins
- directional segments enriched: 4820 of 4828
- directional bins enriched: 208170 of 208340
- bins with enriched route key present in AADT: 110402
- prior AADT review bins recoverable by enriched route key estimate: 62012
- prior AADT review bins recoverable by enriched event-source numeric LINKID estimate: 674
- bins with enriched route key present in speed: 93234
- prior speed review/missing bins recoverable by enriched speed route key estimate: 13648
- paired/directional bin duplicate issues introduced: 0

## Interpretation

The source_road_row_id lineage is reliable for metadata propagation and restores Travelway route and measure fields into the directional-bin context universe. The enriched tables do not create a useful LinkID_Norm bridge, and event_source-to-AADT.LINKID remains weak, but they do make a route+measure AADT v3 join feasible for review because source RTE_NM/RTE_COMMON and source measure pairs are now available on the stable bins. Speed v4 is worth considering as an identity-enriched route-assisted join, but only as a route/name and directionality cleanup; it should not promote spatial-only nearest speed.

## Files Created

- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\aadt_identity_enriched_linkid_match_diagnostic.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\aadt_identity_enriched_match_diagnostic.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\aadt_identity_enriched_measure_feasibility.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\aadt_identity_enriched_recovery_estimate.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\aadt_identity_enriched_route_match_diagnostic.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\base_bins_identity_enriched.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\directional_bins_identity_enriched.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\directional_segments_identity_enriched.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_enrichment_qa.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_field_inventory.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_field_lineage_candidates.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_enrichment_findings.md`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_join_key_candidates.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_enrichment_manifest.json`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_missingness_by_table.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_propagation_key_audit.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\speed_identity_enriched_match_diagnostic.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\speed_identity_enriched_recovery_estimate.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\speed_identity_enriched_route_match_diagnostic.csv`
- `work\output\roadway_graph\review\current\roadway_identity_metadata_propagation\roadway_identity_unique_value_profile.csv`
