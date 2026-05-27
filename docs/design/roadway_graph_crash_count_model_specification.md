# Roadway Graph Crash Count Model Specification

**Status: MODEL SPECIFICATION ONLY.** This memo defines the first exploratory crash-count model sequence for the roadway-graph analysis universe. It does not fit models, create predictions, make causal claims, create rankings, create policy guidance, or recommend downstream functional-area distances.

## Bounded Question

How should the first exploratory crash-count models be specified so they can evaluate how assigned crash counts vary with distance window, local access density, speed context, AADT context, and signal-relative direction while accounting for estimated exposure?

## Modeling Purpose

The first model stage is exploratory association modeling.

The outcome is:

`assigned_crash_count`

The offset is:

`log_estimated_exposure`

The goal is to evaluate whether assigned crash counts are associated with analysis window, local access density, speed band, and signal-relative direction after accounting for the current estimated exposure denominator. This is not a crash-rate model. It is also not a production prediction model, causal analysis, location ranking, policy tool, warrant, or downstream functional-area distance method.

Allowed interpretation language after diagnostics:

- associated with
- higher modeled crash counts after accounting for estimated exposure
- lower modeled crash counts after accounting for estimated exposure
- exploratory
- provisional
- descriptive association

Avoid interpretation language that implies causality, location ordering, policy use, or functional-area guidance.

## Recommended First Modeling Grain

Use:

`reference_signal_id + signal_relative_direction + analysis_window`

This is the recommended first fitting grain because it:

- is less sparse than the fixed distance-band grain
- is already denominator-ready under the current readiness package
- preserves the 0-1,000 ft and 1,000-2,500 ft distinction
- retains signal-relative upstream/downstream interpretation
- supports an `analysis_window x local_access_density_band` interaction motivated by the observed access-density patterns
- aligns with the approved descriptive-rate denominator prototype

Current readiness:

- Window matrix: 3,222 units; 2,967 denominator-ready.
- Distance-band matrix: 7,797 units; 7,174 denominator-ready.
- Window denominator-ready assigned crashes: 12,414 of 13,216.
- Distance-band denominator-ready assigned crashes: 12,413 of 13,216.

Treat the distance-band grain as exploratory sensitivity and later interaction review. It should not be the first fitted model grain because it is more granular and carries more sparse and zero-count units.

## Outcome And Offset

Primary outcome:

`assigned_crash_count`

Primary offset:

`offset(log_estimated_exposure)`

Existing v1 exposure definition:

`estimated_exposure = length_weighted_stable_AADT x represented_length_miles x 1,096 days`

Primary model rows should be denominator-ready rows only. Denominator-ready rows require positive represented length, positive stable AADT, and stable AADT coverage share at or above the current 0.80 threshold.

Exposure caveats for existing model-prep/model outputs:

- Existing outputs use the older v1 bidirectional/provisional AADT exposure.
- `DIRECTION_FACTOR` is not applied in existing outputs.
- The active denominator policy is now v2 direction-factor with null-factor bidirectional fallback; the model offset needs a v2 refresh before active denominator interpretation.
- AADT year flags are preserved.
- Mixed AADT year and outside-period AADT year flags should be retained for sensitivity and interpretation review.
- The offset supports count-model exposure adjustment; it does not make the output policy-ready.

## Candidate Predictors

Primary candidates:

- `analysis_window`
- `signal_relative_direction`
- `local_access_density_band`
- `local_access_density_per_1000ft`
- `speed_band`
- `stable_speed_coverage_share`
- `roadway_representation_mix`, if simplified into an interpretable category before fitting

Caution candidates:

- `aadt_band`, because AADT is already part of the exposure offset
- `aadt_year_status`, because it is a denominator metadata flag rather than roadway context
- crash `AREA_TYPE` composition, because it is crash-level context and not roadway-level rural/suburban/urban geography

Do not use crash direction fields.

## Candidate Interactions

Prioritize:

- `analysis_window x local_access_density_band`
- `analysis_window x speed_band`
- `signal_relative_direction x analysis_window`
- `speed_band x local_access_density_band`, optional after the simpler interactions are reviewed

The access interaction is motivated by the readiness package finding that the 0-1,000 ft access pattern appears non-monotonic while the 1,000-2,500 ft pattern appears monotonic after the zero-access group. These are exploratory descriptive patterns, not fitted effects.

## Model Sequence

Use the following staged sequence, stopping if diagnostics show instability or sparse categories dominate the result.

M0 exposure-only:

`assigned_crash_count ~ 1 + offset(log_estimated_exposure)`

M1 window/direction:

`assigned_crash_count ~ analysis_window + signal_relative_direction + offset(log_estimated_exposure)`

M2 add access:

`assigned_crash_count ~ analysis_window + signal_relative_direction + local_access_density_band + offset(log_estimated_exposure)`

M3 access interaction:

`assigned_crash_count ~ analysis_window * local_access_density_band + signal_relative_direction + offset(log_estimated_exposure)`

