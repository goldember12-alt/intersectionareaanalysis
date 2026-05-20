# Current Design Index

**Status: CURRENT ACTIVE.** The active design surface is limited to the roadway-derived directional context product and its controlled next phase.

## Active Design Docs

- `roadway_graph_context_enrichment_plan.md`: design record for attaching access, speed, AADT, and urban/rural context to the stable roadway-derived directional assignment universe without changing scaffold, catchment, assignment, or upstream/downstream logic.
- `roadway_graph_next_phase_plan.md`: current next-phase plan for descriptive analysis products, stakeholder deliverables, QA needs, non-goals, and production-hardening decisions after the directional-bin context prototype.
- `roadway_graph_rate_and_modeling_readiness_plan.md`: future readiness plan for crash-rate denominators, AADT-normalized comparisons, regression/predictive modeling, and causal-analysis prerequisites. It is planning only and does not authorize rates or models.
- `roadway_graph_rate_denominator_policy.md`: first denominator policy and rate-prototype specification memo. It defines the recommended window-grain unit, numerator, denominator concept, study-period status, AADT handling, suppression flags, exposure duplication policy, and permitted language without computing rates.
- `roadway_graph_rate_assumption_approval_v1.md`: bounded approval memo for descriptive rate prototype v1. It accepts the 2022-2024 numerator period, approves AADT-year alignment with limitations, approves provisional bidirectional AADT treatment, and defines suppression/flag rules without computing rates.
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

The first rate-denominator policy support package is implemented under `work/output/roadway_graph/analysis/current/rate_denominator_policy/`. It confirms that the recommended first rate-prototype unit remains `reference_signal_id + signal_relative_direction + analysis_window`, documents a provisional bidirectional-AADT treatment, audits accepted-crash dates for 2022-2024, and keeps rate calculation blocked until the study period and AADT assumptions are explicitly approved.

The rate-assumption approval v1 package is implemented under `work/output/roadway_graph/analysis/current/rate_assumption_approval_v1/`. It approves `2022-01-01` through `2024-12-31` as the numerator period for descriptive rate prototype v1, approves AADT-year alignment with limitation flags, approves provisional bidirectional AADT treatment, and authorizes a future `descriptive_crash_rate_prototype.py` module only at the window grain. It does not compute rates or authorize fixed-band rates, raw-bin rates, models, causal claims, safety-performance rankings, policy guidance, or downstream functional-area distance recommendations.

The first descriptive crash-rate prototype is implemented under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/`. It computes provisional AADT-normalized descriptive rates only at `reference_signal_id + signal_relative_direction + analysis_window`, preserves non-ready units separately, carries AADT-year and bidirectional-AADT limitation flags, and uses approximate Poisson count intervals. It does not authorize raw-bin rates, fixed-band rates, regression, predictive modeling, causal claims, safety-performance rankings, danger/risk rankings, policy guidance, or downstream functional-area distance recommendations.

The descriptive crash-rate prototype QA package is implemented under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_qa/`. It reviews the existing prototype rates for distribution shape, low denominator artifacts, wide interval flags, non-ready unit exclusions, AADT-year limitations, and interpretation readiness. It recommends internal technical review before fixed distance-band rate sensitivity and recommends installing scientific/statistical packages before exact intervals or later modeling.

The descriptive crash-rate suppression review is implemented under `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review/`. SciPy is available, so the module computes exact Poisson/Garwood intervals with `scipy.stats.chi2`, compares them to the prior approximate intervals, flags all unit-level rates as QA-only for stakeholder display because of the provisional bidirectional-AADT assumption, and preserves only aggregate window/direction summaries as stakeholder-safe descriptive tables with caveats.

The crash-count modeling readiness dataset package is implemented under `work/output/roadway_graph/analysis/current/crash_count_modeling_readiness_dataset/`. It prepares read-only feature matrices for a future count model where `assigned_crash_count` is the outcome and `log_estimated_exposure` is an offset. The package creates window-grain and distance-band-grain matrices, exploratory association tables, candidate formula specs, unit-quality summaries, warning flags, findings, and a manifest. It does not fit Poisson or negative-binomial models, create predictions, make causal or policy claims, rank safety performance/danger/risk, or recommend downstream functional-area distances.

