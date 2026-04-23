# Stage 2 Oracle-Safe Branch Architecture Summary

## Purpose

This document begins Stage 2 for the bounded Oracle-safe branch that now ends in:

- `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet`

The goal of this Stage 2 pass is not to change behavior. It is to make the current bounded branch easier to understand, maintain, and extend without changing analytical meaning or output contracts.

## Branch Scope

This branch is a bounded portability-era lineage that:

1. restores bridge-bearing road identity back onto the study-road boundary
2. inherits that identity into the downstream segment Oracle-prep boundary
3. resumes Oracle matching readiness on the inherited segment subset
4. executes a tightly bounded Oracle true-match only on the ready subset
5. quarantines unresolved rows and defines a 77-row downstream-safe branch
6. packages that branch through several Stage 1B consumer-oriented handoff layers
7. proves a runnable Stage 1C non-directional slice on the same 77 rows
8. stages crash/access inputs, audits landing quality, and completes crash-side Stage 1C work only where justified

This branch does not:

- reopen the excluded 7 quarantined rows
- reopen partial, blocked, or out-of-scope rows
- assign downstream directionality
- perform new Oracle matching beyond the already completed bounded match
- perform final access assignment
- expand statewide

## Current Bounded Outcome

The current authoritative bounded branch outcome is:

- `77` rows in the completed non-directional slice
- classes preserved:
  - `14` `STAGE1C_COMPLETED_SLICE_STRICT`
  - `63` `STAGE1C_COMPLETED_SLICE_WITH_CAUTION`
- crash-side assignment completed only where the prior join audit supported unambiguous local landing:
  - `7` rows `CRASH_ASSIGNED_BOUNDED_NON_DIRECTIONAL`
  - `70` rows `CRASH_NOT_ASSIGNED_LOCAL_AMBIGUITY`
  - `261` total assigned crash records across the `7` assigned rows
- access intentionally held back on all `77` rows:
  - `77` rows `ACCESS_NOT_ASSIGNED_DIRECTIONLESS_HOLDBACK`

Interpretation:

- this branch is done enough for bounded non-directional Stage 1C purposes in crash-side form
- this branch is not directional
- this branch is not complete for access assignment

## Main Phases

### 1. Identity Recovery

This phase reconstructs the GIS-side bridge-bearing lineage needed for truthful downstream Oracle work.

Key commands:

- `restore-study-roads-parent-linkid-normalized-routekey`
- `inherit-stage1b-segment-link-identity`

Primary role:

- restore `AADT_LINKID` and bridge-bearing parent identity at the study-road level
- deterministically carry that identity into the downstream segment Oracle-prep branch

### 2. Bounded Oracle Match

This phase resumes Oracle matching readiness and executes the already-authorized bounded match only on the ready subset.

Key commands:

- `reaudit-stage1b-segment-oracle-matching-contract`
- `execute-stage1b-segment-oracle-true-match-ready-subset`
- `audit-stage1b-segment-oracle-true-match-ready-subset-stability`

Primary role:

- isolate the ready subset
- execute only the bounded Oracle true-match on that subset
- quarantine unresolved rows instead of forcing a conclusion

### 3. Safe-Subset Packaging Ladder

This phase turns the stable matched rows into a downstream-safe consumer branch.

Key commands:

- `define-stage1b-segment-oracle-downstream-safe-subset`
- `define-stage1b-segment-oracle-downstream-safe-consumer-handoff`
- `build-stage1b-segment-oracle-downstream-safe-consumer-staging`
- `build-stage1b-segment-oracle-downstream-safe-analytical-context`
- `build-stage1b-segment-oracle-downstream-safe-review`
- `build-stage1b-segment-oracle-downstream-safe-triage`
- `build-stage1b-segment-oracle-downstream-safe-decision-support`
- `build-stage1b-oracle-safe-subset-closure-handoff`

Primary role:

- keep the `77` stable rows explicit and safe
- keep `strict` versus `with caution` visible
- formalize allowed and disallowed downstream uses before Stage 1C

Architecture note:

- this ladder is behaviorally valid but packaging-heavy
- several layers primarily add presentation or handoff metadata rather than new analytical logic
- Stage 2 should preserve the outputs while making the conceptual grouping clearer
- the first internal consolidation pass now exists in `stage1_portable/stage1b_downstream_safe_packaging_helpers.py`
- that helper module centralizes repeated strict/caution count checks, shared grouped-summary wiring, sample-record serialization, and QC JSON writing for the Stage 1B packaging family without changing command or artifact contracts

### 4. Stage 1C Consumerization

This phase proves the bounded branch can feed a runnable non-directional consumer slice.

Key commands:

- `build-stage1c-nondirectional-consumer-slice`
- `build-stage1c-nondirectional-consumer-output`
- `build-stage1c-nondirectional-minislice`
- `audit-stage1c-capability-gap`

Primary role:

- prove the branch can be consumed
- prove it can write outputs and QC
- identify the remaining gap as crash/access-relevant assignment

### 5. Crash/Access Readiness and Completion

This phase brings crash/access fields into bounded scope, audits landing quality, completes crash-side work where justified, and explicitly holds access back.

Key commands:

