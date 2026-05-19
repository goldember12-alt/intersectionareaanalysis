# Speed Context Join v4 Identity-Enriched Findings

## Bounded Question

Attach posted speed as a read-only flagged context layer to existing 0-2,500 ft directional bins using propagated roadway identity route and directionality fields, with route-measure overlap used for stable assignment. Do not alter scaffold, catchments, crash assignment, access, AADT, or upstream/downstream logic.

## Run Scope

- limit route groups: none
- crash direction fields read or used: False
- speed used for upstream/downstream: False
- scaffold/catchment/assignment/access/AADT logic changed: False
- nearest-any stable promotion: 0

## Key Counts

- stable speed bins: 84857
- stable single-speed bins: 48075
- stable weighted transition bins: 36782
- missing/no route-compatible bins: 8091
- review route mismatch bins: 17762
- review route missing bins: 0
- review directionality mismatch bins: 0
- review unresolved speed conflict bins: 0
- crashes inheriting stable speed: 9671
- reference signals with stable speed: 685
- paired pseudo-direction inconsistent groups: 0

## v3 Comparison

| metric | v3_count | v4_count | v4_minus_v3 |
|---|---:|---:|---:|
| stable_single_speed_bins | 75590 | 48075 | -27515 |
| stable_weighted_transition_bins | 3996 | 36782 | 32786 |
| total_stable_speed_bins | 79586 | 84857 | 5271 |
| missing_speed_bins | 31124 | 8091 | -23033 |
| review_speed_bins | 0 | 17762 | 17762 |
| crashes_inheriting_stable_speed | 9493 | 9671 | 178 |
| reference_signals_with_stable_speed | 668 | 685 | 17 |

## Files Created

- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_context_v4_summary.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\base_bin_speed_context_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\directional_bin_speed_context_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\directional_bin_speed_context_v4_0_1000ft.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\directional_bin_speed_context_v4_1000_2500ft.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\directional_crash_speed_context_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\reference_signal_speed_context_summary_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_route_identity_match_qa_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_directionality_match_qa_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_missing_bins_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_review_bins_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_weighted_transition_bins_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_paired_pseudo_direction_consistency_qa_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_context_v4_comparison_to_v3.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_context_v4_qa.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_context_v4_findings.md`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_context_v4_manifest.json`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\speed_context_v4_progress.log`