Current modeling-prep design result: the recommended first fitting grain is `reference_signal_id + signal_relative_direction + analysis_window`. The fixed distance-band grain is useful for exploratory interaction review but is sparser. Local access density is computed at the model unit grain from summed access counts and summed represented length, not from raw 50-ft bin density. AADT remains bidirectional/provisional, `DIRECTION_FACTOR` is not applied, and AADT year issues are carried as flags rather than automatic suppressions.

The first crash-count model specification memo is implemented at `roadway_graph_crash_count_model_specification.md`, with supporting machine-readable outputs under `work/output/roadway_graph/analysis/current/crash_count_model_specification/`. It specifies exploratory count models with `assigned_crash_count` as the outcome and `offset(log_estimated_exposure)`, recommends the signal-direction-window grain for first fitting, and reserves the distance-band grain for later sensitivity or interaction review. The model sequence starts with Poisson GLM, moves to negative-binomial GLM if overdispersion is present, and requires diagnostics before any interpretation. It remains specification-only and does not fit models or create predictions.

The first exploratory crash-count model fit package is implemented under `work/output/roadway_graph/analysis/current/crash_count_exploratory_model_fit/`. It fits only the signal-direction-window exploratory sequence with denominator-ready rows and `offset(log_estimated_exposure)`. The current package models 2,967 rows and 12,414 assigned crashes. The Poisson sequence fits successfully, overdispersion is present, and the negative-binomial comparison currently returns Hessian/covariance warnings, so it is not usable for interpretation. The access-interaction model improves Poisson AIC compared with the simpler add-access model. The outputs are diagnostics-first internal technical review products, not stakeholder interpretation, external decision outputs, or distance recommendations.

The crash-count model refinement sensitivity package is implemented under `work/output/roadway_graph/analysis/current/crash_count_model_refinement_sensitivity/`. It tests fixed-alpha negative-binomial GLM sensitivities, scaled/robust/clustered Poisson standard errors, speed-category simplification, stable-speed-only sensitivity, and access-interaction stability without changing the signal-direction-window grain. The current decision is `requires_category_simplification`: fixed-alpha NB sensitivities are stable but are not a replacement for a stable estimated-alpha NB model, robust/scaled/clustered Poisson variants are feasible, the access interaction improves AIC consistently, and the 60+ mph speed category should be merged before coefficient-level interpretation.

The category-simplified internal model package is implemented under `work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model/`. It merges 50-59 mph and 60+ mph into `50+ mph`, keeps missing/review speed explicit, and preserves the original speed band for QA. The simplified package models 2,967 denominator-ready signal-direction-window rows and 12,414 assigned crashes. No sparse category rows remain after simplification. The current decision is `access_speed_model_ready_internal_only`, with `S3_access_interaction_speed_simplified` recommended for internal technical review using scaled and cluster-robust Poisson inference. Fixed-alpha NB remains sensitivity evidence only, and stakeholder interpretation remains blocked.

The internal crash-count model review memo is implemented at `../reports/roadway_graph/internal_model_technical_review_memo.md`, with supporting tables under `work/output/roadway_graph/analysis/current/crash_count_internal_model_review/`. It reviews the existing category-simplified model outputs without fitting new models. The selected internal model remains `S3_access_interaction_speed_simplified`; overdispersion, AADT directionality, AADT-year flags, and language approval remain blockers for stakeholder interpretation.

Current roadway-graph report planning docs live under `../reports/roadway_graph/`:

- `../reports/roadway_graph/roadway_graph_methodology_limitations_memo.md`
- `../reports/roadway_graph/roadway_graph_figure_inventory_and_specs.md`
- `../reports/roadway_graph/roadway_graph_report_outline.md`

These are planning and memo documents only. They do not create figures, final report language, policy claims, crash rates, models, or regressions.

Rate and modeling readiness is separately scoped in `roadway_graph_rate_and_modeling_readiness_plan.md`. The recommended next step after the internal technical review memo is technical review of the selected S3 diagnostics and coefficient stability, followed only by optional internal coefficient visualization or explicitly authorized sensitivity work. Report-facing model language remains blocked until method and language approval.
