# Active Speed Context Policy Findings

## Bounded Question

Promote speed v5 as the active speed context going forward, while preserving speed v4 as baseline/legacy comparison and avoiding downstream reruns in this task.

## Active Policy

`speed_v5_new_source_supplement` is active going forward.

- Speed_Limit_RNS route+measure evidence is preferred.
- Speed v4 is retained as baseline/legacy comparison.
- V4/v5 conflicts are QA evidence, not blockers to v5 promotion.
- Remaining v5 review/missing statuses stay visible.
- No speed values are imputed.

## Policy Summary

- v4 stable speed bins: 84857
- v5 stable speed bins: 105835
- newly recovered stable bins from v4 missing/review: 20978
- v5 missing/review bins remaining: 4875
- v4 stable bins confirmed by v5: 29067
- v4 stable bins conflicting with v5: 2809
- crash rows inheriting stable v5 speed: 12750
- reference signals with stable v5 speed: 940

## QA

- speed_v4_outputs_overwritten: PASS (unchanged)
- normalized_speed_parquet_overwritten: PASS (unchanged)
- graph_context_rate_model_outputs_silently_changed: PASS (policy_record_only)
- crash_direction_fields_read_or_used: PASS (False)
- v5_clearly_labeled_active_going_forward: PASS (speed_v5_new_source_supplement)
- v4_retained_as_baseline_legacy: PASS (baseline_retention_rule)
- downstream_refresh_requirements_explicit: PASS (8)

## Outputs

- `work\output\roadway_graph\review\current\active_speed_context_policy\active_speed_context_policy_summary.csv`
- `work\output\roadway_graph\review\current\active_speed_context_policy\active_speed_context_policy_rules.csv`
- `work\output\roadway_graph\review\current\active_speed_context_policy\active_speed_context_v4_v5_comparison.csv`
- `work\output\roadway_graph\review\current\active_speed_context_policy\active_speed_context_conflict_summary.csv`
- `work\output\roadway_graph\review\current\active_speed_context_policy\active_speed_context_downstream_refresh_requirements.csv`
- `work\output\roadway_graph\review\current\active_speed_context_policy\active_speed_context_policy_findings.md`
- `work\output\roadway_graph\review\current\active_speed_context_policy\active_speed_context_policy_manifest.json`
