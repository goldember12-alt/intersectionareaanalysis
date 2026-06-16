# Final Analysis Dataset Contract

Status: active review-analysis contract.

Canonical path:

`work/output/roadway_graph/analysis/current/final_leg_corrected_analysis_dataset/`

Review pointer:

`work/output/roadway_graph/review/current/final_analysis_dataset_pointer/`

Future table, figure, access, crash, and guidance-matrix prompts should read the canonical analysis dataset first before searching branch-specific review outputs.

Primary tables:

- `analysis_signal.csv`: one row per final clean review-analysis signal.
- `analysis_bin.csv`: one row per final leg-corrected bin.
- `analysis_signal_window.csv`: one row per signal and analysis window.
- `analysis_signal_approach_window.csv`: one row per signal approach and analysis window.
- `analysis_guidance_matrix_long.csv`: grouped figure-ready guidance-matrix table.
- `analysis_data_dictionary.csv`: plain-language field definitions and caveats.

The dataset is review-only. It does not modify active outputs, promote records, rerun signal recovery, rerun access assignment, rerun crash assignment, calculate final rates/models, or use crash direction fields.

Numeric speed, AADT, and exposure are carried where existing review sources support them. Missing numeric context remains explicit and should be handled in figures. Candidate exposure is review-only and is not a final rate denominator policy.

Access is carried as raw access counts and count bands. Access density is secondary only.

Crash context carries both the spatial 50 ft primary review product and the identity-compatible spatial 50 ft sensitivity product. Spatial 50 ft remains the primary geometry/catchment product.

Enhanced context package:

`work/output/roadway_graph/analysis/current/final_analysis_directional_numeric_context_enhancement/`

This package should be used when a prompt needs the latest numeric speed/AADT/exposure completeness or explicit directionality fields. It supplements the canonical bin context with exact route/measure interval matches from prior RNS Phase 3D and AADT v3 assignment details, and it carries conservative directionality fields.

Directionality caveat: true downstream/upstream traffic-flow roles are not fully restored in the current canonical scaffold. The enhanced package preserves source bearing context where available and labels unsupported bins as `bidirectional_or_undirected` or `unclear_direction`. Do not treat those labels as downstream/upstream flow orientation, and do not use crash direction fields to infer flow.

Directionality doctrine package:

`work/output/roadway_graph/analysis/current/final_analysis_directionality_doctrine/`

This package is the current review-only doctrine for downstream/upstream feasibility. It does not assign final downstream/upstream labels. It separates bins into direct divided/one-way candidates, undivided centerline synthesis candidates, ramp/interchange review cases, and insufficient-evidence cases. Future downstream/upstream implementation should start with a bounded direct divided-road pilot, then build and validate undivided centerline synthetic direction logic. Crash direction fields remain excluded from scaffold directionality.

Direct divided/one-way directionality Phase 1:

`work/output/roadway_graph/analysis/current/final_analysis_direct_divided_directionality/`

This package provides review-only downstream/upstream labels for the direct divided-row and one-way-row candidate subset only. It preserves the target bins, Travelway flow evidence, direct bin labels, signal/approach/window summaries, QA checks, examples, and next-action recommendation. It should not be interpreted as global downstream/upstream coverage. Undivided centerlines still require synthetic directionality, and ramp/interchange or insufficient-evidence rows remain out of scope. Crash direction fields remain excluded.

Direct directionality uncertainty audit:

`work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_uncertainty_audit/`

This package decomposes the Phase 1 direct divided/one-way bins that remained uncertain or not assignable. It is diagnostic only and does not assign new downstream/upstream labels. Future relaxed direct-rule work should review this package first, especially the route suffix/geometry conflict examples, recoverability estimates, and signal/approach gap summary. Undivided centerline synthesis remains a separate Phase 2 problem.

Direct directionality relaxed recovery:

`work/output/roadway_graph/analysis/current/final_analysis_direct_directionality_relaxed_recovery/`

