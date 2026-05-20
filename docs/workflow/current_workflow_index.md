# Current Workflow Index

**Status: CURRENT ACTIVE.** This is the short navigation page for the roadway-derived directional context product.

## Start Here

- `active_workflow.md`: current command surface and output contract.
- `roadway_graph_workflow.md`: roadway graph foundation workflow and graph-first methodological guardrails.
- `roadway_graph_directional_context_milestone.md`: current milestone for the full 0-2,500 ft directional-bin context universe.
- `roadway_graph_context_analysis_plan.md`: current workflow plan for the next descriptive analysis outputs.
- `../design/roadway_graph_context_enrichment_plan.md`: design record for access, speed, AADT, and context enrichment.
- `../design/roadway_graph_next_phase_plan.md`: next-phase design plan for descriptive products, stakeholder deliverables, and production hardening.
- `../design/roadway_graph_rate_denominator_policy.md`: first denominator policy and rate-prototype specification memo.
- `../design/roadway_graph_rate_assumption_approval_v1.md`: bounded approval memo for descriptive rate prototype v1 assumptions.
- `../methodology/roadway_graph_methodology.md`: core graph-first methodology.
- `../methodology/overview_methodology.md`: repository-level methodology posture.
- `../methodology/proposal_alignment_growth_plan.md`: controlled proposal-alignment growth path.
- `../reports/roadway_graph/roadway_graph_methodology_limitations_memo.md`: bounded methodology and limitations memo for the accepted table package.
- `../reports/roadway_graph/roadway_graph_figure_inventory_and_specs.md`: figure/table exhibit specifications.
- `../reports/roadway_graph/roadway_graph_report_outline.md`: outline for the roadway-graph report.
- `../reports/roadway_graph/roadway_graph_descriptive_report_draft.md`: first descriptive roadway-graph report draft.
- `../reports/roadway_graph/roadway_graph_figure_index.md`: generated figure index.
- `../reports/roadway_graph/roadway_graph_report_qa.md`: report and figure QA.
- `../reports/roadway_graph/internal_model_technical_review_memo.md`: internal technical review memo for the category-simplified crash-count model.

## Current Product

The current product is the stable roadway-derived 0-2,500 ft directional-bin context universe:

- 0-1,000 ft: high-priority descriptive subset.
- 1,000-2,500 ft: sensitivity subset.
- greater than 2,500 ft: review-only, excluded from the combined table.

Final product outputs live under:

`work/output/roadway_graph/analysis/current/directional_bin_context_table/`

First-stage descriptive summary outputs live under:

`work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries/`

Signal-level review-prioritization outputs live under:

`work/output/roadway_graph/analysis/current/signal_context_review_queue/`

Fixed distance-band profile outputs live under:

`work/output/roadway_graph/analysis/current/directional_context_distance_band_profiles/`

Signal-direction profile outputs live under:

`work/output/roadway_graph/analysis/current/signal_direction_context_profiles/`

Compact stakeholder table-package outputs live under:

`work/output/roadway_graph/analysis/current/stakeholder_context_table_package/`

Exposure/modeling-readiness audit outputs live under:

`work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`

Rate-denominator policy support outputs live under:

`work/output/roadway_graph/analysis/current/rate_denominator_policy/`

Rate-assumption approval v1 outputs live under:

`work/output/roadway_graph/analysis/current/rate_assumption_approval_v1/`

Descriptive crash-rate prototype outputs live under:

`work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/`

Descriptive crash-rate prototype QA outputs live under:

`work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_qa/`

Descriptive crash-rate suppression review outputs live under:

`work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review/`

The combined table joins accepted context layers onto one row per usable directional bin. It includes crash assignment/readiness counts, assigned-crash `AREA_TYPE` context, access context, speed v4 context, AADT v3 context, and explicit roadway urban/rural `source_not_found` fields.

## Active Output Folders

Keep these `current` output folders as the active product and reproducibility/audit surface:

- `work/output/roadway_graph/analysis/current/directional_bin_context_table/`
- `work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries/`
- `work/output/roadway_graph/analysis/current/signal_context_review_queue/`
- `work/output/roadway_graph/analysis/current/directional_context_distance_band_profiles/`
- `work/output/roadway_graph/analysis/current/signal_direction_context_profiles/`
- `work/output/roadway_graph/analysis/current/stakeholder_context_table_package/`
- `work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`
- `work/output/roadway_graph/analysis/current/rate_denominator_policy/`
- `work/output/roadway_graph/analysis/current/rate_assumption_approval_v1/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_qa/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review/`
- `work/output/roadway_graph/analysis/current/crash_directional_assignment_descriptive_summary/`
- `work/output/roadway_graph/review/current/reference_signal_directional_scaffold/`
- `work/output/roadway_graph/review/current/reference_signal_directional_scaffold_qa/`
- `work/output/roadway_graph/review/current/reference_signal_directional_bin_catchments/`
- `work/output/roadway_graph/review/current/crash_directional_catchment_assignment_prototype/`
- `work/output/roadway_graph/review/current/crash_directional_catchment_assignment_qa/`
- `work/output/roadway_graph/review/current/crash_directional_assignment_analysis_readiness/`
- `work/output/roadway_graph/review/current/access_context_join/`
- `work/output/roadway_graph/review/current/roadway_identity_metadata_propagation/`
- `work/output/roadway_graph/review/current/speed_context_join_v4_identity_enriched/`
- `work/output/roadway_graph/review/current/aadt_context_join_v3_identity_route_measure/`
- `work/output/roadway_graph/review/current/urban_rural_source_recovery/`

