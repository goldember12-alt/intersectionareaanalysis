# Stage 2 Oracle-Safe Branch Traceability Map

This map records the active bounded Oracle-safe branch from bridge-bearing identity recovery through the current Stage 1C completed slice.

## How to Read This Map

- `Command` is the repo-root entrypoint run with `.\.venv\Scripts\python.exe -m stage1_portable ...`
- `Module` is the producing implementation file
- `Inputs` are the authoritative upstream artifact(s) for that step
- `Outputs` are the primary artifact(s) produced by that step
- `QC note` is the key bounded meaning or validation focus of the step

## Traceability Table

| Phase | Command | Module | Inputs | Outputs | QC note |
|---|---|---|---|---|---|
| Identity recovery | `restore-study-roads-parent-linkid-normalized-routekey` | `stage1_portable/stage1b_study_roads_link_restoration_normalized_route_key.py` | restored study-road parent lineage inputs | `Study_Roads_Divided_LinkRestored_NormalizedRouteKey.parquet` | Retries bounded bridge-bearing restoration using normalized route-key matching without downstream inheritance. |
| Identity recovery | `inherit-stage1b-segment-link-identity` | `stage1_portable/stage1b_segment_link_inheritance.py` | `Study_Roads_Divided_LinkRestored_NormalizedRouteKey.parquet` plus downstream segment Oracle-prep boundary | `Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep_LinkInherited.parquet` | Deterministically carries restored bridge-bearing identity into the downstream segment branch. |
| Bounded Oracle match | `reaudit-stage1b-segment-oracle-matching-contract` | `stage1_portable/stage1b_segment_oracle_matching_contract_resumed.py` | inherited segment Oracle-prep boundary | `Functional_Segments_OracleMatchingContract_Resumed.parquet` | Reassesses Oracle matching readiness on the inherited bridge-bearing subset without performing matching. |
| Bounded Oracle match | `execute-stage1b-segment-oracle-true-match-ready-subset` | `stage1_portable/stage1b_segment_oracle_true_match_ready_subset.py` | resumed matching contract, Oracle segment-ready handoff, Oracle lookup rows | `Functional_Segments_OracleTrueMatch_ReadySubset.parquet` | Executes the authoritative bounded Oracle true-match only on the ready subset. |
| Bounded Oracle match | `audit-stage1b-segment-oracle-true-match-ready-subset-stability` | `stage1_portable/stage1b_segment_oracle_true_match_ready_subset_stability_audit.py` | `Functional_Segments_OracleTrueMatch_ReadySubset.parquet` | `Functional_Segments_OracleTrueMatch_ReadySubset_StabilityAudit.parquet` | Separates stable rows from unresolved rows and preserves quarantine. |
| Safe subset | `define-stage1b-segment-oracle-downstream-safe-subset` | `stage1_portable/stage1b_segment_oracle_matched_downstream_safe_subset.py` | `Functional_Segments_OracleTrueMatch_ReadySubset_StabilityAudit.parquet` | `Functional_Segments_OracleMatched_DownstreamSafeSubset.parquet` | Defines the exact 77-row downstream-safe boundary while preserving strict versus caution. |
| Packaging ladder | `define-stage1b-segment-oracle-downstream-safe-consumer-handoff` | `stage1_portable/stage1b_segment_oracle_downstream_safe_consumer_handoff.py` | downstream-safe subset | `Functional_Segments_OracleMatched_DownstreamSafeConsumerHandoff.parquet` | Formalizes allowed versus disallowed later consumer use. |
| Packaging ladder | `build-stage1b-segment-oracle-downstream-safe-consumer-staging` | `stage1_portable/stage1b_segment_oracle_downstream_safe_consumer_staging.py` | consumer handoff | `Functional_Segments_OracleMatched_DownstreamSafeConsumerStaging.parquet` | Creates a consumer-ready staging boundary without directionality. |
| Packaging ladder | `build-stage1b-segment-oracle-downstream-safe-analytical-context` | `stage1_portable/stage1b_segment_oracle_downstream_safe_analytical_context.py` | consumer staging | `Functional_Segments_OracleMatched_DownstreamSafeAnalyticalContext.parquet` and summaries | Turns the 77-row branch into a bounded analytical context bundle. |
| Packaging ladder | `build-stage1b-segment-oracle-downstream-safe-review` | `stage1_portable/stage1b_segment_oracle_downstream_safe_review.py` | analytical context | `Functional_Segments_OracleMatched_DownstreamSafeReview.parquet` and summaries | Adds review grouping and prioritization metadata. |
| Packaging ladder | `build-stage1b-segment-oracle-downstream-safe-triage` | `stage1_portable/stage1b_segment_oracle_downstream_safe_triage.py` | review boundary | `Functional_Segments_OracleMatched_DownstreamSafeTriage.parquet` and summaries | Adds triage-oriented inspection metadata. |
| Packaging ladder | `build-stage1b-segment-oracle-downstream-safe-decision-support` | `stage1_portable/stage1b_segment_oracle_downstream_safe_decision_support.py` | triage boundary | `Functional_Segments_OracleMatched_DownstreamSafeDecisionSupport.parquet` and summaries | Adds recommended-action metadata for bounded decision support. |
| Stage 1B closure | `build-stage1b-oracle-safe-subset-closure-handoff` | `stage1_portable/stage1b_oracle_safe_subset_closure_handoff.py` | decision-support boundary and summaries | `Functional_Segments_OracleMatched_Stage1B_ClosureHandoff.parquet` and summary | Closes the bounded Stage 1B Oracle-safe branch and defines the Stage 1C handoff. |
| Stage 1C consumerization | `build-stage1c-nondirectional-consumer-slice` | `stage1_portable/stage1c_nondirectional_consumer_slice.py` | Stage 1B closure/handoff boundary and summary | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerSlice.parquet` and summary | Proves the branch can feed a runnable non-directional Stage 1C consumer slice. |
| Stage 1C consumerization | `build-stage1c-nondirectional-consumer-output` | `stage1_portable/stage1c_nondirectional_consumer_output.py` | consumer slice | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerOutput.parquet` and summary | First real consumer-facing derived output layer. |
| Stage 1C consumerization | `build-stage1c-nondirectional-minislice` | `stage1_portable/stage1c_nondirectional_minislice.py` | consumer output | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalMiniSlice.parquet` and summary | First bounded runnable non-directional Stage 1C mini-slice. |
| Stage 1C evaluation | `audit-stage1c-capability-gap` | `stage1_portable/stage1c_capability_gap_audit.py` | mini-slice and summary | `Functional_Segments_OracleMatched_Stage1C_CapabilityGapAudit.parquet` and summary | States that crash/access-relevant integration remains the realistic bounded gap. |
| Stage 1C readiness | `define-stage1c-crash-access-readiness-contract` | `stage1_portable/stage1c_crash_access_readiness_contract.py` | capability/gap audit and summary | `Functional_Segments_OracleMatched_Stage1C_CrashAccessReadinessContract.parquet` and summary | Records that geometry and lineage are present, but crash/access source fields are not yet staged. |
| Stage 1C readiness | `define-stage1c-crash-access-staging-contract` | `stage1_portable/stage1c_crash_access_staging_contract.py` | readiness contract and summary; normalized crashes/access | `Functional_Segments_OracleMatched_Stage1C_CrashAccessStagingContract.parquet` and summary | Brings normalized crash/access source-boundary fields into bounded scope without assignment. |
| Stage 1C readiness | `audit-stage1c-crash-access-join` | `stage1_portable/stage1c_crash_access_join_audit.py` | staging contract and summary; normalized crashes/access | `Functional_Segments_OracleMatched_Stage1C_CrashAccessJoinAudit.parquet` and summary | Audits whether crash/access candidates can land cleanly enough for later bounded assignment. |
| Stage 1C completion | `build-stage1c-nondirectional-completed-slice` | `stage1_portable/stage1c_nondirectional_completed_slice.py` | join-audit boundary and summary; normalized crashes | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet` and summary | Completes crash-side Stage 1C work where justified and explicitly holds access back. |

