# Current Design Index

**Status: CURRENT ACTIVE.** The active design surface is limited to the roadway-derived directional context product and its controlled next phase.

## Active Design Docs

- `roadway_graph_context_enrichment_plan.md`: design record for attaching access, speed, AADT, and urban/rural context to the stable roadway-derived directional assignment universe without changing scaffold, catchment, assignment, or upstream/downstream logic.
- `roadway_graph_next_phase_plan.md`: current next-phase plan for descriptive analysis products, stakeholder deliverables, QA needs, non-goals, and production-hardening decisions after the directional-bin context prototype.
- `roadway_graph_rate_and_modeling_readiness_plan.md`: future readiness plan for crash-rate denominators, AADT-normalized comparisons, regression/predictive modeling, and causal-analysis prerequisites. It is planning only and does not authorize rates or models.
- `roadway_graph_rate_denominator_policy.md`: active denominator policy and rate-prototype specification memo. It now promotes AADT direction-factor v2 as the active descriptive exposure denominator policy, while retaining v1 bidirectional AADT as baseline/legacy comparison.
- `roadway_graph_rate_assumption_approval_v1.md`: bounded historical approval memo for descriptive rate prototype v1. It accepts the 2022-2024 numerator period, approves AADT-year alignment with limitations, approves provisional bidirectional AADT treatment, and defines suppression/flag rules without computing rates.
- `roadway_graph_rate_assumption_approval_v2.md`: current active denominator assumption approval memo. It approves valid `DIRECTION_FACTOR` application with null-factor bidirectional fallback, invalid-factor review flags, and source-documentation caveat.
- `roadway_graph_speed_context_policy.md`: active speed context policy memo. It promotes speed v5 new-source supplement as active, retains speed v4 as baseline/legacy comparison, and points to the refreshed active v2/v5 context and analysis outputs.
- `roadway_graph_crash_count_model_specification.md`: exploratory crash-count model specification. It defines the signal-direction-window model grain, outcome, exposure offset, model sequence, diagnostics, and language guardrails.

## Product Milestone

The current implementation milestone is documented in:

`../workflow/roadway_graph_directional_context_milestone.md`

That milestone supersedes earlier one-off access, speed, AADT, network-analysis, and recovery design notes for active workflow purposes.

## Archived Design Notes

Superseded design and planning notes were moved to:

`../archive/20260519_cleanup/`

Use archived notes only as historical context or comparison evidence. Do not treat them as active design authority unless a later task explicitly promotes a specific item.

## Current Analysis Design Work

The next design phase is scoped in `roadway_graph_next_phase_plan.md`. The read-only descriptive summary modules are implemented under the workflow plan in `../workflow/roadway_graph_context_analysis_plan.md`.

Implemented descriptive table modules now cover first-stage summaries, signal review-priority queues, fixed distance-band profiles, signal-direction profiles, and a compact stakeholder table package. The first exposure/modeling-readiness audit is also implemented as a read-only audit under `work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`.

The readiness audit creates denominator-readiness flags, candidate feature-matrix scaffolds, descriptive count cross-tabs, sparse-cell queues, and duplicate source-bin exposure checks at `reference_signal_id + signal_relative_direction + analysis_window` and `reference_signal_id + signal_relative_direction + fixed distance_band`. It does not compute crash rates, fit models, make causal claims, rank safety performance, or recommend policy distances. Regression-ready or policy-ready products still need reviewed denominator period handling, directional AADT assumptions, uncertainty treatment, duplicate-exposure policy, and validation criteria.

The first rate-denominator policy support package is implemented under `work/output/roadway_graph/analysis/current/rate_denominator_policy/`. It confirms that the recommended first rate-prototype unit remains `reference_signal_id + signal_relative_direction + analysis_window`, audits accepted-crash dates for 2022-2024, and preserves v1 bidirectional-AADT treatment as the original baseline policy.

The rate-assumption approval v1 package is implemented under `work/output/roadway_graph/analysis/current/rate_assumption_approval_v1/`. It approves `2022-01-01` through `2024-12-31` as the numerator period for descriptive rate prototype v1, approves AADT-year alignment with limitation flags, approves provisional bidirectional AADT treatment, and authorizes a future `descriptive_crash_rate_prototype.py` module only at the window grain. It does not compute rates or authorize fixed-band rates, raw-bin rates, models, causal claims, safety-performance rankings, policy guidance, or downstream functional-area distance recommendations.

The active denominator policy package is implemented under `work/output/roadway_graph/analysis/current/active_rate_denominator_policy/`, with active approval documented in `roadway_graph_rate_assumption_approval_v2.md`. It promotes `v2_direction_factor_with_bidirectional_fallback` as the active descriptive exposure denominator policy: valid `DIRECTION_FACTOR` is applied, null factors fall back to v1 bidirectional treatment, invalid factors are flagged, and source-documentation caveats remain. Existing v1 rate and suppression outputs are retained as baseline/legacy comparison.

