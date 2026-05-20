# Roadway Graph Next Phase Plan

**Status: CURRENT DESIGN PLAN.** This document defines the next project phase after completion of the roadway-derived directional-bin context prototype.

## Bounded Question

What should the project build next now that the roadway-derived 0-2,500 ft directional-bin context universe exists with crash assignment, access context, speed context, AADT context, and crash-level urban/rural context?

The answer is a descriptive-analysis and stakeholder-readiness phase. It is not a modeling phase, a policy-guidance phase, or a broad graph-recovery phase.

## Current Product Summary

The current product is the stable roadway-derived directional-bin context universe:

- final folder: `work/output/roadway_graph/analysis/current/directional_bin_context_table/`
- primary table: `directional_bin_context.csv`
- crash-level table: `directional_crash_context.csv`
- signal summary: `reference_signal_context_summary.csv`
- QA and provenance: `combined_context_join_qa.csv`, `directional_bin_context_findings.md`, `directional_bin_context_manifest.json`

Current core counts:

- total bins: 110,710
- 0-1,000 ft high-priority bins: 66,074
- 1,000-2,500 ft sensitivity bins: 44,636
- assigned crashes represented: 13,216
- bins with assigned crashes: 8,552
- reference signals represented: 971
- bins with access context: 110,710
- bins with stable speed context: 84,857
- bins with stable AADT context: 106,210
- assigned crashes with crash `AREA_TYPE` urban/rural classification: 13,216
- roadway-level urban/rural context: unavailable, `source_not_found`

Methodological boundaries already established:

- crash direction fields were not used
- context fields do not redefine upstream/downstream
- crash `AREA_TYPE` is crash-level context only
- no-crash bins are not populated with crash-derived urban/rural values
- greater than 2,500 ft remains review-only
- the product is descriptive-analysis-ready, not modeling-ready or policy-claim-ready

## Alignment With The Proposal

The original proposal asks how VDOT should calculate and document downstream functional area guidance for signalized intersections. The current repository product supports the proposal primarily through Task 3, exploratory crash analysis.

Strong alignment:

- anchors analysis on signalized intersections
- creates downstream/upstream comparison zones from roadway geometry rather than crash direction fields
- attaches crash, access, speed, AADT, and urban/rural crash context to a reproducible scaffold
- preserves 0-1,000 ft and 1,000-2,500 ft analysis windows for comparison
- keeps unresolved and ambiguous cases visible instead of forcing coverage
- can support descriptive screening of signals, windows, roadway representation types, and context combinations

Partial alignment:

- proposal concepts such as limiting/desirable values, stopping-sight distance, decision-sight distance, acceleration distance, and corner clearance are not implemented as named band families yet
- roadway-level rural/suburban/urban context is not solved
- median and detailed access-type/commercial-intensity variables are not yet validated for proposal use
- outputs are not regression-ready or policy-ready

The current product is therefore a much stronger analytical backend than the older signal-centered packages, but it remains an exploratory evidence layer. It should inform guidance development; it should not become a crash-only functional-area calculator.

## What Changed From The Original Plan

The original archived proposal-facing packages were signal-centered and divided-road-oriented. They were useful for early descriptive structure, but they had limited coverage and large unresolved burdens.

The active workflow changed in four important ways:

- roadway graph first: the scaffold is built from Travelway graph evidence before crashes or context are attached
- full roadway retention: both divided and undivided roads remain in the scaffold, with divided physical carriageways and undivided pseudo-direction records handled explicitly
- context completeness: access, speed, AADT, and crash-level urban/rural context are now joined into one current product table
- stronger boundaries: crash direction fields are excluded, roadway urban/rural source failure is explicit, and >2,500 ft rows remain review-only

The plan should now move from context construction to descriptive products and stakeholder communication.

## What Is Solved

- Stable 0-2,500 ft directional-bin universe exists.
- High-priority and sensitivity windows are explicit.
- Unique assigned-crash universe is readiness-gated.
- Access context is present for all current bins.
- Stable speed context is available for most bins, with review/missing flags preserved.
- Stable AADT context is available for most bins, with review/missing flags preserved.
- Crash-level urban/rural context is available for all assigned crashes.
- Roadway-level urban/rural source failure is documented.
- Combined QA confirms context joins did not change upstream/downstream, crash assignment, or source context logic.
- Repo docs/work outputs have been cleaned around the current product.

## What Remains Unresolved

- Blocked divided records remain outside the usable directional universe.
- Ambiguous and unresolved crashes are excluded from assigned-crash summaries.
- Roadway-level rural/suburban/urban context is unavailable.
- Some speed and AADT context remains review/missing.
- Access ambiguity and access type/land-use intensity need review before stakeholder claims.
- Median context is not yet included as an accepted context layer in the combined product.
- Proposal-specific band families are not yet implemented.
- No denominator, exposure, or rate model has been accepted.
- No model-ready dependent or independent variables have been defined.
- No stakeholder-facing methodology memo or limitations memo has been produced from the current product.

## Recommended Next Stage

The next stage should produce descriptive analysis products from the accepted context universe.

Recommended stage name:

**Roadway Graph Context Descriptive Analysis Stage**

Bounded purpose:

- summarize crash, access, speed, AADT, and crash-level urban/rural context by reference signal, signal-relative direction, roadway representation, and distance window
- identify high-priority review signals and patterns
- prepare stakeholder-facing tables and limitations documentation
- keep all outputs descriptive and exploratory