## Architectural Grouping

The branch is easier to maintain when read as five conceptual groups instead of a flat command list:

1. `Identity recovery`
2. `Bounded Oracle match`
3. `Safe subset and packaging ladder`
4. `Stage 1C consumerization`
5. `Stage 1C crash/access completion`

## Stage 2 Interpretation

This map shows two kinds of layers:

- analytically meaningful boundaries:
  - restoration
  - resumed matching
  - true-match execution
  - stability audit
  - crash/access readiness and completion boundaries
- packaging and handoff layers:
  - consumer handoff
  - staging
  - analytical context
  - review
  - triage
  - decision-support
  - closure/handoff
  - consumer slice/output/minislice

Stage 2 cleanup should preserve both kinds of outputs, but can document and group the packaging ladder more clearly so future maintainers do not mistake those layers for independent methodology shifts.

## Current Internal Consolidation

The first safe Stage 2 internal consolidation pass for the Stage 1B packaging ladder now exists in:

- `stage1_portable/stage1b_downstream_safe_packaging_helpers.py`

That helper currently centralizes repeated:

- strict-versus-caution class-count validation
- prior-class mask construction
- grouped summary lookup and summary-row generation
- representative sample serialization
- QC JSON and summary CSV writing support

This did not change command names, output artifact names, or bounded branch meaning.