M4 add speed:

`assigned_crash_count ~ analysis_window * local_access_density_band + signal_relative_direction + speed_band + offset(log_estimated_exposure)`

M5 optional sensitivity:

Add `aadt_band` or simplified roadway representation only as sensitivity, with explicit caution. AADT band requires special review because AADT is already part of `estimated_exposure`.

## Model Families

Recommended sequence:

1. Fit Poisson GLM first.
2. Use negative-binomial GLM if overdispersion is present.
3. Use robust or clustered standard errors by `reference_signal_id` if feasible.
4. Do not use a zero-inflated model unless diagnostics justify it.

The first implementation must output diagnostics before any report-facing interpretation.

## Missing And Review Handling

Primary analysis:

- denominator-ready units only
- `estimated_exposure` and `log_estimated_exposure` must be present and positive
- local access density is expected to be available because it is recomputed at the model unit grain
- AADT year, mixed-year, outside-period year, and bidirectional-AADT flags are retained

Speed handling:

- Preferred first approach: include `speed_missing_or_review` as an explicit category in `speed_band`.
- Sensitivity: rerun M4 on stable-speed units only, or include `stable_speed_coverage_share` as a quality covariate.

AADT handling:

- Do not impute AADT.
- Do not apply `DIRECTION_FACTOR`.
- Keep AADT year flags visible.
- Use `aadt_band` only in sensitivity models because the exposure offset already includes AADT.

Crash context handling:

- Crash `AREA_TYPE` composition should not be a primary predictor.
- It may be reviewed descriptively, but it is not roadway-level rural/suburban/urban truth.

## Required Diagnostics Before Interpretation

The first model-fitting module must report:

- overdispersion diagnostics
- Poisson versus negative-binomial comparison
- coefficient stability across M0-M5
- sparse category checks
- category reference levels
- residual diagnostics
- influence and outlier checks
- exposure distribution checks
- low crash-count and zero-count shares
- denominator-ready row counts and excluded crash counts
- sensitivity to missing/review speed treatment
- sensitivity to AADT band inclusion
- cluster or non-independence warning by `reference_signal_id`

No coefficient table should be interpreted until these diagnostics are reviewed.

## Interpretation Guardrails

Allowed:

- associated with
- higher/lower modeled crash counts after accounting for estimated exposure
- exploratory
- provisional
- descriptive association

Avoid:

- causes
- dangerous
- safety performance
- expected crashes for policy use
- functional area recommendation
- warrants
- guidance
- location ordering language

## Recommended Next Implementation Module

If this specification is accepted, the next implementation module should be:

`src/active/roadway_graph/crash_count_exploratory_model_fit.py`

The module should remain exploratory. It should fit the staged count-model sequence, write diagnostics before any interpretation table, preserve all denominator and AADT caveats, and avoid report-facing language until diagnostics are reviewed.

Implementation status:

- Implemented module: `src/active/roadway_graph/crash_count_exploratory_model_fit.py`
- Output folder: `work/output/roadway_graph/analysis/current/crash_count_exploratory_model_fit/`
- Current result: the Poisson sequence fits successfully, overdispersion is present, and the first negative-binomial comparison returns Hessian/covariance warnings that block interpretation of NB coefficients.
- Next refinement: review overdispersion handling, negative-binomial parameterization, stable-speed-only sensitivity, simplified roadway-representation sensitivity, and clustered/robust inference.

Refinement sensitivity status:

- Implemented module: `src/active/roadway_graph/crash_count_model_refinement_sensitivity.py`
- Output folder: `work/output/roadway_graph/analysis/current/crash_count_model_refinement_sensitivity/`
- Current decision: `requires_category_simplification`.
- Fixed-alpha negative-binomial GLM sensitivities fit without covariance warnings but remain sensitivity evidence only.
- Scaled, robust, and cluster-robust Poisson variants are feasible for internal technical review.
- The access interaction improves AIC consistently across tested sensitivities.
- Merge 50-59 mph and 60+ mph before coefficient-level interpretation.

Simplified internal model status:

- Implemented module: `src/active/roadway_graph/crash_count_simplified_internal_model.py`
- Output folder: `work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model/`
- Current decision: `access_speed_model_ready_internal_only`.
- Category simplification: 50-59 mph and 60+ mph are merged into `50+ mph`; missing/review speed remains explicit.
- Recommended internal model: `S3_access_interaction_speed_simplified` with scaled and cluster-robust Poisson inference.
- Stakeholder interpretation remains blocked pending internal technical review.

## Machine-Readable Specification Outputs

Supporting outputs live under:

`work/output/roadway_graph/analysis/current/crash_count_model_specification/`

Created outputs:

- `candidate_model_sequence.csv`
- `model_variable_role_table.csv`
- `model_specification_qa.csv`
- `crash_count_model_specification_findings.md`
- `crash_count_model_specification_manifest.json`