The active speed context policy package is implemented under `work/output/roadway_graph/review/current/active_speed_context_policy/`, with active policy documented in `roadway_graph_speed_context_policy.md`. It promotes `speed_v5_new_source_supplement` as the active speed context because `Speed_Limit_RNS` route+measure evidence is stronger than speed v4. Existing speed v4 outputs are retained as baseline/legacy comparison.

The active v2/v5 downstream refresh is implemented under `work/output/roadway_graph/analysis/current/directional_bin_context_table_active/`, `directional_context_descriptive_summaries_active/`, `descriptive_crash_rate_prototype_active/`, `descriptive_crash_rate_suppression_review_active/`, `crash_count_modeling_readiness_dataset_active/`, and `active_refresh_impact_summary/`. It uses speed v5 and AADT denominator v2 while preserving the accepted scaffold, catchments, crash assignment, access context, and AADT joins. It does not fit models or introduce policy, risk, safety-performance, or distance-guidance claims.

The first descriptive crash-rate prototype is implemented under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/`. It computes provisional AADT-normalized descriptive rates only at `reference_signal_id + signal_relative_direction + analysis_window`, preserves non-ready units separately, carries AADT-year and bidirectional-AADT limitation flags, and uses approximate Poisson count intervals. It does not authorize raw-bin rates, fixed-band rates, regression, predictive modeling, causal claims, safety-performance rankings, danger/risk rankings, policy guidance, or downstream functional-area distance recommendations.

The descriptive crash-rate prototype QA package is implemented under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_qa/`. It reviews the existing prototype rates for distribution shape, low denominator artifacts, wide interval flags, non-ready unit exclusions, AADT-year limitations, and interpretation readiness. It recommends internal technical review before fixed distance-band rate sensitivity and recommends installing scientific/statistical packages before exact intervals or later modeling.

