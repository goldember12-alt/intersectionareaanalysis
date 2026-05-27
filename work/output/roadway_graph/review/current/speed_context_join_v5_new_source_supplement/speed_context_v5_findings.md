# Speed Context Join v5 New-Source Supplement Findings

## Bounded Question

Can `Speed_Limit_RNS` recover current speed v4 missing/review directional bins using route+measure evidence, while preserving speed v4 as the active accepted context?

## Files Read

- `Intersection Crash Analysis Layers\Speed_Limit_RNS\Speed_Limit_RNS.gdb` layer `Speed_Limit_RNS`
- `work\output\roadway_graph\review\current\speed_context_join_v4_identity_enriched\directional_bin_speed_context_v4.csv`
- `work\output\roadway_graph\analysis\current\directional_bin_context_table\directional_crash_context.csv`
- `artifacts\normalized\speed.parquet` for modification guard/comparison only
- `work\output\roadway_graph\review\current\new_speed_route_source_inventory\new_speed_route_source_inventory_manifest.json` as prior diagnostic provenance when present

## Key Counts

- v4 stable speed bins: 84857
- v5 candidate stable speed bins: 105835
- newly recovered stable bins from v4 missing/review: 20978
- v4 stable bins confirmed by v5: 29067
- v4 stable bins conflicting with v5: 2809
- v5 missing/review bins remaining: 4875
- crash rows inheriting stable v5 speed: 12750
- reference signals with stable v5 speed: 940

## Interpretation

Speed v5 is a candidate supplement, not an accepted replacement. It should not replace v4 as the active speed context until the conflict rows, weighted-transition behavior, and route/measure semantics are reviewed. Downstream combined context, rate, and model outputs should not be refreshed until v5 is explicitly accepted.

## QA

- crash_direction_fields_read_or_used: PASS (False)
- existing_speed_v4_outputs_overwritten: PASS (unchanged)
- normalized_speed_artifact_overwritten: PASS (unchanged)
- graph_context_rate_model_outputs_modified: PASS (module writes only speed_context_join_v5_new_source_supplement review outputs)
- route_measure_evidence_required_for_stable_v5_recovery: PASS (20978)
- conflicts_with_v4_preserved_not_overwritten: PASS (2809)
- v5_labeled_candidate_supplement_until_accepted: PASS (True)
- output_written_summary: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_context_v5_summary.csv)
- output_written_directional: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_bin_speed_context_v5.csv)
- output_written_directional_0_1000: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_bin_speed_context_v5_0_1000ft.csv)
- output_written_directional_1000_2500: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_bin_speed_context_v5_1000_2500ft.csv)
- output_written_crash: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_crash_speed_context_v5.csv)
- output_written_reference_summary: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\reference_signal_speed_context_summary_v5.csv)
- output_written_recovered: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_recovered_from_v4_missing_review.csv)
- output_written_comparison: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_comparison_to_v4.csv)
- output_written_conflict: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_conflict_with_v4_stable.csv)
- output_written_candidates: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_route_measure_candidates.csv)
- output_written_review: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_ambiguous_or_review_bins.csv)
- output_written_missing: PASS (work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_missing_bins.csv)

## Outputs

- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_context_v5_summary.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_bin_speed_context_v5.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_bin_speed_context_v5_0_1000ft.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_bin_speed_context_v5_1000_2500ft.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\directional_crash_speed_context_v5.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\reference_signal_speed_context_summary_v5.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_recovered_from_v4_missing_review.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_comparison_to_v4.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_conflict_with_v4_stable.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_route_measure_candidates.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_ambiguous_or_review_bins.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_missing_bins.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_v5_qa.csv`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_context_v5_findings.md`
- `work\output\roadway_graph\review\current\speed_context_join_v5_new_source_supplement\speed_context_v5_manifest.json`