Supporting source/staging inventories that remain useful for provenance:

- `work/output/roadway_graph/review/current/context_source_inventory/`
- `work/output/roadway_graph/review/current/posted_speed_source_staging/`
- `work/output/roadway_graph/review/current/aadt_source_staging/`

## Archived Material

Superseded docs and one-off audits from the cleanup pass were moved to:

- `docs/archive/20260519_cleanup/`
- `work/archive/20260519_cleanup/`
- `work/output/roadway_graph/review/history/repo_cleanup_20260519/`

Treat archived material as history or comparison evidence only. Do not use archived docs or outputs as current methodology unless a later task explicitly promotes a specific item back into the active workflow.

## Methodological Boundaries

- Crash direction fields are not used.
- Context fields do not redefine upstream/downstream.
- Crash `AREA_TYPE` is crash-level context only.
- Roadway-level urban/rural remains unavailable with `roadway_urban_rural_context_status = source_not_found`.
- Ambiguous and unresolved crashes remain outside the assigned-crash summary universe.
- The table is a prototype descriptive analysis universe, not policy-ready or modeling-ready.

## Next Phase

The next active workflow phase is descriptive analysis from the accepted context table. The first read-only summary module now produces signal-level, signal-direction-window, distance-band, crash-context, access, speed, AADT, urban/rural crash-context, completeness, QA, findings, and manifest outputs without changing scaffold, catchments, crash assignment, or context joins.

The second read-only module produces signal-level and signal-direction-level review-prioritization queues from the accepted summaries. It is a manual review ordering product only, not a danger ranking, model, crash-rate analysis, or policy claim.

The next three read-only modules produce fixed distance-band profiles, signal-direction profiles, and a compact stakeholder table package. They are descriptive table outputs only. They do not create figures, draft a final report, compute crash rates, run models/regressions, or make policy claims.

Report-stage planning docs now live under `../reports/`. They document methodology/limitations, candidate figure specs, and a future report outline. They are planning documents only; no final roadway-graph report or figures have been created.

The first descriptive roadway-graph report draft and static draft figures now live under `../reports/roadway_graph/` and `work/output/roadway_graph/report/current/`. They use accepted descriptive outputs only and do not include crash rates, AADT-normalized comparisons, models, regressions, predictions, or final design recommendations.

The first exposure/modeling-readiness audit now lives under `work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`. It audits denominator coverage, candidate feature-matrix grains, duplicate signal-relative source-bin exposure, sparse descriptive cross-tabs, and readiness flags. It is not a crash-rate prototype, regression, predictive model, causal analysis, safety-performance ranking, or policy-guidance product.

The first rate-denominator policy support package now lives under `work/output/roadway_graph/analysis/current/rate_denominator_policy/`, with the design memo at `../design/roadway_graph_rate_denominator_policy.md`. It documents the recommended window-grain prototype unit, numerator policy, conceptual VMT-like denominator, accepted-crash study-period audit, provisional bidirectional-AADT treatment, missing/review AADT exclusions, suppression flags, and language guardrails. It does not compute crash rates or AADT-normalized comparisons.

The rate-assumption approval v1 package now lives under `work/output/roadway_graph/analysis/current/rate_assumption_approval_v1/`, with the design memo at `../design/roadway_graph_rate_assumption_approval_v1.md`. It accepts 2022-2024 as the numerator period, approves AADT-year alignment with limitation flags, approves provisional bidirectional AADT treatment, defines suppression and eligibility flags, and authorizes only a future window-grain descriptive rate prototype. It does not compute rates.

The first descriptive crash-rate prototype now lives under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/`. It uses only `reference_signal_id + signal_relative_direction + analysis_window`, denominator-ready rows, stable AADT, represented length in miles, and the approved 2022-2024 study period. It is provisional and descriptive only; it does not compute raw-bin rates, fixed-band rates, models, causal claims, safety-performance rankings, danger/risk rankings, policy guidance, or downstream functional-area distance recommendations.

The descriptive crash-rate prototype QA package now lives under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_qa/`. It summarizes rate distributions, high-rate artifact review queues, non-ready unit exclusions, AADT-year flags, and interpretation readiness without recomputing the rate method or creating new rate grains.

