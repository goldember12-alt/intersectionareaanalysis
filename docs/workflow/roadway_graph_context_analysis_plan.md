# Roadway Graph Context Analysis Plan

**Status: CURRENT WORKFLOW PLAN WITH TABLE-PACKAGE AND EXPOSURE-READINESS MODULES IMPLEMENTED.** This document turns the next-phase design into a bounded implementation plan for descriptive analysis outputs and the first exposure/modeling-readiness audit. The read-only summary module, signal review queue, fixed distance-band profiles, signal-direction profiles, compact stakeholder table package, and exposure/modeling-readiness audit are implemented.

## Bounded Question

How should the current roadway-derived directional-bin context table be summarized for descriptive analysis without changing the scaffold, catchments, crash assignment, or context joins?

## Inputs

Primary current product:

- `work/output/roadway_graph/analysis/current/directional_bin_context_table/directional_bin_context.csv`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table/directional_crash_context.csv`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table/reference_signal_context_summary.csv`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table/combined_context_join_qa.csv`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table/directional_bin_context_manifest.json`

Supporting current readouts:

- `work/output/roadway_graph/analysis/current/crash_directional_assignment_descriptive_summary/`
- accepted context-layer findings/manifests under `work/output/roadway_graph/review/current/`

## Output Location

Current first-stage output folder:

`work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries/`

Additional current descriptive output folders:

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
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_direction_factor_sensitivity/`
- `work/output/roadway_graph/analysis/current/active_rate_denominator_policy/`
- `work/output/roadway_graph/review/current/active_speed_context_policy/`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table_active/`
- `work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries_active/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_active/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review_active/`
- `work/output/roadway_graph/analysis/current/crash_count_modeling_readiness_dataset_active/`
- `work/output/roadway_graph/analysis/current/active_refresh_impact_summary/`

Use matching history/run metadata lanes if implemented later.

## Implemented First-Stage Summary Module

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.directional_context_descriptive_summaries
```

Created outputs:

- `directional_context_summary_by_window.csv`
- `directional_context_summary_by_signal_relative_direction.csv`
- `directional_context_summary_by_reference_signal.csv`
- `directional_context_summary_by_signal_direction_window.csv`
- `directional_context_summary_by_distance_band.csv`
- `directional_context_summary_by_roadway_representation.csv`
- `directional_context_summary_by_speed_band.csv`
- `directional_context_summary_by_aadt_band.csv`
- `directional_context_summary_access_exposure.csv`
- `directional_context_summary_crash_area_type.csv`
- `directional_context_context_completeness_summary.csv`
- `directional_context_descriptive_summary_qa.csv`
- `directional_context_descriptive_summary_findings.md`
- `directional_context_descriptive_summary_manifest.json`

The implemented module is read-only against the accepted combined context table and companion context outputs. It does not create figures, stakeholder report narrative, models, regression outputs, crash rates, or policy claims.

## Implemented Signal Review Queue Module

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.signal_context_review_queue
```

Figure-ready source table output folder:

`work/output/roadway_graph/analysis/current/signal_context_review_queue/`

Created outputs:

- `signal_review_queue_overall.csv`
- `signal_review_queue_high_priority_0_1000ft.csv`
- `signal_direction_review_queue.csv`
- `signal_direction_window_review_queue.csv`
- `signal_review_queue_by_crash_burden.csv`
- `signal_review_queue_by_directional_imbalance.csv`
- `signal_review_queue_by_context_density.csv`
- `signal_review_queue_by_context_completeness.csv`
- `signal_review_queue_flags_summary.csv`
- `signal_context_review_queue_qa.csv`
- `signal_context_review_queue_findings.md`
- `signal_context_review_queue_manifest.json`

The signal review queue is for manual review prioritization only. It is not a danger ranking, model output, crash-rate analysis, causal analysis, policy finding, or stakeholder report.

## Implemented Distance Band Profile Module

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.directional_context_distance_band_profiles
```

Output folder:

`work/output/roadway_graph/analysis/current/directional_context_distance_band_profiles/`

Created outputs:

- `distance_band_profile_overall.csv`
- `distance_band_profile_by_signal_relative_direction.csv`
- `distance_band_profile_by_roadway_representation.csv`
- `distance_band_profile_by_access_exposure.csv`
- `distance_band_profile_by_speed_context.csv`
- `distance_band_profile_by_aadt_context.csv`
- `distance_band_profile_by_crash_area_type.csv`
- `distance_band_profile_by_reference_signal.csv`
- `distance_band_profile_qa.csv`
- `distance_band_profile_findings.md`
- `distance_band_profile_manifest.json`

The module uses fixed 0-250 ft, 250-500 ft, 500-1,000 ft, 1,000-1,500 ft, and 1,500-2,500 ft bands. It is descriptive only and does not compute crash rates or AADT-normalized measures.

## Implemented Signal Direction Profile Module

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.signal_direction_context_profiles
```

Output folder:

`work/output/roadway_graph/analysis/current/signal_direction_context_profiles/`

Created outputs:

- `signal_direction_profile.csv`
- `signal_direction_window_profile.csv`
- `signal_direction_distance_band_profile.csv`
- `signal_direction_context_completeness_profile.csv`
- `signal_direction_profile_top_crash_burden.csv`
- `signal_direction_profile_top_directional_imbalance.csv`
- `signal_direction_profile_review_flags.csv`
- `signal_direction_profile_qa.csv`
- `signal_direction_profile_findings.md`
- `signal_direction_profile_manifest.json`

Required grains are implemented as `reference_signal_id + signal_relative_direction`, `reference_signal_id + signal_relative_direction + analysis_window`, and `reference_signal_id + signal_relative_direction + distance_band`.

## Implemented Stakeholder Table Package

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.stakeholder_context_table_package
```

Output folder:

`work/output/roadway_graph/analysis/current/stakeholder_context_table_package/`

Created outputs:

- `stakeholder_table_index.csv`
- `stakeholder_table_package_readme.md`
- `stakeholder_summary_overview.csv`
- `stakeholder_signal_review_queue_top.csv`
- `stakeholder_signal_direction_profiles_top.csv`
- `stakeholder_distance_band_summary.csv`
- `stakeholder_context_completeness_summary.csv`
- `stakeholder_limitations_table.csv`
- `stakeholder_table_package_qa.csv`
- `stakeholder_table_package_manifest.json`

This is a table package only. It preserves detailed outputs in the source module folders and selects compact stakeholder-facing review tables plus technical QA.

## Implemented Exposure and Modeling Readiness Audit

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.exposure_modeling_readiness_audit
```