This stage should not change scaffold construction, catchments, crash assignment, access joins, speed joins, AADT joins, or urban/rural source decisions.

## Recommended Analysis Products

### Signal-Level Summaries

One row per reference signal with:

- total directional bins
- bins by 0-1,000 ft and 1,000-2,500 ft window
- assigned crash counts by upstream/downstream and window
- access counts and access density by upstream/downstream and window
- stable speed coverage and typical speed context
- stable AADT coverage and typical AADT context
- crash-level urban/rural composition
- context completeness flags
- review/limitation flags

### Signal-Direction-Window Summaries

One row per reference signal, signal-relative direction, and distance window with:

- bin count and represented length
- assigned crash count
- crash count per 1,000 ft of represented bin length, flagged as descriptive density rather than rate
- access count and access density per 1,000 ft
- stable speed and AADT context summaries
- urban/rural crash composition
- quality flags for missing speed, missing AADT, access ambiguity, and no assigned crashes

### Bin-Level Summaries

Use the existing bin table to produce compact descriptive summaries by:

- distance window
- 50-foot or coarse distance band
- signal-relative direction
- roadway representation type
- access count class
- speed class
- AADT class
- crash area type composition where assigned crashes exist

### Crash-Level Summaries

Use `directional_crash_context.csv` to summarize assigned crashes by:

- distance window
- signal-relative direction
- roadway representation type
- crash `AREA_TYPE`
- inherited access count class
- inherited speed class
- inherited AADT class

### Review Queues

Create ranked review lists for:

- high assigned crash count in 0-1,000 ft
- high downstream assigned crash count
- high downstream access count or access density
- high crash count with high access density
- high crash count with missing/review speed or AADT context
- large upstream/downstream imbalance
- signals represented only in sensitivity-heavy context

These queues are for table and map review, not statistical outlier claims.

## QA And Review Needs Before Stakeholder Use

Stakeholder-facing summaries should include QA flags for:

- speed review/missing status
- AADT review/missing status
- access ambiguity and access source limitations
- blocked divided records outside the usable universe
- ambiguous and unresolved crash exclusions
- lack of roadway-level urban/rural source
- crash `AREA_TYPE` as crash context only
- >2,500 ft review-only exclusion
- denominator limitations for any density or normalized count

Do not hide these flags in appendices only. They should appear in summary tables and limitations notes.

## Potential Stakeholder Deliverables

First stakeholder-facing deliverables should be descriptive:

- concise methodology memo describing the graph-first context universe
- summary table package for 0-1,000 ft and 1,000-2,500 ft windows
- signal-level ranked review list
- upstream/downstream comparison tables
- access density and crash count summary tables
- speed/AADT context coverage summary
- crash-level urban/rural composition summary
- limitations memo
- optional GeoJSON/map review layers for high-priority review signals

Avoid producing a spreadsheet calculator until the project has accepted band families and policy logic.

## Production-Hardening Tasks

Before turning the prototype into a production pipeline:

- define a formal config for input/output roots and analysis windows
- define a reproducibility run order with dependencies
- document output contracts and primary keys
- add smoke tests for each accepted context layer
- add row-count and duplicate-key tests for final outputs
- formalize CRS conventions and sidecar metadata expectations
- decide artifact retention policy for current/history/archive lanes
- decide which large output summaries should be tracked versus ignored
- create a lightweight release checklist for the current product

Do this after descriptive analysis requirements are clear. Do not build orchestration before the target deliverables are known.

## Explicit Non-Goals

- no modeling yet
- no regression-ready claims yet
- no crash-rate claims yet
- no Appendix F policy language yet
- no spreadsheet calculator yet
- no crash-direction-based interpretation
- no use of crash `AREA_TYPE` as roadway-level urban/rural truth
- no broad recovery of blocked graph rows unless separately scoped
- no expansion of the current universe beyond 0-2,500 ft for main outputs
- no use of access, speed, or AADT to redefine upstream/downstream

## Recommended Next Implementation Prompts

1. **Build descriptive context summary tables.**
   Create a read-only module that consumes the current directional-bin and crash-context tables and writes signal, signal-direction-window, bin-band, and crash-context summaries without changing source context layers.

2. **Build a signal-level ranked review queue.**
   Create transparent review triggers for high crash count, high downstream access density, high crash/access combination, missing speed/AADT context, large upstream/downstream imbalance, and sensitivity-window burden.

3. **Add proposal-facing fixed band summaries.**
   Add coarse fixed bands such as 0-250, 250-500, 500-1,000, and 1,000-2,500 ft to the current roadway-derived context universe. Keep them descriptive and separate from policy-derived bands.

4. **Draft a stakeholder methodology and limitations memo.**
   Convert the milestone, QA, and next-phase limitations into a readable memo that explains what the product can and cannot support.

5. **Inventory candidate policy/literature band families.**
   Read proposal/literature references and design named limiting/desirable/corner-clearance/speed-based band families without generating rows yet.

6. **Plan production hardening.**
   Once the first descriptive tables are reviewed, define config, tests, output contracts, CRS sidecars, and artifact retention rules for a production-quality run.

## Decision

Proceed with descriptive analysis outputs first. Defer modeling, policy guidance, spreadsheet tools, and broad graph recovery until the descriptive products and stakeholder review questions are clear.
