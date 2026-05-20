# Internal Model Technical Review Memo

**Status: INTERNAL TECHNICAL REVIEW ONLY.** This memo translates the category-simplified crash-count model outputs into a cautious technical review record. It does not fit new models, create predictions for policy use, make causal claims, rank signals, describe safety performance, use risk or danger language, or recommend downstream functional area distances.

## Bounded Question

Can the existing category-simplified signal-direction-window crash-count model package support internal technical review of exploratory associations between assigned crash counts, distance window, local access density, speed context, and signal-relative direction after accounting for estimated exposure?

## Executive Summary

`S3_access_interaction_speed_simplified` is ready for **internal technical review only**. The recommended internal review framing is scaled Poisson and cluster-robust Poisson inference, with fixed-alpha negative-binomial results retained as sensitivity evidence only.

The simplified package modeled 2,967 denominator-ready signal-direction-window rows and 12,414 assigned crashes. It preserved 255 excluded rows outside the modeled denominator-ready universe. Speed categories were simplified by merging 50-59 mph and 60+ mph into `50+ mph`; missing/review speed remained an explicit category. After simplification, remaining sparse categories were 0.

Stakeholder interpretation remains blocked. The model is not ready for policy findings, signal ranking, safety-performance language, risk/danger language, causal interpretation, predictions for policy use, or downstream functional area distance recommendations.

## Model Unit And Outcome

The model unit is:

`reference_signal_id + signal_relative_direction + analysis_window`

The outcome is:

`assigned_crash_count`

The offset is:

`log_estimated_exposure`

The current exposure concept is:

`estimated_exposure = length_weighted_stable_AADT x represented_length_miles x 1,096 days`

Only denominator-ready signal-direction-window rows were modeled. Denominator-ready rows require positive represented length, positive stable AADT, and stable AADT coverage share at or above the current 0.80 threshold. Rows beyond 2,500 ft were not included, crash direction fields were not used, and `DIRECTION_FACTOR` was not applied.

Exposure remains estimated and provisional. AADT is still bidirectional/provisional, and the source directionality audit found mixed or unclear directionality values rather than explicit opposing travel-direction labels.

## Model Sequence

The simplified package followed the internal S0-S4 sequence:

- `S0_exposure_only`: exposure offset only.
- `S1_window_direction`: adds analysis window and signal-relative direction.
- `S2_access_interaction`: adds the analysis-window by local-access-density interaction.
- `S3_access_interaction_speed_simplified`: adds simplified speed context.
- `S4_speed_sensitivity_no_missing`: stable-speed-only sensitivity row set.

`S3_access_interaction_speed_simplified` is preferred for internal review because the access interaction remained useful after simplification and adding simplified speed improved fit while avoiding the prior sparse 60+ mph category. The scaled-Poisson AIC comparison for `S2_access_interaction` versus `S1_window_direction` was -36.752. The scaled-Poisson AIC comparison for `S3_access_interaction_speed_simplified` versus `S2_access_interaction` was -59.901.

## Diagnostics Summary

Overdispersion remains present. For the selected S3 model, the Pearson overdispersion ratio is 7.680, so conventional Poisson standard errors should not be used alone.

Scaled Poisson inference is available and is the main internal sequence-comparison basis. Cluster-robust Poisson inference by `reference_signal_id` is also available for review and should be used alongside scaled inference when discussing coefficient stability.

Fixed-alpha negative-binomial sensitivity fits at alpha 0.25, 0.5, 1.0, and 2.0 converged for S3, but they remain sensitivity evidence only. They do not replace a stable estimated-alpha negative-binomial model and do not make the model stakeholder-ready.

The simplified package reports convergence for the selected model families used in the internal review package. The sparse-category cleanup passed after merging 50-59 mph and 60+ mph into `50+ mph`, while preserving missing/review speed as an explicit category.

Supporting diagnostics are in:

`work/output/roadway_graph/analysis/current/crash_count_internal_model_review/internal_model_diagnostic_summary.csv`

## Access Interaction Interpretation