Output folder:

`work/output/roadway_graph/analysis/current/exposure_modeling_readiness_audit/`

Created outputs:

- `exposure_modeling_readiness_summary.csv`
- `analysis_unit_readiness_signal_direction_window.csv`
- `analysis_unit_readiness_signal_direction_distance_band.csv`
- `modeling_feature_matrix_signal_direction_window.csv`
- `modeling_feature_matrix_signal_direction_distance_band.csv`
- `exposure_denominator_candidate_fields.csv`
- `exposure_duplicate_source_bin_audit.csv`
- `exposure_duplicate_by_reference_signal.csv`
- `exposure_context_coverage_by_unit.csv`
- `exposure_low_denominator_review_queue.csv`
- `exposure_sparse_cell_review_queue.csv`
- `crashes_by_distance_band_and_direction.csv`
- `crashes_by_distance_band_and_speed_band.csv`
- `crashes_by_distance_band_and_aadt_band.csv`
- `crashes_by_distance_band_and_access_density_band.csv`
- `crashes_by_direction_speed_aadt_band.csv`
- `crashes_by_direction_distance_access_band.csv`
- `crashes_by_speed_aadt_access_band.csv`
- `crashes_by_context_completeness.csv`
- `exposure_modeling_readiness_qa.csv`
- `exposure_modeling_readiness_findings.md`
- `exposure_modeling_readiness_manifest.json`

The module audits candidate analysis units at `reference_signal_id + signal_relative_direction + analysis_window` and `reference_signal_id + signal_relative_direction + fixed distance_band`. It creates denominator-readiness flags, feature-matrix scaffolds, descriptive count cross-tabs, sparse-cell queues, and duplicate source-bin audits. It does not compute crash rates, fit regressions, create predictive models, make causal claims, rank safety performance, or recommend downstream functional area distances.

## Active Denominator Policy Update

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.active_rate_denominator_policy_update
```

Output folder:

`work/output/roadway_graph/analysis/current/active_rate_denominator_policy/`

Created outputs:

- `active_rate_denominator_policy_summary.csv`
- `active_rate_denominator_policy_rules.csv`
- `active_rate_denominator_policy_comparison_v1_v2.csv`
- `active_rate_denominator_policy_findings.md`
- `active_rate_denominator_policy_manifest.json`

This module promotes `v2_direction_factor_with_bidirectional_fallback` as the active descriptive exposure denominator policy going forward. It does not rerun rates, overwrite v1 outputs, fit models, create figures, or change downstream combined context tables. Valid `DIRECTION_FACTOR` is applied only in the approved denominator context, null factors fall back to v1 bidirectional AADT treatment, invalid factors are flagged, and the source-documentation caveat remains open.

Downstream outputs requiring refresh before they are treated as current under v2:

- descriptive crash-rate prototype v2 active denominator outputs
- rate suppression review v2 active denominator outputs
- context relationship rate figures using v2
- modeling readiness exposure/offset update
- simplified internal model v2 only if speed/AADT context changes are accepted

## Active Speed Context Policy Update

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.active_speed_context_policy_update
```

Output folder:

`work/output/roadway_graph/review/current/active_speed_context_policy/`

Created outputs:

- `active_speed_context_policy_summary.csv`
- `active_speed_context_policy_rules.csv`
- `active_speed_context_v4_v5_comparison.csv`
- `active_speed_context_conflict_summary.csv`
- `active_speed_context_downstream_refresh_requirements.csv`
- `active_speed_context_policy_findings.md`
- `active_speed_context_policy_manifest.json`

This module promotes `speed_v5_new_source_supplement` as the active speed context going forward. It does not overwrite speed v4 outputs, overwrite `artifacts/normalized/speed.parquet`, rerun the combined context table, rerun rates, or fit models. `Speed_Limit_RNS` route+measure evidence is preferred for future refreshes, v4/v5 conflicts are preserved as QA evidence rather than blockers, and remaining v5 review/missing statuses remain visible. No speed values are imputed.

Downstream outputs requiring refresh before they are treated as current under v5:

- combined directional-bin context table
- descriptive context summaries
- review queues and profile outputs using speed context
- stakeholder table packages and report figures/tables using speed context
- rate outputs after active denominator v2 and active speed v5 are integrated
- modeling readiness datasets and internal models before interpreting speed terms under v5

## Active V2/V5 Downstream Refresh

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.directional_bin_context_table_active_refresh
```

Primary output folders:

- `work/output/roadway_graph/analysis/current/directional_bin_context_table_active/`
- `work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries_active/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_active/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review_active/`
- `work/output/roadway_graph/analysis/current/crash_count_modeling_readiness_dataset_active/`
- `work/output/roadway_graph/analysis/current/active_refresh_impact_summary/`

This module refreshes the accepted downstream analytical surface using speed v5 and AADT denominator v2. It reuses the existing scaffold, catchments, crash assignment/readiness, access context, AADT v3 context join, and crash-level `AREA_TYPE` context. It does not overwrite v1/v4 outputs, rerun source staging, modify graph/context joins, use crash direction fields, fit models, or make policy/risk/safety-performance claims.

Active refresh counts:

- stable speed bins: 84,857 baseline v4 -> 105,835 active v5
- represented assigned crashes: 13,216 -> 13,216
- rate-ready window units: 2,967 -> 2,967
- v1 exposure: 12,162,169,675.11
- active v2 exposure: 7,108,955,359.70
- v1 aggregate rate per million: 1.020706
- active v2 aggregate rate per million: 1.746248
- window-grain modeling-ready units: 2,124 baseline -> 2,786 active

Figures and report tables that use speed coverage, speed bands, rates, or model matrices must be regenerated from the active folders before they are treated as current.

Current readiness results:

- Window-grain denominator-ready units under the conservative AADT coverage rule: 2,967 of 3,222.
- Fixed-band denominator-ready units under the conservative AADT coverage rule: 7,174 of 7,797.
- Window-grain modeling-ready candidate units after adding speed coverage gate: 2,041 of 3,222.
- Fixed-band modeling-ready candidate units after adding speed coverage gate: 4,645 of 7,797.
- Assigned-crash coverage retained in denominator-ready window units: 12,414 of 13,216.
- Assigned-crash coverage retained in denominator-ready fixed-band units: 12,413 of 13,216.

The readiness flags use positive represented length and stable AADT coverage share >= 0.80. Missing or review AADT is not treated as stable denominator context. Stable speed coverage is retained as a modeling-readiness gate, not as a crash-rate denominator.

## Implemented Rate Denominator Policy Support

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.rate_denominator_policy_audit
```