- `define-stage1c-crash-access-readiness-contract`
- `define-stage1c-crash-access-staging-contract`
- `audit-stage1c-crash-access-join`
- `build-stage1c-nondirectional-completed-slice`

Primary role:

- stage normalized crash/access inputs
- audit whether they can land on the same 77 rows
- complete crash-side assignment only for locally unambiguous rows
- record access as intentionally incomplete

## What Each Major Boundary Means

### `Functional_Segments_OracleMatchingContract_Resumed.parquet`

The resumed Oracle matching-readiness boundary after bridge-bearing identity has been deterministically inherited into the segment Oracle-prep chain.

### `Functional_Segments_OracleTrueMatch_ReadySubset.parquet`

The authoritative bounded Oracle true-match output for the ready subset only.

### `Functional_Segments_OracleTrueMatch_ReadySubset_StabilityAudit.parquet`

The post-match audit that separates stable versus unresolved rows and preserves quarantine.

### `Functional_Segments_OracleMatched_DownstreamSafeSubset.parquet`

The first exact 77-row downstream-safe branch boundary.

### `Functional_Segments_OracleMatched_Stage1B_ClosureHandoff.parquet`

The formal Stage 1B closure / Stage 1C handoff boundary for this branch.

### `Functional_Segments_OracleMatched_Stage1C_CapabilityGapAudit.parquet`

The branch-level statement that the remaining realistic Stage 1C gap is crash/access-relevant integration.

### `Functional_Segments_OracleMatched_Stage1C_CrashAccessReadinessContract.parquet`

The readiness statement that the segment side has enough geometry and lineage to attempt bounded crash/access staging.

### `Functional_Segments_OracleMatched_Stage1C_CrashAccessStagingContract.parquet`

The boundary where normalized crash/access source fields are explicitly brought into bounded scope for later landing audits.

### `Functional_Segments_OracleMatched_Stage1C_CrashAccessJoinAudit.parquet`

The landing-quality audit that shows crash can move forward on a small clean subset, while access remains weak because the source is directionless and sparsely landing.

### `Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet`

The current authoritative branch endpoint. This is the bounded non-directional Stage 1C completed slice for this Oracle-safe branch.

## What Remains Incomplete

The bounded branch still intentionally does not solve:

- downstream directionality
- final access assignment
- crash assignment on locally ambiguous rows
- broader parity across the full statewide or excluded branches
- broader architectural cleanup outside this branch

## Stage 2 Cleanup Opportunities

These are safe architecture opportunities revealed by the current chain. They are not executed by this document-only pass.

### 1. Clarify the Packaging Ladder

The following layers are valid but conceptually repetitive:

- downstream-safe consumer handoff
- consumer staging
- analytical context
- review
- triage
- decision-support

Stage 2 should keep their output contracts intact, but can document them as one conceptual ladder with sub-phases instead of leaving the reader to infer that from filenames alone.

### 2. Group the Branch by Responsibility

The current command list is flat in `stage1_portable/__main__.py`. The branch is easier to reason about when grouped into:

- identity recovery
- bounded Oracle match
- safe-subset packaging
- Stage 1C consumerization
- crash/access completion

### 3. Keep Completion Semantics Explicit

Future cleanup must continue to separate:

- `strict`
- `with caution`
- crash assigned
- crash not assigned due ambiguity
- access intentionally held back

These distinctions are part of the analytical meaning of the current branch and should not be collapsed during cleanup.

### 4. Preserve the Non-Directional Contract

The completed slice is useful precisely because it is explicit about what it is not:

- it is not directional
- it is not a full access-assigned branch
- it is not a general statewide result

Stage 2 cleanup should make those limits more visible, not less visible.

## Packaging Ladder Cleanup Plan

The packaging-ladder cleanup plan for this branch is documented separately in:

- `docs/stage2_oracle_safe_branch_packaging_ladder_cleanup_plan.md`

That plan classifies the active branch layers as:

- analytically meaningful
- runtime handoff boundary
- presentational packaging layer
- QC-only artifact

It also records which current 77-row layers look safe to group later and which ones should remain explicit because they define real analytical or phase-boundary meaning.
The first no-behavior-change implementation step from that plan is now complete for the Stage 1B packaging family helper wiring.

## Suggested Next Stage 2 Workstreams

Plausible next bounded Stage 2 tasks:

1. Consolidate the documentation of the Stage 1B packaging ladder without changing any runtime behavior.
2. Introduce a lightweight branch index in code or docs that maps command names to phases and artifacts.
3. Add module-level docstrings/comments to the recent Stage 1C modules so their purpose is visible without opening the matching task handoff text.
4. Start a separate access-preparatory design note for future work, clearly separated from the crash-complete branch.

## Validation Note

This Stage 2 branch summary started as documentation-first.
The current state now also includes a no-behavior-change internal helper consolidation for the Stage 1B packaging family.

Behavior preserved:

- no runtime logic was intentionally changed
- no bounded branch output meaning was changed
- no new Oracle matching, directionality, or access assignment was introduced

See:

- `docs/stage2_oracle_safe_branch_traceability_map.md`
- `artifacts/parity/stage2_oracle_safe_branch_architecture_qc.json`
