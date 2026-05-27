# Internal Model Technical Review Memo

**Status: INTERNAL TECHNICAL REVIEW ONLY.** This memo translates the active v2/v5 category-simplified crash-count model outputs into a cautious technical review record. It does not fit new models, compute new rates, create predictions for policy use, make causal claims, rank signals, describe safety performance, use risk or danger language, update stakeholder report conclusions, or recommend downstream functional area distances.

## Bounded Question

Can the active v2/v5 category-simplified signal-direction-window crash-count model package support internal technical review of exploratory associations between assigned crash counts, distance window, local access density, speed context, and signal-relative direction after accounting for estimated exposure?

## Executive Summary

`S3_access_interaction_speed_simplified` remains the selected active internal model and is ready for **internal technical review only**. The recommended internal review framing remains scaled Poisson and cluster-robust Poisson inference, with fixed-alpha negative-binomial results retained as sensitivity evidence only.

The active simplified package modeled 2,967 denominator-ready signal-direction-window rows and 12,414 assigned crashes. It used active speed v5 context and the active AADT v2 denominator exposure offset. Speed categories were simplified by merging 50-59 mph and 60+ mph into `50+ mph`; missing/review speed remained an explicit category. After simplification, remaining sparse categories were 0.

Stakeholder interpretation remains blocked. The model is not ready for policy findings, signal ranking, safety-performance language, risk/danger language, causal interpretation, predictions for policy use, or downstream functional area distance recommendations.

## Model Unit And Outcome

The model unit is:

`reference_signal_id + signal_relative_direction + analysis_window`

The outcome is:

`assigned_crash_count`

The offset is:

`log_estimated_exposure`

The active exposure concept is:

`active estimated exposure = active v2 denominator policy x represented length x 2022-2024 study period`

Only denominator-ready signal-direction-window rows were modeled. Denominator-ready rows require positive represented length, positive stable AADT, and stable AADT coverage share at or above the current 0.80 threshold. Rows beyond 2,500 ft were not included and crash direction fields were not used.

Exposure remains estimated. The active v2 denominator policy applies valid `DIRECTION_FACTOR`, uses bidirectional fallback where `DIRECTION_FACTOR` is null, and flags invalid factors. No additional `DIRECTION_FACTOR` is applied in the model package or this memo. Source-documentation confirmation remains a caveat.

## Model Sequence

The simplified package followed the internal S0-S4 sequence:

- `S0_exposure_only`: exposure offset only.
- `S1_window_direction`: adds analysis window and signal-relative direction.
- `S2_access_interaction`: adds the analysis-window by local-access-density interaction.
- `S3_access_interaction_speed_simplified`: adds simplified speed context.
- `S4_speed_sensitivity_no_missing`: stable-speed-only sensitivity row set.

`S3_access_interaction_speed_simplified` is preferred for internal review because the access interaction remained useful after simplification and adding simplified speed improved fit while avoiding the prior sparse 60+ mph category. Under active v2/v5, the scaled-Poisson AIC comparison for `S2_access_interaction` versus `S1_window_direction` was -26.269. The scaled-Poisson AIC comparison for `S3_access_interaction_speed_simplified` versus `S2_access_interaction` was -16.439. Both additions remain useful, though less strongly than in the prior v1/v4 baseline model.

## Diagnostics Summary

Overdispersion remains present. For the active selected S3 model, the scaled-Poisson Pearson overdispersion ratio is 6.894, so conventional Poisson standard errors should not be used alone.

Scaled Poisson inference is available and is the main internal sequence-comparison basis. Cluster-robust Poisson inference by `reference_signal_id` is also available for review and should be used alongside scaled inference when discussing coefficient stability.

Fixed-alpha negative-binomial sensitivity fits at alpha 0.25, 0.5, 1.0, and 2.0 converged for the active sequence and support the access-window interaction and simplified speed as sensitivity evidence only. Active estimated-alpha NB improved versus baseline for `NB0` and `NB3`, but `NB4_access_interaction_speed_simplified_active` did not converge and had incomplete covariance. Estimated-alpha NB therefore does not replace the active scaled and cluster-robust Poisson framework.

The simplified package reports convergence for the selected model families used in the internal review package. The sparse-category cleanup passed after merging 50-59 mph and 60+ mph into `50+ mph`, while preserving missing/review speed as an explicit category.

Supporting diagnostics are in:

`work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model_active/active_simplified_model_diagnostics.csv`

## Access Interaction Interpretation

The access interaction should be interpreted only as exploratory association. The model supports deeper internal review of whether the association between local access density and assigned crash counts differs by analysis window after accounting for estimated exposure and the other model terms.

This aligns with the descriptive pattern that the 0-1,000 ft window is less monotonic across access-density categories, while the 1,000-2,500 ft window appears more monotonic after the zero-access group. The coefficient table should not be summarized as a simple access-density effect because interaction terms depend on the reference window and reference access category.

Selected IRRs and confidence intervals are preserved for review in:

`work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model_active/active_simplified_access_interaction_summary.csv`

Those IRRs are conditional model terms. They are not causal effects, they are not signal rankings, and they do not support policy or distance guidance.

## Speed Interpretation

Adding simplified speed improved scaled-Poisson fit for S3 relative to S2. Speed remains roadway context, not causal evidence. Missing/review speed was retained as an explicit category rather than dropped or imputed.

The `50+ mph` merge was used to avoid sparse-category instability by combining the prior 50-59 mph and 60+ mph categories. This improves technical stability for internal review, but it also means the selected model does not distinguish 50-59 mph from 60+ mph.

Selected speed summaries are preserved for review in:

`work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model_active/active_simplified_speed_sensitivity_summary.csv`

## AADT And Exposure Caveats

AADT v2 direction-factor denominator policy is active for this model input. `DIRECTION_FACTOR` is not applied again in the model.

The active policy applies valid `DIRECTION_FACTOR`, uses the bidirectional fallback where the factor is null, and flags invalid factors. Source documentation is still needed to fully confirm field semantics, so the exposure should remain labeled estimated exposure.

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

Active supporting model outputs live under:

`work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model_active/`

Active conclusion support outputs live under:

`work/output/roadway_graph/analysis/current/internal_modeling_conclusion_readiness_active/`

The prior `crash_count_internal_model_review/` package is retained as baseline/history unless a later task regenerates that review table package from active outputs.

## QA Checks

This memo update did not fit new models. It summarizes already-available outputs from the active simplified model package and active NB stabilization diagnostic.

QA status:

- No new models were fit.
- No crash direction fields were used.
- No additional `DIRECTION_FACTOR` was applied beyond the active v2 exposure already present in model inputs.
- No distance-band models were fit.
- Source, context, and assignment data were not altered.
- Stakeholder interpretation remains blocked.
- The memo is labeled internal technical review only.

## Recommended Next Steps

1. Complete technical review of this active memo, the active selected coefficient table, the active diagnostics, and the active NB stabilization result.
2. Regenerate internal model figures from active v2/v5 outputs before using visuals in review.
3. Keep fixed-alpha NB as sensitivity evidence and do not promote estimated-alpha NB while active NB4 remains non-interpretable.
4. Continue AADT v2 source-semantics validation before any stakeholder-facing model interpretation.
5. Draft any stakeholder report language only after method and language approval.