The descriptive crash-rate suppression review is implemented under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review/`. SciPy is available, so the module computes exact Poisson/Garwood intervals with `scipy.stats.chi2`, compares them to the prior approximate intervals, flags all unit-level rates as QA-only for stakeholder display because of the provisional bidirectional-AADT assumption, and preserves only aggregate window/direction summaries as stakeholder-safe descriptive tables with caveats.

The crash-count modeling readiness dataset package is implemented under `work/output/roadway_graph/analysis/current/crash_count_modeling_readiness_dataset/`. It prepares read-only feature matrices for a future count model where `assigned_crash_count` is the outcome and `log_estimated_exposure` is an offset. The package creates window-grain and distance-band-grain matrices, exploratory association tables, candidate formula specs, unit-quality summaries, warning flags, findings, and a manifest. It does not fit Poisson or negative-binomial models, create predictions, make causal or policy claims, rank safety performance/danger/risk, or recommend downstream functional-area distances.

Current modeling-prep design result: the recommended first fitting grain is `reference_signal_id + signal_relative_direction + analysis_window`. The fixed distance-band grain is useful for exploratory interaction review but is sparser. Local access density is computed at the model unit grain from summed access counts and summed represented length, not from raw 50-ft bin density. The active modeling-readiness matrices now use speed v5 and AADT denominator v2; older modeling-prep and internal model outputs remain baseline/legacy until a separate model-fitting task is explicitly run. AADT year issues remain flags rather than automatic suppressions.

The first crash-count model specification memo is implemented at `roadway_graph_crash_count_model_specification.md`, with supporting machine-readable outputs under `work/output/roadway_graph/analysis/current/crash_count_model_specification/`. It specifies exploratory count models with `assigned_crash_count` as the outcome and `offset(log_estimated_exposure)`, recommends the signal-direction-window grain for first fitting, and reserves the distance-band grain for later sensitivity or interaction review. The model sequence starts with Poisson GLM, moves to negative-binomial GLM if overdispersion is present, and requires diagnostics before any interpretation. It remains specification-only and does not fit models or create predictions.

The first exploratory crash-count model fit package is implemented under `work/output/roadway_graph/analysis/current/crash_count_exploratory_model_fit/`. It fits only the signal-direction-window exploratory sequence with denominator-ready rows and `offset(log_estimated_exposure)`. The current package models 2,967 rows and 12,414 assigned crashes. The Poisson sequence fits successfully, overdispersion is present, and the negative-binomial comparison currently returns Hessian/covariance warnings, so it is not usable for interpretation. The access-interaction model improves Poisson AIC compared with the simpler add-access model. The outputs are diagnostics-first internal technical review products, not stakeholder interpretation, external decision outputs, or distance recommendations.

The crash-count model refinement sensitivity package is implemented under `work/output/roadway_graph/analysis/current/crash_count_model_refinement_sensitivity/`. It tests fixed-alpha negative-binomial GLM sensitivities, scaled/robust/clustered Poisson standard errors, speed-category simplification, stable-speed-only sensitivity, and access-interaction stability without changing the signal-direction-window grain. The current decision is `requires_category_simplification`: fixed-alpha NB sensitivities are stable but are not a replacement for a stable estimated-alpha NB model, robust/scaled/clustered Poisson variants are feasible, the access interaction improves AIC consistently, and the 60+ mph speed category should be merged before coefficient-level interpretation.

The active category-simplified internal model rerun is implemented under `work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model_active/`. It uses the active v2/v5 window-grain modeling-readiness matrix, merges 50-59 mph and 60+ mph into `50+ mph`, keeps missing/review speed explicit, and preserves the signal-direction-window grain. The prior `crash_count_simplified_internal_model/` package is retained as baseline/history. Active result: 2,967 denominator-ready rows and 12,414 assigned crashes modeled; access interaction and simplified speed still improve AIC; overdispersion remains; scaled and cluster-robust Poisson remain the primary internal-review family.

The internal crash-count model review memo is implemented at `../reports/roadway_graph/internal_model_technical_review_memo.md`, with supporting tables under `work/output/roadway_graph/analysis/current/crash_count_internal_model_review/`. It reviews the existing category-simplified model outputs without fitting new models. The selected internal model remains `S3_access_interaction_speed_simplified`; overdispersion, AADT directionality, AADT-year flags, and language approval remain blockers for stakeholder interpretation.

The prior internal model visualization package keeps figure-ready source tables under `work/output/roadway_graph/analysis/current/crash_count_internal_model_figures/`, with the cleaned presentation subset under `../reports/roadway_graph/modeling_figures/`. These figures were generated before the active v2/v5 model refresh and are retained as baseline/historical visual references until regenerated from active outputs. They do not fit new models, change the model specification, update stakeholder report conclusions, or support causal/policy/ranking/distance language.

The baseline negative-binomial stabilization diagnostic is implemented under `work/output/roadway_graph/analysis/current/crash_count_negative_binomial_stabilization/`. It attempts estimated-alpha NB models across increasing complexity and reruns fixed-alpha NB sensitivity at alpha 0.25, 0.5, 1.0, and 2.0 using the denominator-ready signal-direction-window grain and S3 simplified categories. Baseline decision: `robust_poisson_primary_nb_sensitivity`; estimated-alpha NB is unstable and not interpretable, while fixed-alpha NB remains sensitivity evidence only.

The active v2/v5 negative-binomial stabilization diagnostic is implemented under `work/output/roadway_graph/analysis/current/crash_count_negative_binomial_stabilization_active/`. It uses the active v2 exposure offset and speed v5 simplified categories with the same denominator-ready signal-direction-window grain. Active result: estimated-alpha NB is interpretable for `NB0_exposure_only_active` and `NB3_access_interaction_no_speed_active`, but `NB1`, `NB2`, and `NB4_access_interaction_speed_simplified_active` remain unstable or incomplete, so estimated-alpha NB does not replace the active robust/scaled Poisson family. Fixed-alpha NB fits across alpha 0.25, 0.5, 1.0, and 2.0 and supports the access-window interaction and simplified speed as sensitivity evidence only. Active readiness decision: `active_robust_poisson_primary_nb_sensitivity`; stakeholder interpretation remains blocked.

The active internal modeling conclusion and presentation-readiness memo is implemented at `../reports/roadway_graph/internal_modeling_conclusion_and_presentation_readiness.md`, with active support tables under `work/output/roadway_graph/analysis/current/internal_modeling_conclusion_readiness_active/`. It synthesizes the active v2/v5 simplified internal model and active NB stabilization result. Current design conclusion: active `S3_access_interaction_speed_simplified` remains the selected internal model; scaled and cluster-robust Poisson remain the preferred internal model family; fixed-alpha NB remains sensitivity-only; stakeholder-facing model claims remain blocked. The prior `internal_modeling_conclusion_readiness/` support package is retained as baseline/history.

Current roadway-graph report planning docs live under `../reports/roadway_graph/`:

- `../reports/roadway_graph/roadway_graph_methodology_limitations_memo.md`
- `../reports/roadway_graph/roadway_graph_figure_inventory_and_specs.md`
- `../reports/roadway_graph/roadway_graph_report_outline.md`

These are planning and memo documents only. They do not create figures, final report language, policy claims, crash rates, models, or regressions.

Rate and modeling readiness is separately scoped in `roadway_graph_rate_and_modeling_readiness_plan.md`. The recommended next step after the internal technical review memo is technical review of the selected S3 diagnostics and coefficient stability, followed only by optional internal coefficient visualization or explicitly authorized sensitivity work. Report-facing model language remains blocked until method and language approval.
