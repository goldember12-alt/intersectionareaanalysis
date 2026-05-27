# Roadway Graph Rate Assumption Approval V2

**Status: CURRENT ACTIVE DENOMINATOR ASSUMPTION APPROVAL.** This memo promotes AADT direction-factor v2 to the active descriptive exposure denominator policy. It does not overwrite v1 outputs, rerun rates, fit models, make causal claims, rank safety performance, create policy guidance, or recommend downstream functional-area distances.

## Bounded Question

Should the descriptive exposure denominator use `DIRECTION_FACTOR` where valid while preserving v1 bidirectional AADT treatment where the factor is null?

## Inputs Reviewed

- `docs/design/roadway_graph_rate_denominator_policy.md`
- `docs/design/roadway_graph_rate_assumption_approval_v1.md`
- `work/output/roadway_graph/analysis/current/aadt_direction_factor_audit/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_direction_factor_sensitivity/`
- `work/output/roadway_graph/analysis/current/active_rate_denominator_policy/`

No crash direction fields were read or used.

## Authorization Decision

Decision:

`approved_active_denominator_policy_v2_direction_factor_with_bidirectional_fallback`

Active denominator policy:

`v2_direction_factor_with_bidirectional_fallback`

V1 status:

`baseline_legacy_comparison`

## Approved Rules

- Apply valid `DIRECTION_FACTOR` values in the approved descriptive exposure denominator context.
- Use v1 bidirectional AADT fallback where `DIRECTION_FACTOR` is null.
- Flag invalid `DIRECTION_FACTOR` values for review.
- Do not apply `DIRECTION_FACTOR` outside the approved denominator context.
- Do not overwrite or delete v1 outputs.
- Preserve source-documentation caveat until field semantics are fully confirmed.

## Promotion Evidence

The v2 sensitivity package evaluated the same 2,967 denominator-ready window-grain units used by v1.

- Units evaluated: 2,967.
- Units with factor applied: 2,751.
- Units using null-factor bidirectional fallback: 594.
- Units with invalid factor: 0.
- V1 exposure: 12,162,169,675.11.
- V2 adjusted exposure: 7,108,955,359.70.
- Exposure ratio v2/v1: 0.584514.
- V1 aggregate descriptive rate per million: 1.020706.
- V2 aggregate descriptive rate per million: 1.746248.
- Rate ratio v2/v1: 1.710824.

## Remaining Caveat

Source documentation is still needed to fully confirm `DIRECTION_FACTOR` semantics. The policy is active because it is inclusive of v1 and uses available direction-factor evidence where present, not because source semantics are fully closed.

## Required Boundaries

- No crash direction fields.
- No fixed-band or raw-bin rate authorization.
- No regression, predictive modeling, or causal interpretation from this approval alone.
- No safety-performance, risk, danger, or policy ranking.
- No downstream functional-area distance recommendation.
- No `DIRECTION_FACTOR` use outside approved descriptive exposure denominator outputs.

## Downstream Refresh Needed

- `descriptive_crash_rate_prototype` v2 active denominator outputs.
- `descriptive_crash_rate_suppression_review` v2 active denominator outputs.
- Context relationship rate figures using v2.
- Modeling readiness exposure/offset update.
- Simplified internal model v2 only if speed/AADT context changes are accepted.

## Machine-Readable Outputs

Active policy outputs live under:

`work/output/roadway_graph/analysis/current/active_rate_denominator_policy/`

Created outputs:

- `active_rate_denominator_policy_summary.csv`
- `active_rate_denominator_policy_rules.csv`
- `active_rate_denominator_policy_comparison_v1_v2.csv`
- `active_rate_denominator_policy_findings.md`
- `active_rate_denominator_policy_manifest.json`