## Packaging Ladder Role Classification

For the active bounded branch, the current artifacts now separate into four roles:

- `Analytically meaningful`
  - `Study_Roads_Divided_LinkRestored_NormalizedRouteKey.parquet`
  - `Functional_Segments_OracleTrueMatch_ReadySubset.parquet`
  - `Functional_Segments_OracleTrueMatch_ReadySubset_StabilityAudit.parquet`
  - `Functional_Segments_OracleMatched_DownstreamSafeSubset.parquet`
  - `Functional_Segments_OracleMatched_DownstreamSafeAnalyticalContext.parquet`
  - `Functional_Segments_OracleMatched_Stage1C_CrashAccessJoinAudit.parquet`
  - `Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet`
- `Runtime handoff boundary`
  - `Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep_LinkInherited.parquet`
  - `Functional_Segments_OracleMatchingContract_Resumed.parquet`
  - `Functional_Segments_OracleMatched_DownstreamSafeConsumerHandoff.parquet`
  - `Functional_Segments_OracleMatched_Stage1B_ClosureHandoff.parquet`
  - `Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerSlice.parquet`
  - `Functional_Segments_OracleMatched_Stage1C_NonDirectionalMiniSlice.parquet`
  - `Functional_Segments_OracleMatched_Stage1C_CrashAccessReadinessContract.parquet`
  - `Functional_Segments_OracleMatched_Stage1C_CrashAccessStagingContract.parquet`
- `Presentational packaging layer`
  - `Functional_Segments_OracleMatched_DownstreamSafeConsumerStaging.parquet`
  - `Functional_Segments_OracleMatched_DownstreamSafeReview.parquet`
  - `Functional_Segments_OracleMatched_DownstreamSafeTriage.parquet`
  - `Functional_Segments_OracleMatched_DownstreamSafeDecisionSupport.parquet`
  - `Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerOutput.parquet`
- `QC-only artifact`
  - `Functional_Segments_OracleMatched_Stage1C_CapabilityGapAudit.parquet`
  - summary CSV companions for the same branch
  - parity/QC JSON companions in `artifacts/parity/`

See:

- `docs/stage2_oracle_safe_branch_packaging_ladder_cleanup_plan.md`

That document is the authoritative Stage 2 cleanup-planning note for this branch.

## Current Endpoint

The current authoritative endpoint for this branch is:

- `Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet`

Current bounded meaning:

- non-directional
- crash-side complete only where justified
- access explicitly held back
- strict versus caution preserved
