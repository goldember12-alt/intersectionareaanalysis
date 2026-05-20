# Roadway Graph Rate Assumption Approval V1

**Status: ASSUMPTION APPROVAL FOR A FUTURE DESCRIPTIVE RATE PROTOTYPE.** This memo approves bounded denominator assumptions for prototype v1. It does not compute crash rates, AADT-normalized comparisons, regressions, predictive models, causal claims, safety-performance rankings, danger/risk rankings, policy guidance, or downstream functional area distance recommendations.

## Bounded Question

Are the numerator period, AADT-year handling, directional AADT treatment, and suppression flags sufficiently specified to authorize a first descriptive rate prototype?

## Inputs Reviewed

- `docs/design/roadway_graph_rate_denominator_policy.md`
- `work/output/roadway_graph/analysis/current/rate_denominator_policy/`
- `work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table/directional_bin_context.csv`
- `work/output/roadway_graph/review/current/aadt_context_join_v3_identity_route_measure/`

No crash direction fields were read or used.

## Authorization Decision

Decision:

`approved_for_descriptive_rate_prototype_v1`

Authorized next module:

`src/active/roadway_graph/descriptive_crash_rate_prototype.py`

The authorization is limited to a provisional descriptive rate prototype at:

`reference_signal_id + signal_relative_direction + analysis_window`

This approval does not authorize fixed-band rates, raw 50-ft bin rates, regression models, causal language, safety-performance rankings, policy claims, or downstream functional area distance recommendations.

## Crash Study Period

The accepted numerator period for descriptive rate prototype v1 is:

`2022-01-01` through `2024-12-31`

Study period:

- Days: 1,096.
- Years: 3.000684 using days / 365.25.
- Accepted assigned crashes: 13,216.
- Missing crash dates: 0.
- 2022 crashes: 4,244.
- 2023 crashes: 4,506.
- 2024 crashes: 4,466.

The observed crash dates match the expected 2022-2024 period, so the numerator period is accepted for prototype v1.

## AADT Year Alignment

Recommendation:

`approved_with_limitation`

Stable AADT bins are concentrated enough to proceed with a provisional descriptive prototype, but AADT-year variation must be preserved as a limitation flag.

Stable AADT bins by year-period status:

- Inside crash period, 2022-2024: 98,423 stable AADT bins.
- Before crash period: 7,787 stable AADT bins.
- After crash period: 0 stable AADT bins.
- Missing AADT year among stable AADT bins: 0.

Major stable AADT years:

- 2022: 1,287 stable AADT bins.
- 2023: 1,027 stable AADT bins.
- 2024: 96,109 stable AADT bins.

Window-grain denominator-ready unit alignment:

- Denominator-ready units with dominant AADT year inside 2022-2024: 2,760.
- Denominator-ready units with dominant AADT year outside 2022-2024: 207.
- Denominator-ready units with mixed stable AADT years: 362.
- Denominator-ready units with positive AADT: 2,967.

Interpretation:

Most denominator-ready exposure is aligned with the crash-period years, especially 2024. Older AADT years remain in a smaller part of the denominator-ready universe and should be flagged, not silently excluded, for prototype v1 unless later review requires stricter filtering.

## Directional AADT Assumption

Recommendation:

`approved_bidirectional_aadt_for_prototype_v1`

`DIRECTION_FACTOR` is present in the context data, but it is not validated for prototype v1 and must not be applied yet.

Prototype v1 will use available stable AADT as bidirectional exposure for each signal-relative directional view. This is acceptable only for a provisional descriptive rate prototype because it is simple, transparent, and avoids introducing an unvalidated directional split.

The subsequent read-only AADT direction-factor audit is stored under:

`work/output/roadway_graph/analysis/current/aadt_direction_factor_audit/`

That audit found source `DIRECTIONALITY` values of `Combined`, `Single`, and missing, with no explicit opposing travel-direction labels. It also found that a diagnostic `DIRECTION_FACTOR` adjustment would generally reduce estimated exposure. Because source definitions and paired route/measure behavior still need validation, prototype v1 remains under the bidirectional AADT assumption and `DIRECTION_FACTOR` remains unapplied.

Required limitation language:

- AADT is not directionally adjusted in prototype v1.
- Signal-relative upstream/downstream views use the same stable AADT context where applicable.
- Prototype v1 rates must not be interpreted as final directional exposure or policy-ready directional safety evidence.
- Future work may validate `DIRECTION_FACTOR`, source directionality, or another directional exposure method.

## Suppression And Flag Rules

Prototype v1 rate rows must include only denominator-ready units.

Required denominator eligibility rules:

- `reference_signal_id + signal_relative_direction + analysis_window` grain only.
- `stable_aadt_coverage_share >= 0.80`.
- `represented_length_miles > 0`.
- positive nonzero stable AADT.
- study period known and equal to 2022-2024.
- missing/review AADT excluded from denominator values.
- excluded crashes and bins reported.
- no AADT imputation.

Required flags:

- `low_crash_count_flag`: `assigned_crash_count < 3`.
- `zero_crash_unit_flag`: `assigned_crash_count == 0`.
- `low_aadt_coverage_flag`: `stable_aadt_coverage_share < 0.80`.
- `mixed_aadt_year_flag`: unit contains multiple stable AADT years.
- `outside_crash_period_aadt_year_flag`: dominant or only AADT year outside 2022-2024.
- `bidirectional_aadt_assumption_flag`: true for all prototype v1 rate rows.
- `denominator_ready_flag`: true only when all denominator eligibility rules pass.

If a later prototype computes exposure values, it should also add a low-exposure flag before presenting rate values.

## Required Prototype Boundaries

The next module may compute a descriptive rate prototype only within these boundaries:

- no crash direction fields
- no >2,500 ft rows
- no missing/review AADT in denominators
- no AADT imputation
- no `DIRECTION_FACTOR` application
- no regression or predictive modeling
- no causal claims
- no danger/risk or safety-performance rankings
- no policy recommendations
- no downstream functional area distance recommendations

## Machine-Readable Outputs

Assumption approval outputs live under:

`work/output/roadway_graph/analysis/current/rate_assumption_approval_v1/`

Created outputs:

- `rate_assumption_approval_summary.csv`
- `crash_study_period_approval.csv`
- `aadt_year_alignment_audit.csv`
- `denominator_rule_spec_v1.csv`
- `rate_prototype_authorization_decision.csv`
- `rate_assumption_approval_qa.csv`
- `rate_assumption_approval_findings.md`
- `rate_assumption_approval_manifest.json`

## Next Step

Implement `src/active/roadway_graph/descriptive_crash_rate_prototype.py` next, limited to the approved window-grain descriptive prototype and carrying all denominator, AADT-year, directional-AADT, low-count, and eligibility flags defined here.
