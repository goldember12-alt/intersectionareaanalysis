# Roadway Graph Rate Denominator Policy

**Status: CURRENT ACTIVE DENOMINATOR POLICY.** AADT direction-factor v2 is now the active descriptive exposure denominator policy for future rate refreshes. The original bidirectional-AADT v1 policy is retained as a baseline and legacy comparison. This memo does not itself rerun rates, fit models, create causal claims, rank safety performance, make policy recommendations, or recommend downstream functional-area distances.

## Bounded Question

What denominator assumptions must be documented before the accepted 0-2,500 ft roadway-derived directional-bin context universe can support a first descriptive crash-rate prototype?

## Inputs Reviewed

- `docs/design/roadway_graph_rate_and_modeling_readiness_plan.md`
- `work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table/directional_crash_context.csv`
- `work/output/roadway_graph/tables/current/crash_oriented_segment_bin_assignment.csv`, read only for `crash_id`, `CRASH_DT`, and `CRASH_YEAR`
- `work/output/roadway_graph/review/current/aadt_context_join_v3_identity_route_measure/aadt_context_v3_findings.md`
- `work/output/roadway_graph/review/current/aadt_context_join_v3_identity_route_measure/aadt_context_v3_manifest.json`

Crash direction fields were not read or used.

## Recommended First Rate Prototype Unit

Use:

`reference_signal_id + signal_relative_direction + analysis_window`

Windows:

- `high_priority_0_1000ft`
- `sensitivity_1000_2500ft`

This window grain is the first recommended rate-prototype unit because it preserves signal-relative upstream/downstream interpretation while avoiding raw 50-ft bin instability. Fixed distance-band rates should wait until the window-grain denominator behavior is reviewed.

## Numerator Definition

The numerator for the first prototype should be accepted assigned crashes only:

- Use only accepted assigned crashes in the current 0-2,500 ft roadway-derived directional context universe.
- Exclude ambiguous and unresolved crashes.
- Do not use crash direction fields.
- Do not use context fields to redefine upstream/downstream.
- Crash-level `AREA_TYPE` may be summarized as crash context, but it must not be treated as roadway-level urban/rural geography.

Current accepted numerator checks:

- Accepted assigned crashes: 13,216.
- 0-1,000 ft crashes: 9,170.
- 1,000-2,500 ft crashes: 4,046.

## Denominator Definition

The future VMT-like exposure concept is:

`AADT x represented length x crash study period`

This memo defines the concept and required fields only. It does not compute the final denominator or any rate.

Required denominator fields:

- `represented_length_miles`
- stable AADT value
- stable AADT coverage share
- crash study period days or years
- directional AADT handling rule

Use represented length from the analysis-unit readiness outputs. Preserve truncated-bin lengths where available and convert feet to miles as:

`represented_length_miles = represented_length_ft / 5280`

Do not assume each bin is exactly 50 ft unless a later audit proves that assumption is appropriate for the selected unit.

## Crash Study Period

The policy-support audit found crash dates for the accepted assigned-crash universe by matching `directional_crash_context.csv` crash IDs to `work/output/roadway_graph/tables/current/crash_oriented_segment_bin_assignment.csv`.

Crash study-period audit:

- Accepted assigned crashes matched to date source: 13,216.
- Earliest crash date: 2022-01-01.
- Latest crash date: 2024-12-31.
- Missing crash date count: 0.
- Year distribution: 4,244 in 2022, 4,506 in 2023, and 4,466 in 2024.
- Candidate study period: 2022-2024 calendar years.

Status: crash dates are available, but the study period is not yet authorized for rate calculation. Before rates are computed, a later review must confirm source filters, complete-year handling, denominator period alignment, and AADT year treatment.

## Directional AADT Policy

Active policy:

`v2_direction_factor_with_bidirectional_fallback`

Rules:

- Where `DIRECTION_FACTOR` is valid, apply it in the approved descriptive exposure denominator context.
- Where `DIRECTION_FACTOR` is null, fall back to the v1 bidirectional AADT treatment.
- Where `DIRECTION_FACTOR` is invalid, flag the row for review and preserve transparent fallback handling.
- Do not apply `DIRECTION_FACTOR` outside the approved denominator context.
- Preserve v1 bidirectional-AADT outputs as baseline and legacy comparison artifacts.

Rationale:

V2 is inclusive of v1. It uses available direction-factor information where present and preserves the v1 bidirectional treatment where the factor is absent. Invalid factors remain visible as review flags. Source documentation is still needed to fully confirm field semantics, but v2 is the best active policy for future descriptive denominator refreshes because it uses available source evidence without dropping null-factor units.

### AADT Direction-Factor Audit Result

The read-only audit `src/active/roadway_graph/aadt_direction_factor_audit.py` now documents the source `DIRECTION_FACTOR` and `DIRECTIONALITY` fields without changing rate outputs.

Audit output:

`work/output/roadway_graph/analysis/current/aadt_direction_factor_audit/`

Current audit result:

- source `DIRECTIONALITY` values are `Combined`, `Single`, and missing, rather than explicit opposing travel-direction labels
- `DIRECTION_FACTOR` is populated on the `Combined` and `Single` source rows and is missing on rows with missing `DIRECTIONALITY`
- stable directional-bin AADT context mostly inherits `Combined`
- applying `DIRECTION_FACTOR` as a diagnostic denominator alternative would generally reduce estimated exposure, but this is not yet validated as the correct directional exposure method
- outside-period and mixed AADT year rows should remain visible as flags, not automatic suppression rules

Policy implication:

Promote v2 to the active denominator policy for future descriptive rate refreshes. Do not overwrite v1 outputs. Treat v1 as the baseline comparison. Existing v1-derived outputs remain historical/legacy until refreshed under v2.

### AADT Direction-Factor V2 Promotion

The read-only sensitivity module `src/active/roadway_graph/descriptive_crash_rate_direction_factor_sensitivity.py` evaluated v2 against v1 at the approved window grain.

Active policy output:

`work/output/roadway_graph/analysis/current/active_rate_denominator_policy/`

Promotion result:

- Units evaluated: 2,967.
- Units with valid factor applied: 2,751.
- Units using null-factor bidirectional fallback: 594.
- Units with invalid factor: 0.
- V1 exposure: 12,162,169,675.11.
- V2 adjusted exposure: 7,108,955,359.70.
- Exposure ratio v2/v1: 0.584514.
- V1 aggregate descriptive rate per million: 1.020706.
- V2 aggregate descriptive rate per million: 1.746248.
- Rate ratio v2/v1: 1.710824.

Downstream outputs that need a v2 refresh before they are treated as current:

- descriptive crash-rate prototype v2 active denominator outputs
- rate suppression review v2 active denominator outputs
- context relationship rate figures using v2
- modeling readiness exposure/offset update
- simplified internal model v2 only if speed/AADT context changes are accepted

## Missing Or Review AADT

Missing or review AADT must not be silently included in denominators.

Prototype v1 treatment:

- Include only denominator-ready units in future rate rows.
- Exclude units below the denominator-ready threshold from future rate rows.
- Report excluded crashes.
- Report excluded bins.
- Report denominator coverage.
- Do not impute AADT.
- Keep excluded rows available as non-rate descriptive context if needed.

Current window-grain readiness:

- Candidate window units: 3,222.
- Denominator-ready window units: 2,967.
- Assigned crashes retained in denominator-ready window units: 12,414 of 13,216.
- Assigned crashes in not-denominator-ready window units: 802.

## Denominator Readiness Thresholds

Prototype v1 denominator-ready requirements:

- Stable AADT coverage share >= 0.80.
- Represented length > 0.
- Positive nonzero stable AADT.
- Known and approved crash study period.
- Missing/review AADT excluded from denominator values.

Warning flags:

- Low denominator warning: represented length below the configured review threshold or no stable AADT.
- Low crash-count warning: assigned crash count below the configured review threshold.
- Coverage warning: stable AADT coverage below 0.80.
- Study-period warning: crash period not yet approved.

These are QA and suppression flags, not data-cleaning shortcuts.

## Exposure Duplication Policy

The exposure readiness audit found:

- Duplicate source-bin keys across reference signals: 0.
- Unique source-bin keys audited: 78,292.

Interpretation:

Signal-relative duplicate exposure appears low under the available `source_bin_key` audit. This is favorable for the first signal-centered prototype, but it does not eliminate the need for explicit de-duplication review before corridor-level or systemwide rates. Future corridor/systemwide outputs must define a de-duplicated physical exposure key before treating exposure as total roadway length.

## Allowed Output Language

Allowed, after denominator gates are satisfied:

- descriptive rate prototype
- AADT-normalized descriptive comparison
- denominator-ready unit
- exposure denominator
- uncertainty interval
- provisional
- readiness-gated

Avoid:

- dangerous
- risky
- safety performance
- policy recommendation
- causal effect
- expected crashes
- final downstream functional area recommendation

## Machine-Readable Policy Outputs

Policy-support outputs live under:

`work/output/roadway_graph/analysis/current/rate_denominator_policy/`

Created outputs:

- `rate_denominator_policy_summary.csv`
- `rate_denominator_candidate_unit_counts.csv`
- `crash_study_period_audit.csv`
- `rate_denominator_policy_spec.csv`
- `rate_denominator_policy_qa.csv`
- `rate_denominator_policy_findings.md`
- `rate_denominator_policy_manifest.json`

`rate_denominator_policy_spec.csv` is the machine-readable policy/spec table. It records the prototype unit, numerator policy, denominator concept, AADT handling, missing-context treatment, warning rules, duplication policy, and language constraints.

## Recommended Next Module

`src/active/roadway_graph/descriptive_crash_rate_prototype.py` has been implemented after the separate assumption-approval step in `docs/design/roadway_graph_rate_assumption_approval_v1.md`.

Prototype outputs:

`work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/`

The prototype remains bounded to `reference_signal_id + signal_relative_direction + analysis_window`. It does not compute raw 50-ft bin rates, fixed distance-band rates, models, causal claims, safety-performance rankings, policy guidance, or downstream functional-area distance recommendations.