Design memo:

`docs/design/roadway_graph_rate_denominator_policy.md`

Output folder:

`work/output/roadway_graph/analysis/current/rate_denominator_policy/`

Created outputs:

- `rate_denominator_policy_summary.csv`
- `rate_denominator_candidate_unit_counts.csv`
- `crash_study_period_audit.csv`
- `rate_denominator_policy_spec.csv`
- `rate_denominator_policy_qa.csv`
- `rate_denominator_policy_findings.md`
- `rate_denominator_policy_manifest.json`

The module writes policy-support tables only. It does not compute crash rates, AADT-normalized comparisons, models, regressions, causal claims, safety-performance rankings, or policy recommendations.

Current policy result:

- Recommended first rate-prototype unit: `reference_signal_id + signal_relative_direction + analysis_window`.
- Windows: `high_priority_0_1000ft` and `sensitivity_1000_2500ft`.
- Numerator: accepted assigned crashes only.
- Future denominator concept: `AADT x represented length x crash study period`.
- AADT treatment: stable AADT only; missing/review AADT excluded from denominator-gated rate rows and reported.
- Provisional directional AADT assumption: use AADT as bidirectional exposure for each signal-relative directional view until direction-factor/source directionality is validated.
- Crash date audit: 13,216 accepted assigned crashes matched to dates from 2022-01-01 through 2024-12-31, with 0 missing dates.

The study period is available but not yet authorized for rate calculation. A later approval step must confirm the 2022-2024 period, AADT year handling, bidirectional-AADT treatment, and suppression rules before `descriptive_crash_rate_prototype.py` is implemented.

## Implemented Rate Assumption Approval V1

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.rate_assumption_approval_audit
```

Design memo:

`docs/design/roadway_graph_rate_assumption_approval_v1.md`

Output folder:

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

Current approval result:

- Authorization decision: `approved_for_descriptive_rate_prototype_v1`.
- Authorized next module: `src/active/roadway_graph/descriptive_crash_rate_prototype.py`.
- Approved prototype unit: `reference_signal_id + signal_relative_direction + analysis_window`.
- Approved numerator period: `2022-01-01` through `2024-12-31`.
- Study period length: 1,096 days, or 3.000684 years using days / 365.25.
- AADT year alignment recommendation: `approved_with_limitation`.
- Directional AADT recommendation: `approved_bidirectional_aadt_for_prototype_v1`.

This approval remains bounded. It does not authorize fixed-band rates, raw-bin rates, models/regressions, causal claims, safety-performance rankings, policy guidance, or downstream functional-area distance recommendations.

## Implemented Descriptive Crash-Rate Prototype

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.descriptive_crash_rate_prototype
```

Output folder:

`work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype/`

Created outputs:

- `descriptive_rate_prototype_signal_direction_window.csv`
- `descriptive_rate_prototype_non_ready_units.csv`
- `descriptive_rate_summary_by_window.csv`
- `descriptive_rate_summary_by_signal_relative_direction.csv`
- `descriptive_rate_summary_by_review_flags.csv`
- `descriptive_rate_top_review_units.csv`
- `descriptive_rate_prototype_qa.csv`
- `descriptive_rate_prototype_findings.md`
- `descriptive_rate_prototype_manifest.json`

Current prototype result:

- Primary rate rows: 2,967.
- Non-ready window units preserved separately: 255.
- Crashes represented in rate-ready units: 12,414.
- Crashes excluded due to denominator readiness: 802.
- Median VMT-like exposure: 2,996,612.32.
- Mean VMT-like exposure: 4,099,147.18.
- High-priority 0-1,000 ft summary: 8,512 crashes, 7,750,111,561.92 VMT-like exposure, 1.098307 crashes per million VMT-like exposure.
- Sensitivity 1,000-2,500 ft summary: 3,902 crashes, 4,412,058,113.18 VMT-like exposure, 0.884395 crashes per million VMT-like exposure.
- Downstream summary: 6,288 crashes, 6,102,114,567.00 VMT-like exposure, 1.030462 crashes per million VMT-like exposure.
- Upstream summary: 6,126 crashes, 6,060,055,108.11 VMT-like exposure, 1.010882 crashes per million VMT-like exposure.

This v1 prototype is descriptive and provisional. It uses length-weighted stable AADT, represented length in miles, and the approved 1,096-day 2022-2024 study period. AADT is treated as bidirectional exposure for each signal-relative view and `DIRECTION_FACTOR` is not applied in this legacy/baseline output. Missing/review AADT units are excluded from primary rate rows and preserved in `descriptive_rate_prototype_non_ready_units.csv`. After the v2 active policy promotion, this output needs a v2 refresh before it is treated as the current active denominator product.

This module does not compute raw 50-ft bin rates, fixed distance-band rates, models, regressions, causal results, safety-performance rankings, danger/risk rankings, policy guidance, or downstream functional-area distance recommendations.

## Implemented Descriptive Crash-Rate Prototype QA

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.descriptive_crash_rate_prototype_qa
```

Output folder:

`work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_qa/`

Created outputs:

- `rate_distribution_summary.csv`
- `rate_distribution_by_window.csv`
- `rate_distribution_by_signal_relative_direction.csv`
- `top_rate_units_review_queue.csv`
- `low_denominator_rate_review_queue.csv`
- `non_ready_unit_summary.csv`
- `non_ready_units_by_reason.csv`
- `aadt_year_flag_rate_summary.csv`
- `rate_summary_comparison_window_direction.csv`
- `rate_interpretation_readiness_decision.csv`
- `descriptive_crash_rate_prototype_qa_checks.csv`
- `rate_prototype_interpretation_qa.csv`
- `descriptive_crash_rate_prototype_qa_findings.md`
- `descriptive_crash_rate_prototype_qa_manifest.json`

Current QA result:

- Rate rows checked: 2,967.
- Assigned crashes in primary rows: 12,414.
- Unit-rate median: 0.652846 crashes per million VMT-like exposure.
- Unit-rate mean: 1.822919 crashes per million VMT-like exposure.
- Unit-rate p95: 4.615331 crashes per million VMT-like exposure.
- Unit-rate maximum: 1070.559611 crashes per million VMT-like exposure, driven by very low exposure and assigned to QA review.
- Low-crash-count units: 1,658.
- Zero-crash units: 831.
- Low-exposure units: 297.
- Wide-interval units: 2,598.
- Non-ready units preserved separately: 255, carrying 802 assigned crashes.

Interpretation-readiness decision:

- Window-level rates are ready for internal technical review.
- Stakeholder-facing descriptive tables are ready with limitations if limited to window/direction summaries and non-ranking language.
- Denominator-rule refinement is recommended.
- Fixed distance-band rate sensitivity should wait until the window-grain QA review is complete.
- Modeling-readiness dataset remains not ready.
- Scientific package installation is recommended before exact intervals or later statistical work.

The QA module does not recompute the rate method, does not create fixed distance-band rates or raw bin-level rates, and does not fit models/regressions.

## Implemented Descriptive Crash-Rate Suppression Review

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.descriptive_crash_rate_suppression_review
```

