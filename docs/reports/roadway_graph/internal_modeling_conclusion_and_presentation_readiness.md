# Internal Modeling Conclusion And Presentation Readiness

**Status: INTERNAL TECHNICAL REVIEW ONLY.** This memo synthesizes the active v2/v5 simplified internal crash-count model and active negative-binomial stabilization diagnostic. It does not fit new models, compute rates, create predictions, rank signals, make causal claims, describe safety performance, use risk/danger language, make policy claims, update stakeholder report conclusions, or recommend downstream functional area distances.

## Modeling Question

Can assigned crash counts be modeled as a function of distance window, access density, speed context, and signal-relative direction after accounting for estimated exposure?

Current active answer for internal technical review: yes, as an exploratory association model using the active v2/v5 inputs. The usable internal model remains a Poisson-family count model with overdispersion-aware inference. The output is not ready for stakeholder findings.

## Active Inputs

The current internal modeling baseline is now the active v2/v5 rerun:

- Speed context: active speed v5 new-source supplement.
- Exposure policy: active AADT v2 direction-factor denominator with bidirectional fallback where `DIRECTION_FACTOR` is null.
- Model input: denominator-ready signal-direction-window rows from the active modeling-readiness matrix.
- Prior v1/v4 model packages are retained as baseline/history only.

The active model uses the existing active estimated exposure offset. No additional `DIRECTION_FACTOR` is applied in the model or this memo.

## Model Unit And Exposure

The model unit is:

`reference_signal_id + signal_relative_direction + analysis_window`

The outcome is:

`assigned_crash_count`

The offset is:

`log_estimated_exposure`

The active estimated exposure uses the approved v2 denominator policy. Valid `DIRECTION_FACTOR` is applied where available, null factors use the bidirectional fallback, and invalid factors remain flagged. The model uses denominator-ready signal-direction-window rows only and does not include rows beyond 2,500 ft.

## Active Model Sequence Summary

The active simplified internal model package modeled 2,967 denominator-ready signal-direction-window rows and 12,414 assigned crashes. The selected active model remains:

`S3_access_interaction_speed_simplified`

The active sequence result is:

- Access-window interaction remains useful under active v2/v5. The scaled-Poisson AIC change for `S2_access_interaction` versus `S1_window_direction` is -26.269.
- Simplified speed remains useful under active v2/v5. The scaled-Poisson AIC change for `S3_access_interaction_speed_simplified` versus `S2_access_interaction` is -16.439.
- Both additions are weaker than the prior baseline v1/v4 model, where the corresponding AIC changes were -36.752 and -59.901.
- Overdispersion remains, so conventional Poisson standard errors should not be used alone.

## Preferred Internal Model

Current preferred active internal model:

`S3_access_interaction_speed_simplified`

Preferred active internal model family:

scaled and cluster-robust Poisson primary, with fixed-alpha negative-binomial sensitivity.

The model is ready for internal technical review only. It is not ready for stakeholder interpretation.

## Negative-Binomial Conclusion

Negative binomial remains theoretically relevant because the crash-count model is overdispersed. The active v2/v5 stabilization diagnostic improved estimated-alpha NB behavior compared with the baseline package, but it did not stabilize the selected full speed model.

Active estimated-alpha NB result:

- `NB0_exposure_only_active` is interpretable.
- `NB3_access_interaction_no_speed_active` is interpretable.
- `NB1_window_direction_active`, `NB2_add_access_no_interaction_active`, and `NB4_access_interaction_speed_simplified_active` remain unstable or have incomplete covariance.
- `NB4_access_interaction_speed_simplified_active` fit but did not converge and is not interpretable.

Fixed-alpha NB GLM fits succeeded at alpha 0.25, 0.5, 1.0, and 2.0. They support the broad access-window interaction and simplified speed additions as sensitivity evidence only. They do not replace robust/scaled Poisson because alpha is imposed rather than stably estimated.

Active readiness decision:

`active_robust_poisson_primary_nb_sensitivity`

## Stable Internal Patterns

The active internal modeling packages support these cautious technical patterns:

- Access-density association appears to differ by distance window.
- Simplified speed context improves exploratory model fit, though less strongly than in the baseline v1/v4 model.
- Signal-relative upstream/downstream direction alone appears less central than access/window/speed context in this model sequence.

These are exploratory associations. They are not causal findings, safety-performance findings, risk findings, signal rankings, policy findings, or distance recommendations.

## Internally Presentable Artifacts

The following active artifacts can be shown in an internal technical review:

- active simplified model diagnostics
- active selected-model coefficients and IRRs
- active access interaction and speed sensitivity summaries
- active NB stabilization summary
- active model-family readiness table
- active blocked-claims table

Existing model presentation figures under `docs/reports/roadway_graph/modeling_figures/` were created before the active v2/v5 model refresh. Treat them as baseline/historical visual references until they are regenerated from active outputs.

## Blocked From Stakeholder Findings

Do not present the following as stakeholder findings:

- model coefficients as final findings
- risk, danger, or safety-performance language
- signal rankings
- causal claims
- policy guidance
- downstream functional area distance recommendations
- predictions for policy use

## Recommended Next Step

Hold an internal technical review using the active v2/v5 S3 diagnostics and active NB stabilization package. Regenerate the internal model figures from active outputs before using visuals in review. After that review, decide whether the stakeholder report should include only a high-level modeling-status paragraph, with no coefficient interpretation and no model figure.

## Supporting Outputs

Active supporting tables live under:

`work/output/roadway_graph/analysis/current/internal_modeling_conclusion_readiness_active/`

Created active outputs:

- `active_internal_modeling_conclusion_summary.csv`
- `active_model_family_readiness_table.csv`
- `active_presentable_internal_artifacts_table.csv`
- `active_blocked_stakeholder_claims_table.csv`
- `active_recommended_next_steps_modeling.csv`
- `active_internal_modeling_conclusion_manifest.json`

The prior support folder, `work/output/roadway_graph/analysis/current/internal_modeling_conclusion_readiness/`, is retained as baseline/history.