The access interaction should be interpreted only as exploratory association. The model supports deeper internal review of whether the association between local access density and assigned crash counts differs by analysis window after accounting for estimated exposure and the other model terms.

This aligns with the descriptive pattern that the 0-1,000 ft window is less monotonic across access-density categories, while the 1,000-2,500 ft window appears more monotonic after the zero-access group. The coefficient table should not be summarized as a simple access-density effect because interaction terms depend on the reference window and reference access category.

Selected IRRs and confidence intervals are preserved for review in:

`work/output/roadway_graph/analysis/current/crash_count_internal_model_review/internal_model_access_interaction_interpretation_table.csv`

Those IRRs are conditional model terms. They are not causal effects, they are not signal rankings, and they do not support policy or distance guidance.

## Speed Interpretation

Adding simplified speed improved scaled-Poisson fit for S3 relative to S2. Speed remains roadway context, not causal evidence. Missing/review speed was retained as an explicit category rather than dropped or imputed.

The `50+ mph` merge was used to avoid sparse-category instability by combining the prior 50-59 mph and 60+ mph categories. This improves technical stability for internal review, but it also means the selected model does not distinguish 50-59 mph from 60+ mph.

Selected speed IRRs and confidence intervals are preserved for review in:

`work/output/roadway_graph/analysis/current/crash_count_internal_model_review/internal_model_speed_sensitivity_interpretation_table.csv`

## AADT And Exposure Caveats

AADT remains bidirectional/provisional. `DIRECTION_FACTOR` was not applied.

The AADT direction-factor audit found that source `DIRECTIONALITY` values are `Combined`, `Single`, and missing rather than explicit opposing travel-direction labels. It also found that applying `DIRECTION_FACTOR` as a diagnostic denominator alternative would generally reduce estimated exposure, but that diagnostic result is not validated as the correct directional exposure method.

AADT year flags remain limitations. Mixed AADT year and outside-period AADT year conditions should remain visible in internal review rather than being silently suppressed or treated as solved.

Because exposure is estimated, the model should be described as using an estimated exposure offset. It should not be described as final directional exposure or as policy-ready directional evidence.

## Blocked From Stakeholder Use

The following remain blocked:

- policy findings
- safety-performance rankings
- risk or danger language
- signal ranking
- downstream functional area distance recommendations
- causal claims
- predictions for policy use
- fixed distance-band model interpretation

Allowed language is limited to internal technical review, exploratory association, provisional estimated exposure, and higher/lower modeled crash counts after accounting for estimated exposure.

## Supporting Review Outputs

Supporting outputs live under:

`work/output/roadway_graph/analysis/current/crash_count_internal_model_review/`

Created review outputs:

- `internal_model_review_summary.csv`
- `internal_model_selected_coefficients.csv`
- `internal_model_selected_irrs.csv`
- `internal_model_diagnostic_summary.csv`
- `internal_model_access_interaction_interpretation_table.csv`
- `internal_model_speed_sensitivity_interpretation_table.csv`
- `internal_model_limitations_table.csv`
- `internal_model_language_guardrails.csv`
- `internal_model_next_steps.csv`
- `internal_model_review_manifest.json`

## QA Checks

This review package did not fit new models. It reformatted and summarized already-available outputs from the simplified model package and related diagnostics.

QA status:

- No new models were fit.
- No crash direction fields were used.
- `DIRECTION_FACTOR` was not applied.
- No distance-band models were fit.
- Source, context, and assignment data were not altered.
- Stakeholder interpretation remains blocked.
- The memo is labeled internal technical review only.

## Recommended Next Steps

1. Complete technical review of this memo, the selected coefficient table, and the diagnostic summary.
2. Optionally create coefficient visualizations for internal review only, using the same guardrail language.
3. Consider distance-band sensitivity only after this memo is reviewed and an explicit bounded task authorizes that sparser grain.
4. Continue AADT directionality and `DIRECTION_FACTOR` validation before any stakeholder-facing model interpretation.
5. Draft any stakeholder report language only after method and language approval.
