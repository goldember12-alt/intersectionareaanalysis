# AADT Context Join v3 Identity Route-Measure Findings

## Bounded Question

Attach AADT as a read-only flagged context layer to existing 0-2,500 ft directional bins using enriched roadway identity route keys and route-measure interval overlap. Do not alter scaffold, catchments, crash assignment, access, speed, or upstream/downstream logic.

## Run Scope

- limit route groups: none
- crash direction fields read or used: False
- AADT used for upstream/downstream: False
- scaffold/catchment/assignment/access/speed logic changed: False

## Key Counts

- bins with stable AADT: 106210
- route+measure stable bins: 106210
- single-route-candidate stable bins: 0
- review no-measure-overlap bins: 510
- review measure-missing bins: 0
- review multi-candidate route-measure bins: 1878
- ambiguous/conflicting AADT bins: 473
- no route-compatible AADT match bins: 1639
- crashes inheriting stable AADT: 12630
- reference signals with stable AADT: 954
- paired pseudo-direction inconsistent groups: 0
- AADT ready as strong flagged context layer: True

## v1/v2 Comparison

| metric | v1_count | v2_count | v3_count | v3_minus_v1 | v3_minus_v2 |
|---|---:|---:|---:|---:|---:|
| bins_with_stable_aadt | 46089 | 46094 | 106210 | 60121 | 60116 |
| ambiguous_conflicting_aadt_bins | 1935 | 2296 | 473 | -1462 | -1823 |
| crashes_inheriting_stable_aadt | 7951 | 7960 | 12630 | 4679 | 4670 |
| reference_signals_with_stable_aadt | 574 | 587 | 954 | 380 | 367 |
| route_measure_stable_bins | 0 | 0 | 106210 | 106210 | 106210 |
| stable_single_route_candidate_bins | 0 | 6 | 0 | 0 | -6 |
| review_or_missing_bins | 64621 | 64616 | 4500 | -60121 | -60116 |

## Files Created

- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_context_v3_summary.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\base_bin_aadt_context_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\directional_bin_aadt_context_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\directional_bin_aadt_context_v3_0_1000ft.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\directional_bin_aadt_context_v3_1000_2500ft.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\directional_crash_aadt_context_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\reference_signal_aadt_context_summary_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_route_measure_candidates_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_route_measure_review_candidates_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_route_measure_ambiguous_matches_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_route_measure_missing_bins_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_route_measure_match_qa_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_paired_pseudo_direction_consistency_qa_v3.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_context_v3_comparison_to_v1_v2.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_context_v3_qa.csv`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_context_v3_findings.md`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_context_v3_manifest.json`
- `work\output\roadway_graph\review\current\aadt_context_join_v3_identity_route_measure\aadt_context_v3_progress.log`