Output folder:

`work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review/`

Created outputs:

- `rate_interval_method_comparison.csv`
- `rate_suppression_rule_spec.csv`
- `rate_unit_suppression_flags.csv`
- `stakeholder_safe_rate_summary_by_window.csv`
- `stakeholder_safe_rate_summary_by_direction.csv`
- `high_rate_units_suppressed_review_queue.csv`
- `rate_suppression_review_qa.csv`
- `rate_suppression_review_findings.md`
- `rate_suppression_review_manifest.json`

Current suppression result:

- SciPy is available and exact Poisson/Garwood intervals use `scipy.stats.chi2`.
- Primary unit rows reviewed: 2,967.
- Unit rows suppressed from stakeholder unit-rate display: 2,967.
- Low exposure denominator flags: 297.
- Low crash count flags: 1,658.
- Zero crash count flags: 831.
- Extremely wide interval flags: 1,951.
- Mixed AADT year flags: 362.
- Outside-period AADT year flags: 207.

All unit-level rate rows remain QA/review outputs only because prototype v1 carries the provisional bidirectional-AADT assumption. Stakeholder-safe tables are limited to aggregate window and signal-relative direction summaries with exact intervals and explicit caveats.

## Implemented Crash Count Modeling Readiness Dataset

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_modeling_readiness_dataset
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_modeling_readiness_dataset/`

Created outputs:

- `crash_count_modeling_matrix_signal_direction_window.csv`
- `crash_count_modeling_matrix_signal_direction_distance_band.csv`
- `exploratory_counts_by_distance_access.csv`
- `exploratory_counts_by_window_access.csv`
- `exploratory_counts_by_speed_access.csv`
- `exploratory_counts_by_aadt_access.csv`
- `exploratory_counts_by_distance_speed.csv`
- `exploratory_counts_by_distance_aadt.csv`
- `exploratory_counts_by_direction_distance_access.csv`
- `exploratory_counts_by_direction_speed_access.csv`
- `exploratory_rate_preview_by_distance_access.csv`
- `exploratory_rate_preview_by_window_access.csv`
- `candidate_model_feature_inventory.csv`
- `candidate_model_formula_spec.csv`
- `modeling_unit_quality_summary.csv`
- `modeling_readiness_warning_flags.csv`
- `crash_count_modeling_readiness_qa.csv`
- `crash_count_modeling_readiness_findings.md`
- `crash_count_modeling_readiness_manifest.json`

The package prepares future crash-count model inputs only. The intended future outcome is `assigned_crash_count`, with `log_estimated_exposure` prepared as an offset where denominator inputs are valid. It does not fit a Poisson model, negative-binomial model, predictive model, causal model, safety-performance ranking, danger/risk ranking, policy guidance, or downstream functional-area distance recommendation.

Current readiness result:

- Recommended first fitting grain: `reference_signal_id + signal_relative_direction + analysis_window`.
- Window matrix units: 3,222; denominator-ready units: 2,967.
- Distance-band matrix units: 7,797; denominator-ready units: 7,174.
- Window denominator-ready assigned crashes: 12,414 of 13,216.
- Distance-band denominator-ready assigned crashes: 12,413 of 13,216.
- Existing v1 `estimated_exposure = length_weighted_stable_AADT x represented_length_miles x 1,096 days`.
- Existing model-prep outputs do not apply `DIRECTION_FACTOR`; they need a v2 exposure/offset refresh before they are treated as current under the active denominator policy.
- AADT v1 bidirectional/provisional flags remain on existing model-prep rows as legacy/baseline evidence.
- AADT year mismatches are flagged, not automatically suppressed.
- Access density is recalculated at the local signal-direction-window or signal-direction-distance-band grain from summed catchment access count divided by summed represented length, not from raw 50-ft bin density.

Exploratory association findings:

- Access-density patterns differ by distance band/window.
- The 0-1,000 ft access pattern appears non-monotonic.
- The 1,000-2,500 ft access pattern appears monotonic after the zero-access group.
- Speed and AADT bands are usable candidate fields with caution; speed has missing/review units, and AADT remains provisional as both exposure input and possible covariate.

QA confirmed no crash direction fields were read or used, no rows beyond 2,500 ft entered, no `DIRECTION_FACTOR` was applied in the existing v1 readiness package, no model/regression was fit, no causal/policy/safety-performance/danger/risk language was introduced, local access density was used, exposure is denominator-gated, and high/exploding preview rates are flagged rather than hidden. A v2 readiness refresh is now required for active denominator use.

## Implemented Crash Count Model Specification Memo

Design memo:

`docs/design/roadway_graph_crash_count_model_specification.md`

Supporting output folder:

`work/output/roadway_graph/analysis/current/crash_count_model_specification/`

Created outputs:

- `candidate_model_sequence.csv`
- `model_variable_role_table.csv`
- `model_specification_qa.csv`
- `crash_count_model_specification_findings.md`
- `crash_count_model_specification_manifest.json`

The memo specifies the first exploratory crash-count model sequence only. It does not fit models, create predictions, make causal claims, create rankings, write policy guidance, or recommend downstream functional-area distances.

Specification result:

- First fitting grain: `reference_signal_id + signal_relative_direction + analysis_window`.
- Outcome: `assigned_crash_count`.
- Offset: `log_estimated_exposure`.
- First family: Poisson GLM.
- Follow-up family: negative-binomial GLM if overdispersion is present.
- Robust or clustered standard errors by `reference_signal_id` should be used if feasible.
- Zero-inflated models should wait until diagnostics justify them.

Primary predictor sequence:

- M0: exposure-only.
- M1: `analysis_window + signal_relative_direction`.
- M2: add `local_access_density_band`.
- M3: add `analysis_window x local_access_density_band`.
- M4: add `speed_band`.
- M5: optional sensitivity for `aadt_band` or simplified roadway representation.

The access interaction is motivated by the current readiness finding that the 0-1,000 ft access pattern appears non-monotonic while the 1,000-2,500 ft pattern appears monotonic after the zero-access group. AADT band is caution-only because AADT is already part of the exposure offset. Crash `AREA_TYPE` composition remains crash-level context, not roadway-level geography.

QA confirms no model was fit, no crash direction fields were used, no `DIRECTION_FACTOR` was applied, the sequence uses count outcome plus exposure offset, and the first model grain is signal-direction-window.

## Implemented Crash Count Exploratory Model Fit

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_exploratory_model_fit
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_exploratory_model_fit/`

