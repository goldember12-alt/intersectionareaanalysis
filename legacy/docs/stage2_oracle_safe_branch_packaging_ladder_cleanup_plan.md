# Stage 2 Oracle-Safe Branch Packaging Ladder Cleanup Plan

## Purpose

This document is a bounded Stage 2 planning pass for the current Oracle-safe branch that ends at:

- `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet`

It does not change runtime behavior.
It does not change the validated meaning of the current 77-row bounded branch.
It does not reopen excluded, quarantined, partial, blocked, or out-of-scope rows.

## Guardrails

This plan assumes the following current state remains authoritative:

- completed slice row count remains `77`
- completed-slice classes remain exactly:
  - `14` `STAGE1C_COMPLETED_SLICE_STRICT`
  - `63` `STAGE1C_COMPLETED_SLICE_WITH_CAUTION`
- crash-side assignment remains bounded and justified only where the join audit supported it:
  - `7` `CRASH_ASSIGNED_BOUNDED_NON_DIRECTIONAL`
  - `70` `CRASH_NOT_ASSIGNED_LOCAL_AMBIGUITY`
  - `261` assigned crashes total across the `7` assigned rows
- access remains intentionally incomplete on all `77` rows:
  - `77` `ACCESS_NOT_ASSIGNED_DIRECTIONLESS_HOLDBACK`
- no downstream directionality
- no new Oracle matching
- no final access assignment
- no statewide expansion

## Why This Cleanup Pass Is Needed

The active Oracle-safe branch is valid, but its packaging ladder is long.

Observed current shape:

- the row count drops from `18,293` to `77` only once at `Functional_Segments_OracleMatched_DownstreamSafeSubset.parquet`
- from that point through the completed slice, the branch stays at `77` rows
- most later steps add small sets of status, class, restriction, or summary-hint columns on top of the same bounded branch
- strict-versus-caution semantics are preserved all the way through the ladder

That means Stage 2 can improve maintainability by documenting which layers are analytically substantive versus which layers primarily package the same bounded branch for different consumers or QC views.

## Current Branch Classification

### Core rule

Each layer below is classified as one of:

- `analytically meaningful`
- `runtime handoff boundary`
- `presentational packaging layer`
- `QC-only artifact`

### Primary artifact ladder

