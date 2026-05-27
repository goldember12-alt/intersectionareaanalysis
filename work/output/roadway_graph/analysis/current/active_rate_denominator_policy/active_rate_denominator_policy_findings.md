# Active Rate Denominator Policy Findings

## Bounded Question

Promote AADT direction-factor v2 to the active descriptive exposure denominator policy without overwriting v1 outputs or rerunning rates/models.

## Active Policy

`v2_direction_factor_with_bidirectional_fallback` is active going forward.

- Valid `DIRECTION_FACTOR`: apply in the approved descriptive exposure denominator context.
- Null `DIRECTION_FACTOR`: use v1 bidirectional AADT fallback.
- Invalid `DIRECTION_FACTOR`: flag for review.
- V1 bidirectional AADT outputs remain baseline/legacy comparison artifacts.
- Source documentation is still needed to fully confirm `DIRECTION_FACTOR` semantics.

## Policy Summary

- Units evaluated: 2967
- Units with factor applied: 2751
- Units using null-factor bidirectional fallback: 594
- Units with invalid factor: 0
- V1 exposure: 12162169675.11
- V2 adjusted exposure: 7108955359.7
- Exposure ratio v2/v1: 0.584514
- V1 aggregate descriptive rate per million: 1.020706
- V2 aggregate descriptive rate per million: 1.746248
- Rate ratio v2/v1: 1.710824

## Downstream Refresh Needed

- `descriptive_crash_rate_prototype` v2 active denominator outputs.
- `descriptive_crash_rate_suppression_review` using v2 active denominator outputs.
- Context relationship rate figures using v2.
- Modeling readiness offset/exposure update.
- Simplified internal model v2 only if speed/AADT context changes are accepted.

## QA

- v1_outputs_overwritten: PASS (unchanged)
- rates_or_models_silently_changed: PASS (no_rate_or_model_outputs_written)
- v2_policy_clear_active: PASS (active_policy_output_and_docs)
- null_factor_fallback_documented: PASS (rule_written)
- source_documentation_caveat_preserved: PASS (rule_written)
- crash_direction_fields_read_or_used: PASS (False)

## Outputs

- `work\output\roadway_graph\analysis\current\active_rate_denominator_policy\active_rate_denominator_policy_summary.csv`
- `work\output\roadway_graph\analysis\current\active_rate_denominator_policy\active_rate_denominator_policy_rules.csv`
- `work\output\roadway_graph\analysis\current\active_rate_denominator_policy\active_rate_denominator_policy_comparison_v1_v2.csv`
- `work\output\roadway_graph\analysis\current\active_rate_denominator_policy\active_rate_denominator_policy_findings.md`
- `work\output\roadway_graph\analysis\current\active_rate_denominator_policy\active_rate_denominator_policy_manifest.json`