Created outputs:

- `model_input_rows.csv`
- `model_input_excluded_rows.csv`
- `model_fit_summary.csv`
- `model_fit_coefficients.csv`
- `model_fit_incidence_rate_ratios.csv`
- `model_fit_diagnostics.csv`
- `model_overdispersion_summary.csv`
- `model_family_comparison.csv`
- `model_residual_summary.csv`
- `model_influence_review_queue.csv`
- `model_sparse_category_summary.csv`
- `model_convergence_warnings.csv`
- `model_interpretation_guardrails.csv`
- `crash_count_exploratory_model_fit_qa.csv`
- `crash_count_exploratory_model_fit_findings.md`
- `crash_count_exploratory_model_fit_manifest.json`

The module fits the first exploratory signal-direction-window crash-count sequence for internal technical review only. It uses `assigned_crash_count` as the outcome and `offset(log_estimated_exposure)`. It does not read crash direction fields, does not apply `DIRECTION_FACTOR`, does not fit distance-band-grain models, does not alter source/context/assignment data, does not create external decision outputs, and does not recommend downstream functional-area distances.

Current fit result:

- Package availability: `statsmodels`, `scipy`, and `patsy` are available.
- Modeled rows: 2,967 denominator-ready signal-direction-window rows.
- Excluded rows preserved: 255.
- Modeled assigned crashes: 12,414.
- Poisson sequence fit successfully for M0 through M4.
- Overdispersion is present; M4 Pearson overdispersion ratio is 7.004.
- Negative-binomial comparison was attempted, but Hessian/covariance warnings mean the current NB comparison is not usable for interpretation.
- The Poisson access-interaction model improved AIC compared with the add-access model; delta AIC for M3 versus M2 is -94.000.
- Speed is usable only with caution in the first sequence: missing/review speed is an explicit category, and the 60+ mph category is sparse.

Next refinement should review overdispersion handling, negative-binomial parameterization, stable-speed-only sensitivity, simplified roadway-representation sensitivity, and clustered/robust inference before any report-facing summary is drafted.

## Implemented Crash Count Model Refinement Sensitivity

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_model_refinement_sensitivity
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_model_refinement_sensitivity/`

Created outputs:

- `model_refinement_input_summary.csv`
- `negative_binomial_alpha_grid_comparison.csv`
- `poisson_overdispersion_adjusted_summary.csv`
- `robust_clustered_se_comparison.csv`
- `speed_category_sensitivity_summary.csv`
- `access_interaction_stability_summary.csv`
- `sparse_category_refinement_review.csv`
- `refined_model_fit_summary.csv`
- `refined_model_coefficients.csv`
- `refined_model_incidence_rate_ratios.csv`
- `refined_model_diagnostics.csv`
- `model_family_comparison.csv`
- `model_refinement_warnings.csv`
- `model_refinement_readiness_decision.csv`
- `model_refinement_sensitivity_qa.csv`
- `crash_count_model_refinement_sensitivity_findings.md`
- `crash_count_model_refinement_sensitivity_manifest.json`

This module is an internal exploratory refinement layer only. It does not read crash direction fields, does not apply `DIRECTION_FACTOR`, does not fit distance-band-grain models, does not create external decision outputs, does not rank locations, does not alter source/context/assignment data, and does not recommend downstream functional-area distances.

Current refinement result:

- Modeled rows: 2,967 denominator-ready signal-direction-window rows.
- Modeled assigned crashes: 12,414.
- Fixed-alpha negative-binomial GLM sensitivities with alpha values 0.25, 0.5, 1.0, and 2.0 fit without covariance warnings, but they remain sensitivity fits and do not validate the earlier unstable estimated-alpha NB coefficients.
- Estimated-alpha negative-binomial model is not ready for internal interpretation.
- Scaled, robust, and cluster-robust Poisson standard-error variants are feasible.
- The access interaction improved AIC in all tested sensitivity comparisons.
- The 60+ mph speed category remains sparse in the primary and stable-speed-only categories; merging 50-59 mph and 60+ mph removes that sparse speed category in the merged-speed sensitivity.
- Readiness decision: `requires_category_simplification`.
- Recommended internal model direction: merged-speed scaled and cluster-robust Poisson after category simplification, with fixed-alpha NB retained as sensitivity evidence only.

No output from this refinement package is stakeholder-ready. Any coefficient-level interpretation must wait for category simplification, overdispersion handling review, and cluster/robust inference review.

## Implemented Crash Count Simplified Internal Model

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_simplified_internal_model
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model/`

Created outputs:

- `simplified_model_input_rows.csv`
- `simplified_model_input_excluded_rows.csv`
- `simplified_category_mapping.csv`
- `simplified_sparse_category_summary.csv`
- `simplified_model_fit_summary.csv`
- `simplified_model_coefficients.csv`
- `simplified_model_incidence_rate_ratios.csv`
- `simplified_model_clustered_se_comparison.csv`
- `simplified_model_overdispersion_summary.csv`
- `simplified_model_family_comparison.csv`
- `simplified_nb_alpha_sensitivity.csv`
- `simplified_access_interaction_summary.csv`
- `simplified_speed_sensitivity_summary.csv`
- `simplified_model_interpretation_guardrails.csv`
- `simplified_model_readiness_decision.csv`
- `simplified_model_input_summary.csv`
- `simplified_model_warnings.csv`
- `simplified_model_qa.csv`
- `crash_count_simplified_internal_model_findings.md`
- `crash_count_simplified_internal_model_manifest.json`

This module creates the first category-simplified internal technical review model package. It keeps the signal-direction-window grain, uses denominator-ready rows only, uses `assigned_crash_count` with `offset(log_estimated_exposure)`, does not read crash direction fields, does not apply `DIRECTION_FACTOR`, does not fit distance-band-grain models, does not alter source/context/assignment data, does not create external decision outputs, and does not recommend downstream functional-area distances.