| Order | Command | Primary artifact | Rows | Classification | Why it matters now | Later consolidation posture |
|---|---|---|---:|---|---|---|
| 1 | `restore-study-roads-parent-linkid-normalized-routekey` | `Study_Roads_Divided_LinkRestored_NormalizedRouteKey.parquet` | 16,495 | analytically meaningful | Restores bounded bridge-bearing parent identity on study roads. | Keep distinct. This is substantive lineage recovery, not packaging. |
| 2 | `inherit-stage1b-segment-link-identity` | `Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep_LinkInherited.parquet` | 18,293 | runtime handoff boundary | Carries restored study-road identity into the segment Oracle-prep chain using deterministic lineage. | Keep distinct. This is the road-to-segment handoff seam. |
| 3 | `reaudit-stage1b-segment-oracle-matching-contract` | `Functional_Segments_OracleMatchingContract_Resumed.parquet` | 18,293 | runtime handoff boundary | Re-establishes Oracle-match readiness on the inherited segment set without matching. | Keep distinct. This is the explicit contract boundary before bounded matching. |
| 4 | `execute-stage1b-segment-oracle-true-match-ready-subset` | `Functional_Segments_OracleTrueMatch_ReadySubset.parquet` | 18,293 | analytically meaningful | Executes the already-authorized bounded true-match on the ready subset only. | Keep distinct. Matching output meaning is substantive. |
| 5 | `audit-stage1b-segment-oracle-true-match-ready-subset-stability` | `Functional_Segments_OracleTrueMatch_ReadySubset_StabilityAudit.parquet` | 18,293 | analytically meaningful | Separates stable from unresolved rows and preserves quarantine. | Keep distinct. This is the last full-scope safety gate before the 77-row branch. |
| 6 | `define-stage1b-segment-oracle-downstream-safe-subset` | `Functional_Segments_OracleMatched_DownstreamSafeSubset.parquet` | 77 | analytically meaningful | Defines the first exact 77-row bounded branch and preserves strict versus caution. | Keep distinct. This is the first authoritative bounded-branch artifact. |
| 7 | `define-stage1b-segment-oracle-downstream-safe-consumer-handoff` | `Functional_Segments_OracleMatched_DownstreamSafeConsumerHandoff.parquet` | 77 | runtime handoff boundary | Formalizes allowed/disallowed consumer use on the 77-row branch. | Likely keep as the first consumer-facing contract, but implement later with shared helpers. |
| 8 | `build-stage1b-segment-oracle-downstream-safe-consumer-staging` | `Functional_Segments_OracleMatched_DownstreamSafeConsumerStaging.parquet` | 77 | presentational packaging layer | Repackages the same bounded branch as consumer-ready staging. | Candidate to group with consumer handoff in a later consolidation pass. |
| 9 | `build-stage1b-segment-oracle-downstream-safe-analytical-context` | `Functional_Segments_OracleMatched_DownstreamSafeAnalyticalContext.parquet` | 77 | analytically meaningful | Adds grouped context fields such as parent road key, route, signal, zone, and ownership grouping. | Keep conceptually distinct, but shared helper logic can absorb repeated status/notes wiring. |
| 10 | `build-stage1b-segment-oracle-downstream-safe-review` | `Functional_Segments_OracleMatched_DownstreamSafeReview.parquet` | 77 | presentational packaging layer | Adds review-oriented grouping, priority, and summary hints on the same branch. | Candidate to collapse with triage and decision-support into a single packaging family. |
| 11 | `build-stage1b-segment-oracle-downstream-safe-triage` | `Functional_Segments_OracleMatched_DownstreamSafeTriage.parquet` | 77 | presentational packaging layer | Adds triage ordering and inspection metadata, not new matching meaning. | Candidate to collapse with review and decision-support. |
| 12 | `build-stage1b-segment-oracle-downstream-safe-decision-support` | `Functional_Segments_OracleMatched_DownstreamSafeDecisionSupport.parquet` | 77 | presentational packaging layer | Adds recommended-action metadata for bounded decision support. | Candidate to collapse with review and triage after a no-behavior helper refactor. |
| 13 | `build-stage1b-oracle-safe-subset-closure-handoff` | `Functional_Segments_OracleMatched_Stage1B_ClosureHandoff.parquet` | 77 | runtime handoff boundary | Declares the Stage 1B closure / Stage 1C handoff contract. | Keep distinct. This is the explicit phase boundary into Stage 1C. |
| 14 | `build-stage1c-nondirectional-consumer-slice` | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerSlice.parquet` | 77 | runtime handoff boundary | Establishes the first runnable Stage 1C consumer boundary. | Candidate to remain as the canonical Stage 1C entrypoint even if later packaging is simplified. |
| 15 | `build-stage1c-nondirectional-consumer-output` | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerOutput.parquet` | 77 | presentational packaging layer | Re-expresses the consumer slice as the first consumer-facing output layer. | Candidate to group with consumer slice and mini-slice behind shared helper logic. |
| 16 | `build-stage1c-nondirectional-minislice` | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalMiniSlice.parquet` | 77 | runtime handoff boundary | Marks the first bounded runnable mini-slice used for the Stage 1C gap audit. | Keep as a named checkpoint unless a later refactor proves the same contract can be carried directly from consumer slice. |
| 17 | `audit-stage1c-capability-gap` | `Functional_Segments_OracleMatched_Stage1C_CapabilityGapAudit.parquet` | 77 | QC-only artifact | States what the mini-slice can already do and what still blocks fuller Stage 1C completion. | Keep output for traceability, but treat as audit/QC, not as new runtime semantics. |
| 18 | `define-stage1c-crash-access-readiness-contract` | `Functional_Segments_OracleMatched_Stage1C_CrashAccessReadinessContract.parquet` | 77 | runtime handoff boundary | Defines that the branch has enough geometry/lineage to attempt bounded crash/access staging. | Keep distinct. This is the formal contract before source-field staging. |
| 19 | `define-stage1c-crash-access-staging-contract` | `Functional_Segments_OracleMatched_Stage1C_CrashAccessStagingContract.parquet` | 77 | runtime handoff boundary | Brings normalized crash/access source-boundary fields into bounded scope without assignment. | Keep distinct. It materially expands the branch schema and readiness state. |
| 20 | `audit-stage1c-crash-access-join` | `Functional_Segments_OracleMatched_Stage1C_CrashAccessJoinAudit.parquet` | 77 | analytically meaningful | Determines which rows can justify bounded crash-side assignment and confirms access remains blocked. | Keep distinct. This audit drives the justified completed-slice behavior. |
| 21 | `build-stage1c-nondirectional-completed-slice` | `Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet` | 77 | analytically meaningful | Produces the authoritative bounded endpoint with crash-side completion and access holdback. | Keep distinct. This is the current branch endpoint. |

### QC-only support artifacts

These are important for reproducibility, but they are not separate analytical boundaries:

- per-step summary CSVs such as:
  - `Functional_Segments_OracleMatched_DownstreamSafeAnalyticalContext_Summaries.csv`
  - `Functional_Segments_OracleMatched_DownstreamSafeReview_Summaries.csv`
  - `Functional_Segments_OracleMatched_DownstreamSafeTriage_Summaries.csv`
  - `Functional_Segments_OracleMatched_DownstreamSafeDecisionSupport_Summaries.csv`
  - `Functional_Segments_OracleMatched_Stage1B_ClosureHandoff_Summary.csv`
  - `Functional_Segments_OracleMatched_Stage1C_*_Summary.csv`
- parity/QC JSONs in `artifacts/parity/` for the same commands

Stage 2 should continue to preserve these artifacts as QC outputs even if later implementation cleanup reduces internal repetition.

## What Is Substantive Versus Packaging-Heavy

### Substantive boundaries that should remain explicit

The following steps change bounded branch meaning or define a real phase gate:

- normalized-route-key restoration
- link inheritance
- resumed matching contract
- true-match ready subset
- stability audit
- downstream-safe subset
- Stage 1B closure handoff
- crash/access readiness contract
- crash/access staging contract
- crash/access join audit
- completed slice

### Packaging-heavy families

The following families appear to be safe future consolidation targets because they preserve the same 77 rows and mainly add small bundles of presentation, restriction, or review metadata:

- Stage 1B consumer packaging:
  - consumer handoff
  - consumer staging
- Stage 1B review packaging:
  - review
  - triage
  - decision support
- Stage 1C consumer packaging:
  - consumer slice
  - consumer output
  - mini-slice

### Important exception

`Functional_Segments_OracleMatched_DownstreamSafeAnalyticalContext.parquet` is not just presentation.
It appears to be the point where the bounded 77-row branch is bundled with grouped context keys that help later review and Stage 1C consumption.
It should therefore be treated as analytically meaningful even if later helper code is consolidated.

## Safe Consolidation Plan For Later Implementation

### Goal

Reduce conceptual and code repetition while preserving:

- the 77-row bounded branch
- strict versus caution distinctions
- existing allowed/disallowed-use guidance
- crash-assigned versus crash-not-assigned results
- access holdback semantics
- current file contracts unless explicitly retired in a later validated pass

### Recommended order

1. Keep outputs and commands stable while introducing grouped internal helpers.
2. Consolidate repeated status/class/notes scaffolding across packaging modules first.
3. Consolidate packaging families second, but continue writing the current artifacts.
4. Only after a parity-style check should any future pass consider reducing emitted intermediate artifacts.

### Proposed later implementation sequence

#### Step A. Introduce grouped helper families behind existing commands

Safe first refactor target:

- shared helper for Stage 1B packaging-layer status/class propagation
- shared helper for Stage 1C consumer-layer status/class propagation
- shared helper for repeated strict/caution validation and summary writing

Why first:

- this reduces code duplication without changing command names or artifact names
- it lowers risk before any deeper consolidation discussion

Implementation status:

- completed for the Stage 1B packaging family through `stage1_portable/stage1b_downstream_safe_packaging_helpers.py`
- current helper coverage is limited to repeated status/class validation support, summary CSV support, sample/QC serialization support, and related no-behavior internal wiring
- current commands and emitted artifacts remain unchanged

#### Step B. Consolidate Stage 1B packaging families conceptually, not externally

Later implementation target:

- treat `consumer_handoff` plus `consumer_staging` as one packaging family
- treat `review` plus `triage` plus `decision_support` as one packaging family

Recommended runtime posture for that pass:

- keep the current commands
- keep the current output files
- allow the commands to call shared builders instead of separate near-duplicate logic

#### Step C. Consolidate Stage 1C consumer packaging internally

Later implementation target:

- reduce overlap among `consumer_slice`, `consumer_output`, and `mini_slice`

Important caution:

- preserve the current named checkpoints until a later validated pass proves that direct collapsing does not erase useful traceability for the mini-slice and capability-gap audit

#### Step D. Revisit emitted intermediates only after evidence

Not for the next pass:

- do not delete active outputs now
- do not silently stop writing current intermediate artifacts now
- do not collapse strict/caution labels now

If a later pass wants to reduce emitted artifacts, it should first prove:

- dependent docs and QC still make sense
- the same bounded branch decisions are observable
- the same 77-row contract remains explicit

## Minimal Next Stage 2 Implementation Pass

The next safe Stage 2 implementation pass should be:

1. no behavior change
2. no output deletion
3. no canonical rename
4. no new Oracle work
5. no directionality work

Suggested bounded objective:

- introduce internal helper consolidation for the Stage 1B packaging family while preserving every existing command and artifact

## What This Plan Does Not Claim

This plan does not claim:

- repository-wide cleanup outside this bounded branch
- behavioral equivalence for a future consolidation that has not been implemented yet
- that every packaging artifact is unnecessary
- that the current completed slice is directional or access-complete

It only claims that the current branch is now classified clearly enough to support a later low-risk cleanup pass.