The descriptive crash-rate suppression review now lives under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review/`. It uses SciPy exact Poisson/Garwood intervals, compares them to the prior approximate intervals, flags unit-level rates for QA review, and keeps stakeholder-facing rate output limited to aggregate window and direction summaries with caveats.

The crash-count modeling readiness dataset package now lives under `work/output/roadway_graph/analysis/current/crash_count_modeling_readiness_dataset/`. It creates read-only model-prep matrices at `reference_signal_id + signal_relative_direction + analysis_window` and `reference_signal_id + signal_relative_direction + distance_band`, prepares `log_estimated_exposure` for a future count-model offset, and writes exploratory association tables for speed, local access density, distance, AADT, and signal-relative direction. It does not fit a model or create predictions, causal claims, rankings, policy guidance, or distance recommendations. Access density is recalculated at the local model-unit grain, `DIRECTION_FACTOR` is not applied, AADT remains bidirectional/provisional, and high/exploding preview rates are preserved with QA flags.

The crash-count model specification memo now lives at `../design/roadway_graph_crash_count_model_specification.md`, with supporting outputs under `work/output/roadway_graph/analysis/current/crash_count_model_specification/`. It defines the first exploratory model sequence only: `assigned_crash_count` as outcome, `offset(log_estimated_exposure)`, signal-direction-window as the first grain, Poisson GLM first, negative-binomial GLM if overdispersion is present, and diagnostics before interpretation. It does not fit any model, create predictions, apply `DIRECTION_FACTOR`, use crash direction fields, or authorize policy/report conclusions.

The first exploratory crash-count model fit package now lives under `work/output/roadway_graph/analysis/current/crash_count_exploratory_model_fit/`. It fits only the signal-direction-window sequence M0 through M4 using denominator-ready rows and `offset(log_estimated_exposure)`, then writes diagnostics, coefficients, incidence-rate-ratio transforms, overdispersion checks, family comparisons, residual summaries, influence-review queues, sparse-category checks, guardrails, findings, and a manifest. Current result: 2,967 rows and 12,414 assigned crashes modeled; the Poisson sequence fit successfully; overdispersion is present; negative-binomial comparison was attempted but current Hessian/covariance warnings make it not usable for interpretation; the Poisson access-interaction model improves AIC versus the simpler add-access model. Outputs remain exploratory/internal technical review only.

The crash-count model refinement sensitivity package now lives under `work/output/roadway_graph/analysis/current/crash_count_model_refinement_sensitivity/`. It keeps the signal-direction-window grain and tests fixed-alpha negative-binomial GLM sensitivities, scaled/robust/clustered Poisson standard errors, speed-category simplification, stable-speed-only sensitivity, and access-interaction stability. Current decision: `requires_category_simplification`. Fixed-alpha NB sensitivities are stable but remain sensitivity evidence only; estimated-alpha NB is not ready for interpretation; scaled/robust/clustered Poisson variants are feasible; the access interaction improves AIC consistently; merging 50-59 mph and 60+ mph removes the sparse 60+ mph category. Outputs remain internal exploratory refinement only.

The category-simplified internal model package now lives under `work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model/`. It merges 50-59 mph and 60+ mph into `50+ mph`, keeps missing/review speed explicit, preserves the signal-direction-window grain, and fits S0-S4 with Poisson, overdispersion-adjusted Poisson, robust Poisson, cluster-robust Poisson, and fixed-alpha NB sensitivity models. Current decision: `access_speed_model_ready_internal_only`. The recommended internal model is `S3_access_interaction_speed_simplified` with scaled and cluster-robust Poisson inference. Stakeholder interpretation remains blocked.

The internal crash-count model review package now lives under `work/output/roadway_graph/analysis/current/crash_count_internal_model_review/`, with the memo at `../reports/roadway_graph/internal_model_technical_review_memo.md`. It reformats existing simplified-model outputs into internal review summary, selected coefficients, selected IRRs, diagnostics, access interaction interpretation, speed interpretation, limitations, language guardrails, next steps, and manifest tables. It does not fit new models, use crash direction fields, apply `DIRECTION_FACTOR`, fit distance-band models, create stakeholder conclusions, rank signals, make causal claims, or recommend downstream functional area distances.

Use:

- `roadway_graph_context_analysis_plan.md`
- `../design/roadway_graph_next_phase_plan.md`
- `../design/roadway_graph_rate_and_modeling_readiness_plan.md`
- `../design/roadway_graph_rate_denominator_policy.md`
- `../design/roadway_graph_rate_assumption_approval_v1.md`
- `../design/roadway_graph_crash_count_model_specification.md`