Current simplified-model result:

- Modeled rows: 2,967.
- Modeled assigned crashes: 12,414.
- Preserved excluded rows: 255.
- Category simplification: 50-59 mph and 60+ mph are merged into `50+ mph`; missing/review speed remains explicit.
- Remaining sparse category rows after simplification: 0.
- Access interaction remains useful after simplification; scaled-Poisson delta AIC for `S2_access_interaction` versus `S1_window_direction` is -36.752.
- Adding simplified speed improves fit; scaled-Poisson delta AIC for `S3_access_interaction_speed_simplified` versus `S2_access_interaction` is -59.901.
- Poisson, overdispersion-adjusted Poisson, robust Poisson, cluster-robust Poisson, and fixed-alpha negative-binomial sensitivity models were fit.
- Readiness decision: `access_speed_model_ready_internal_only`.
- Recommended internal model: `S3_access_interaction_speed_simplified` with scaled and cluster-robust Poisson inference.

The simplified model is for internal technical review only. Stakeholder interpretation remains blocked until denominator assumptions, AADT directionality, model diagnostics, and reporting language are reviewed.

## Active V2/V5 Crash Count Simplified Internal Model Rerun

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_simplified_internal_model_active
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model_active/`

This rerun uses the active v2/v5 window-grain modeling-readiness matrix and active speed v5 bands derived from the active combined context table. It does not fit distance-band models, create predictions, create rankings, modify source/context/assignment data, or introduce causal, policy, risk, safety-performance, or downstream-distance guidance language.

Current active result:

- Modeled rows: 2,967 denominator-ready signal-direction-window rows.
- Modeled assigned crashes: 12,414.
- Access interaction remains useful; scaled-Poisson delta AIC for `S2_access_interaction` versus `S1_window_direction` is -26.269.
- Simplified speed remains useful; scaled-Poisson delta AIC for `S3_access_interaction_speed_simplified` versus `S2_access_interaction` is -16.439.
- S3 scaled-Poisson Pearson overdispersion ratio is 6.894, so overdispersion remains.
- Scaled and cluster-robust Poisson remain the primary internal-review family.
- Fixed-alpha NB remains sensitivity evidence only; active estimated-alpha NB stabilization was rerun separately and did not replace the Poisson-family primary decision.

The prior `crash_count_simplified_internal_model/` package is retained as baseline/history.

## Active V2/V5 Negative-Binomial Stabilization Diagnostic

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_negative_binomial_stabilization_active
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_negative_binomial_stabilization_active/`

This diagnostic uses only denominator-ready active signal-direction-window rows, `assigned_crash_count` as the outcome, the active `log_estimated_exposure` offset, active speed v5 simplified categories, and the same simplified model sequence. It does not apply any additional `DIRECTION_FACTOR`, fit distance-band models, create predictions, create rankings, alter source/context/assignment data, or introduce causal, policy, risk, safety-performance, or downstream-distance guidance language.

Created outputs:

- `active_nb_stabilization_input_summary.csv`
- `active_estimated_alpha_nb_sequence_summary.csv`
- `active_estimated_alpha_nb_coefficients.csv`
- `active_estimated_alpha_nb_irrs.csv`
- `active_estimated_alpha_nb_warning_log.csv`
- `active_fixed_alpha_nb_sequence_summary.csv`
- `active_fixed_alpha_nb_irrs.csv`
- `active_poisson_vs_nb_comparison.csv`
- `active_nb_access_interaction_stability.csv`
- `active_nb_speed_term_stability.csv`
- `active_vs_baseline_nb_comparison.csv`
- `active_nb_model_readiness_decision.csv`
- `active_negative_binomial_stabilization_qa.csv`
- `crash_count_negative_binomial_stabilization_active_findings.md`
- `crash_count_negative_binomial_stabilization_active_manifest.json`

Current active result:

- Estimated-alpha NB is interpretable for `NB0_exposure_only_active` and `NB3_access_interaction_no_speed_active`.
- `NB1_window_direction_active`, `NB2_add_access_no_interaction_active`, and `NB4_access_interaction_speed_simplified_active` remain unstable or have incomplete covariance; NB4 does not converge.
- Fixed-alpha NB fits succeed across alpha 0.25, 0.5, 1.0, and 2.0.
- Fixed-alpha NB supports the access-window interaction and simplified speed as sensitivity evidence.
- Active v2/v5 improves estimated-alpha NB stability versus baseline, but not enough to replace scaled and cluster-robust Poisson.
- Readiness decision: `active_robust_poisson_primary_nb_sensitivity`.
- Stakeholder interpretation remains blocked.

## Implemented Internal Crash Count Model Review Memo

Memo:

`docs/reports/roadway_graph/internal_model_technical_review_memo.md`

Supporting output folder:

`work/output/roadway_graph/analysis/current/crash_count_internal_model_review/`

Created outputs:

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

The memo translates the existing category-simplified model outputs into an internal technical review record. It does not fit new models, use crash direction fields, apply `DIRECTION_FACTOR` in the existing v1 exposure offset, fit distance-band models, alter source/context/assignment data, create stakeholder-facing conclusions, create rankings, make causal claims, or recommend downstream functional area distances.

Current review result:

- Selected internal model: `S3_access_interaction_speed_simplified`.
- Inference focus: scaled Poisson and cluster-robust Poisson.
- Fixed-alpha negative-binomial fits remain sensitivity evidence only.
- Overdispersion remains present and requires explicit review.
- Existing internal model outputs use the older v1 bidirectional/provisional exposure, with `DIRECTION_FACTOR` unapplied; they need a v2 offset refresh before active denominator interpretation.
- Stakeholder interpretation remains blocked.

