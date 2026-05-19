# Urban/Rural Source Recovery Findings

## Bounded Question

Recover and rank possible urban/rural context sources for the stable 0-2,500 ft directional-bin universe. This is diagnostic-only and does not update the combined context table.

## Search Scope

- text roots: src | docs | legacy | artifacts | work\output
- artifact roots: artifacts\normalized | artifacts\staging | artifacts\staged | work\output
- geodatabase root: Intersection Crash Analysis Layers
- text hits: 46656
- artifact candidate fields: 587
- geodatabase layers inspected: 9

## Best Candidate

- source: artifacts\normalized\aadt.parquet:aadt.FROM_PHY_JURISDICTION_NM
- source type: jurisdiction/planning proxy
- defensible for candidate bin join now: False
- recommended join method: route/measure or route identity review
- rationale: proxy context only; needs documented urban-area or policy definition

## Coverage

- total stable bins: 110710
- 0-1,000 ft bins: 66074
- 1,000-2,500 ft bins: 44636
- reference signals: 971
- bins with assigned crashes: 8552
- estimated covered bins for best candidate: 
- coverage status: not_defensible_for_bin_context

## Interpretation

The recovered legacy signal-centered RU outputs are crash `AREA_TYPE` context, not roadway-level urban/rural truth. Roadway Travelway/roads sources inspected here do not expose a direct urban/rural field. Jurisdiction, district, MPO, signal area, and functional-class fields remain proxies or require source-definition review before use.

## QA

- crash direction fields read or used: false
- scaffold/catchment/crash-assignment/access/speed/AADT logic changed: false
- combined directional-bin context table overwritten: false
- crash AREA_TYPE labeled crash-level only: true

## Files Created

- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_source_recovery_summary.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_code_doc_search_hits.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_artifact_schema_hits.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_gdb_layer_inventory.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_candidate_field_inventory.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_candidate_source_ranking.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_candidate_join_key_audit.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_candidate_coverage_estimate.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_rejected_candidates.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_source_recovery_findings.md`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_source_recovery_manifest.json`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_source_recovery_progress.log`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_candidate_join_preview.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_candidate_bin_coverage.csv`
- `work\output\roadway_graph\review\current\urban_rural_source_recovery\urban_rural_candidate_signal_coverage.csv`