This package applies documented relaxed rules to recoverable direct divided/one-way uncertainty bins and creates a combined direct divided/one-way directionality detail table. It excludes map-review rows and rows that should remain uncertain, and it does not assign undivided centerline directionality. The recovered labels are review-only and should be map-reviewed before canonical integration. Phase 2 undivided centerline synthesis remains unresolved.

Undivided centerline synthetic directionality:

`work/output/roadway_graph/analysis/current/final_analysis_undivided_centerline_directionality/`

This package creates paired upstream/downstream interpretation rows for undivided centerline bins where signal-centered approach geometry is sufficient. These are logical interpretations of one bidirectional centerline, not separate source Travelway rows and not single direct labels. They are suitable for review-only roadway context summaries. They are not ready for directional crash assignment; synthetic rows are explicitly marked `context_only_not_directional_crash_assignment` until a crash-direction-independent assignment rule is separately defined and validated.

Directionality coverage audit:

`work/output/roadway_graph/analysis/current/final_analysis_directionality_coverage_audit/`

This package audits direct divided/one-way labels and undivided synthetic interpretation coverage against the full canonical bin universe. Future canonical directionality integration should read this audit first. The current directionality layer is suitable for review-only context summaries, but directional crash/access analysis remains blocked until a separate crash-direction-independent assignment rule is defined and validated.

Residual directionality recovery:

`work/output/roadway_graph/analysis/current/final_analysis_residual_directionality_recovery/`

This package is the latest review-only directionality coverage source before canonical integration. It conservatively recovers additional undivided synthetic-unclear bins, diagnoses ramp/interchange missingness, preserves true grade-separated/mainline holdouts as unassigned, and writes the current residual map-review queue. Directionality remains context-ready, not crash/access assignment-ready.

Ramp/interchange directionality recovery:

`work/output/roadway_graph/analysis/current/final_analysis_ramp_interchange_directionality_recovery/`

This package is the latest ramp/interchange-specific review layer. It recovers low-risk signal-relevant ramp-terminal, frontage/service, and surface-interchange bins while preserving true grade-separated/mainline and unresolved mixed ramp/mainline rows as uncovered. It should be read before any canonical directionality integration or map-review package creation. Directionality remains context-ready only.

Final residual directionality decomposition and recovery:

`work/output/roadway_graph/review/current/final_residual_directionality_decomposition_recovery/`

This package is an exploratory review/current pre-map-review recovery layer over the remaining uncovered directionality bins after ramp/interchange recovery. It recovers only candidate direct residual labels and paired synthetic undivided interpretation rows where final residual rules have sufficient non-crash evidence. It is not a canonical analysis product. Future canonical directionality integration should read this package only after deciding to accept the candidate recovered labels, and directional crash/access splitting remains blocked until a separate crash-direction-independent assignment rule is defined and validated.

Final residual directionality composition audit:

`work/output/roadway_graph/review/current/final_directionality_residual_composition_audit/`

This package is the pre-map-review residual audit for the latest 34,358 uncovered directionality bins. It does not assign new labels. It should be used to decide whether to design one more targeted automated rule pass, prepare map-review examples, or integrate accepted candidate directionality with explicit holdout flags. The audit currently finds no immediate automatable recovery queue, but it identifies a 6,672-row specific-rule-design queue and separates map-review, source/geometry limitation, grade/mainline holdout, policy-hold, and data-debug cases.

Specific-rule feasibility for residual directionality:

`work/output/roadway_graph/review/current/final_directionality_specific_rule_feasibility/`

This package scores the 6,672 residual rows that need specific rule design. It does not assign labels. It should be read before any new automated recovery implementation. The current highest-yield candidate is a direct route/measure borderline rule, but even that rule is recommended only after sample map review. Synthetic approach-grouping and relaxed-axis rules remain context-only candidates. Mixed ramp/mainline rows remain too small and risky for automated implementation without review.