## Implemented Baseline Internal Crash Count Model Figures

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_internal_model_figures
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_internal_model_figures/`

Cleaned presentation SVGs and docs:

`docs/reports/roadway_graph/modeling_figures/`

Created source-table outputs:

- `internal_model_irr_plot_data.csv`
- `internal_model_access_interaction_plot_data.csv`
- `internal_model_speed_effect_plot_data.csv`
- `internal_model_diagnostic_plot_data.csv`
- `internal_model_inference_comparison_plot_data.csv`
- `internal_model_figure_qa.csv`
- `internal_model_figure_manifest.json`

Baseline review SVGs were later cleaned into `docs/reports/roadway_graph/modeling_figures/`:

- `internal_model_irr_forest_plot.svg`
- `internal_model_access_interaction_forest_plot.svg`
- `internal_model_speed_effect_forest_plot.svg`
- `internal_model_diagnostic_summary.svg`
- `internal_model_inference_comparison.svg`

The figure package is internal technical review only. It visualizes baseline selected-model coefficient, IRR, and diagnostic outputs without fitting new models or changing model specification, rate methodology, source data, context data, assignment data, or stakeholder-facing report conclusions. These figures predate the active v2/v5 model refresh and should be treated as baseline/historical until regenerated from active outputs. It does not use crash direction fields, does not create policy predictions, and does not support causal claims, rankings, safety-performance language, risk/danger language, or downstream functional area distance recommendations.

## Implemented Baseline Negative-Binomial Stabilization Diagnostic

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_negative_binomial_stabilization
```

Output folder:

`work/output/roadway_graph/analysis/current/crash_count_negative_binomial_stabilization/`

Created outputs:

- `nb_stabilization_input_summary.csv`
- `estimated_alpha_nb_sequence_summary.csv`
- `estimated_alpha_nb_coefficients.csv`
- `estimated_alpha_nb_irrs.csv`
- `estimated_alpha_nb_warning_log.csv`
- `fixed_alpha_nb_sequence_summary.csv`
- `fixed_alpha_nb_irrs.csv`
- `poisson_vs_nb_comparison.csv`
- `nb_access_interaction_stability.csv`
- `nb_speed_term_stability.csv`
- `nb_model_readiness_decision.csv`
- `crash_count_negative_binomial_stabilization_findings.md`
- `negative_binomial_stabilization_qa.csv`
- `crash_count_negative_binomial_stabilization_manifest.json`

The diagnostic is read-only and stays at the denominator-ready signal-direction-window grain. It uses `assigned_crash_count` as outcome, `log_estimated_exposure` as offset, and the same simplified S3 categories. Estimated-alpha negative-binomial models are attempted from exposure-only through access-interaction-plus-speed complexity, while fixed-alpha NB sensitivities are run at alpha 0.25, 0.5, 1.0, and 2.0.

Current diagnostic result:

- Estimated-alpha NB is not interpretable even at `NB0_exposure_only` because covariance/Hessian behavior is unstable.
- `NB4_access_interaction_speed_simplified` does not converge and returns an unusable alpha estimate.
- Fixed-alpha NB fits succeed across the requested grid and model sequence.
- Fixed-alpha NB supports the access-window interaction and simplified speed as sensitivity evidence.
- Readiness decision: `robust_poisson_primary_nb_sensitivity`.
- Preferred internal model family remains scaled and cluster-robust Poisson, with fixed-alpha NB retained as sensitivity evidence only.
- Stakeholder interpretation remains blocked.

## Active Internal Modeling Conclusion And Presentation Readiness

Memo:

`docs/reports/roadway_graph/internal_modeling_conclusion_and_presentation_readiness.md`

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.internal_modeling_conclusion_readiness_active
```

Active supporting output folder:

`work/output/roadway_graph/analysis/current/internal_modeling_conclusion_readiness_active/`

Created active outputs:

- `active_internal_modeling_conclusion_summary.csv`
- `active_model_family_readiness_table.csv`
- `active_presentable_internal_artifacts_table.csv`
- `active_blocked_stakeholder_claims_table.csv`
- `active_recommended_next_steps_modeling.csv`
- `active_internal_modeling_conclusion_manifest.json`

The active conclusion memo is a synthesis and presentation-readiness document only. It does not fit new models, compute rates, use crash direction fields, apply any additional `DIRECTION_FACTOR`, include rows beyond 2,500 ft, create predictions, create rankings, make causal/safety-performance/risk/policy claims, update stakeholder report conclusions, or recommend downstream functional area distances.

Current active conclusion:

- Active v2/v5 replaces the prior v1/v4 baseline for current internal modeling review.
- Preferred active internal model: `S3_access_interaction_speed_simplified`.
- Preferred internal family: scaled and cluster-robust Poisson primary.
- Fixed-alpha negative-binomial remains sensitivity evidence only.
- Estimated-alpha negative-binomial improved versus baseline but is not stable for `NB4_access_interaction_speed_simplified_active`, so it does not replace Poisson-family inference.
- Active access-window interaction and simplified speed remain useful, but both are weaker than in the baseline v1/v4 model.
- Active internal artifacts are review-ready for technical discussion only.
- Stakeholder model findings remain blocked.

The prior `internal_modeling_conclusion_readiness/` package is retained as baseline/history.

## Implemented Model Presentation Figure Subset

Command:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_model_presentation_figures
```

Output folder:

`work/output/roadway_graph/report/current/model_presentation_figures/`

Docs and review SVG copies:

`docs/reports/roadway_graph/modeling_figures/`

Main presentation subset:

- `model_presentation_model_summary.svg`
- `model_presentation_access_interaction.svg`
- `model_presentation_speed_context.svg`

Appendix/internal figures:

- `model_appendix_full_irr_forest_plot.svg`
- `model_appendix_inference_comparison.svg`
- `model_appendix_diagnostic_summary.svg`

The package refines figure labels, spacing, and titles for internal team discussion only. It does not fit new models, change methodology, compute rates, update stakeholder report conclusions, create predictions, create rankings, make causal/safety-performance/risk/policy claims, or recommend downstream functional area distances.

## Earlier Planned Output Tables

### `reference_signal_descriptive_summary.csv`

Unit:

- one row per reference signal.

Minimum fields:

- reference signal ID
- total directional bins
- bin counts by high-priority and sensitivity windows
- assigned crash counts by high-priority and sensitivity windows
- upstream and downstream assigned crash counts
- access counts and access density by window
- stable speed bin coverage
- stable AADT bin coverage
- assigned crash urban/rural counts
- roadway urban/rural status
- review flags

### `signal_direction_window_summary.csv`

Unit:

- one row per reference signal, signal-relative direction, and distance window.

Minimum fields:

- reference signal ID
- signal-relative direction
- distance window
- directional bin count
- represented length in feet
- assigned crash count
- access count
- access density per 1,000 ft
- stable speed context count and share
- stable AADT context count and share
- urban/rural assigned crash counts
- context quality class

### `distance_band_context_summary.csv`

Unit:

- one row per descriptive distance band and grouping.

Recommended first bands:

- 0-250 ft
- 250-500 ft
- 500-1,000 ft
- 1,000-1,500 ft
- 1,500-2,500 ft

Recommended groupings:

- all bins
- signal-relative direction
- roadway representation type
- high-priority versus sensitivity window

### `crash_context_descriptive_summary.csv`

Unit:

- grouped assigned-crash summary.

Recommended groupings:

- functional distance window
- signal-relative direction
- roadway representation type
- crash urban/rural class
- inherited access count class
- inherited speed class
- inherited AADT class

### `signal_review_queue.csv`

Unit:

- one row per reference signal with at least one review trigger.

Recommended trigger fields:

- high 0-1,000 ft crash count
- high downstream 0-1,000 ft crash count
- high downstream access density
- high crash count plus high access density
- large upstream/downstream imbalance
- missing or review speed burden
- missing or review AADT burden
- sensitivity-window-heavy crash burden
- no roadway-level urban/rural caveat

Trigger thresholds should be transparent constants in the module or config. They should be described as review triggers, not statistical outlier definitions.

### `directional_context_descriptive_qa.csv`

Unit:

- one row per QA check.

Minimum QA checks:

- input row counts match current product counts
- no >2,500 ft bins enter main summaries
- crash counts sum to 13,216
- signal count remains 971
- bin-level urban/rural crash summary counts sum to assigned crashes
- speed and AADT stable counts match combined context QA
- access count comparison matches combined context QA
- context fields did not redefine upstream/downstream
- crash direction fields were not used

### `directional_context_descriptive_findings.md`

Purpose:

- human-readable summary of the descriptive analysis output
- explicit limitations
- recommended review queues
- statement that outputs are descriptive, not policy-ready

### `directional_context_descriptive_manifest.json`

Purpose:

- timestamp, inputs, outputs, row counts, QA results, constants, and methodological boundaries

## Analysis Rules

- Use only current accepted context outputs.
- Do not rerun source joins.
- Do not read crash direction fields.
- Do not modify scaffold, catchments, crash assignment, access, speed, AADT, or urban/rural source logic.
- Do not infer roadway urban/rural from assigned crashes.
- Do not populate no-crash bins with crash `AREA_TYPE`.
- Keep >2,500 ft assignment rows out of main outputs.
- Preserve review/missing flags for speed and AADT.
- Treat access density as descriptive context, not as a rate claim unless denominator handling is explicitly documented.

## Descriptive Metrics

Recommended metrics:

- assigned crash count
- assigned crash count by upstream/downstream
- assigned crash count by high-priority and sensitivity windows
- assigned crash urban/rural composition
- access count
- access density per 1,000 ft represented bin length
- nearest access distance summary where available
- stable speed context share
- speed class distribution
- stable AADT context share
- AADT class distribution
- roadway representation mix
- review/missing context burden

Avoid:

- crash rates
- expected crash estimates
- regression-ready variables
- policy-distance claims
- causal wording

## Stakeholder-Ready Readouts

The implemented first stakeholder table package includes:

- a table index
- a compact summary overview
- a top signal review-priority queue
- top signal-direction profiles by assigned crash burden
- fixed distance-band summaries
- context-completeness summaries
- a visible limitations table
- package QA and manifest outputs

The package does not include a methodology memo, final report narrative, figures, maps, GeoJSON, crash rates, model outputs, regressions, or policy guidance.

The implemented exposure/modeling-readiness audit adds denominator-readiness tables, feature-matrix scaffolds, duplicate source-bin checks, and descriptive cross-tabs for stakeholder discussion. It remains a readiness audit only and does not authorize rates or models.

The implemented rate-denominator policy package adds a memo and machine-readable specification for a future descriptive rate prototype. It remains a policy gate only and does not authorize rate calculation until the remaining denominator assumptions are approved.

The implemented rate-assumption approval v1 package approves those remaining assumptions only for a future window-grain descriptive prototype. It is still not itself a rate table.

The implemented descriptive crash-rate prototype creates the first window-grain AADT-normalized descriptive rate table under the approved assumptions. It remains provisional and should be used for denominator behavior review and stakeholder discussion only.

The implemented prototype QA package reviews rate distribution, high-rate artifact concerns, non-ready unit exclusion reasons, AADT-year flags, and interpretation readiness without changing the prototype method.

The implemented suppression review refines uncertainty intervals with SciPy exact Garwood intervals and separates stakeholder-safe aggregate summaries from unit-level QA review rows.

## Implemented Report Planning Documents

Current report planning and draft documents live under `docs/reports/roadway_graph/`:

- `roadway_graph_methodology_limitations_memo.md`
- `roadway_graph_figure_inventory_and_specs.md`
- `roadway_graph_report_outline.md`
- `roadway_graph_descriptive_report_draft.md`
- `roadway_graph_figure_index.md`
- `roadway_graph_report_qa.md`

The generated report draft and figures use accepted descriptive outputs only. They do not create crash rates, AADT-normalized comparisons, models, regressions, predictions, causal findings, or final design recommendations.

## QA Before Stakeholder Use

Before sharing, verify:

- combined context QA still passes
- new summary row counts match input counts
- review queues are threshold-based and not labeled as statistical outliers
- every table states whether it is signal-level, direction-window-level, bin-level, or crash-level
- limitations are visible in the first readout, not only in appendices

## Implementation Order

1. Review the first descriptive summary tables, signal review queue, distance-band profiles, signal-direction profiles, stakeholder table package, and QA.
2. Review the compact stakeholder tables manually before designing policy/literature band families.
3. Decide whether to add a methodology or limitations memo from generated outputs.
4. Decide production-hardening scope.
5. Review the exposure/modeling-readiness audit before any denominator prototype.
6. Review the bounded window-grain descriptive rate prototype QA and high-rate review queues.
7. Decide whether to refine denominator rules, AADT-year handling, or directional exposure before any fixed-band rate prototype.
8. Define modeling-readiness requirements before any regression or policy claim.
9. Review the internal crash-count model memo before any coefficient visualization, distance-band sensitivity, or report-facing model language.
10. Review the internal model figure package manually before any later model-language or visualization approval.
11. Treat fixed-alpha negative-binomial results as sensitivity evidence unless a future bounded diagnostic stabilizes estimated-alpha NB with usable covariance.
12. Use the internal modeling conclusion memo to decide whether a stakeholder report should include only a high-level modeling-status paragraph.

## Non-Goals

- no modeling
- no regression
- no crash-rate claims
- no Appendix F recommendations
- no spreadsheet calculator
- no new graph repair
- no new source recovery
- no use of crash direction fields
- no context-derived upstream/downstream relabeling
