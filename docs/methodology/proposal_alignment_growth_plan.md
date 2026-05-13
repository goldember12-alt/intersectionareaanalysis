# Proposal Alignment and Growth Plan: Downstream Functional Area Guidance

**Status: CURRENT SUPPORT.** This remains the proposal-alignment growth plan. Read it as the controlled expansion path after the current roadway_graph scaffold is validated.

## Purpose

This document translates the VTRC final proposal, *Developing Guidance for Calculating the Downstream Functional Area of an Intersection*, into repository-facing methodology and growth guidance.

It should be kept under `docs/methodology/` because it is not merely a workflow note. It describes the larger research charter that this repository is meant to support over time:

- clearer Virginia guidance for calculating downstream functional area dimensions at signalized intersections
- evidence for Appendix F of VDOT's Road Design Manual
- exploratory crash/access analysis that can inform, but not solely determine, downstream functional area guidance
- controlled growth from the full-roadway graph foundation and preserved divided-road vertical slice into comparison-ready analytical outputs

This document is a companion to `docs/methodology/overview_methodology.md`. The overview remains the core active methodology for how this repo should work today. The current graph-foundation pivot is a full-roadway signal-adjacent graph that retains both divided and undivided Travelway roads, documented further in `docs/methodology/roadway_graph_methodology.md`. The older divided-road directed segment workflow remains useful as a preserved vertical-slice prototype. This proposal-alignment document explains why that active methodology matters to the larger research project and how it can grow without losing methodological discipline.

## Relationship to the Core Methodology

The core methodology now asks a bounded implementation question:

- how can the repo build a full-roadway signal-adjacent graph and distance bins that retain both divided and undivided roads so later crash, access, AADT, speed, and median evidence can be attached to a stable roadway scaffold without prematurely claiming true vehicle travel direction?

The proposal asks a broader research question:

- how should VDOT calculate and document downstream functional area guidance for signalized intersections across relevant roadway and land-use contexts?

Those questions are aligned but not identical.

The current repository should not try to become the full proposal in one step. It should first produce a trustworthy roadway graph foundation, while preserving the divided-road vertical slice as a comparison and validation prototype. Once the graph foundation is reviewed, it can become the analytical backend for the proposal's exploratory crash analysis and later guidance development.

## Core Ideas from the Final Proposal

### Research Need

Appendix F of VDOT's Road Design Manual provides standards and guidance for entrance spacing, corner clearance, and upstream functional area dimensions. The proposal identifies the downstream functional area as the weakest-guidance portion of that framework.

The practical problem is inconsistent application across districts and local contexts. Some reviewers use values from access-management literature, some use corner-clearance standards, and some use engineering judgment. That inconsistency affects entrance approvals, waiver and exception decisions, review predictability, and developer/locality expectations.

### Project Purpose

The proposal's purpose is to provide clearer guidance for calculating downstream functional area dimensions at signalized intersections.

The expected research deliverables are:

- a final report documenting literature, practice, exploratory crash analysis, findings, and recommendations
- proposed guidance for VDOT Road Design Manual Appendix F
- methods for calculating downstream functional area distances
- more descriptive details for upstream functional area calculations
- a spreadsheet-based tool for functional-area computations

### Proposed Research Tasks

The proposal describes five tasks:

1. Conduct a literature review.
2. Conduct a survey of best practices.
3. Conduct exploratory crash analysis.
4. Develop guidance.
5. Prepare a final report.

For this repository, Task 3 is the primary near-term connection. The repo can provide structured, reproducible crash/access/context evidence for exploratory analysis. Tasks 1, 2, 4, and 5 remain important research and reporting work, but they are not software workflow steps by themselves.

### Downstream Functional Area Concepts

The proposal frames downstream functional area guidance around several candidate concepts from the access-management literature:

- acceleration distance from stop to normal roadway speed
- stopping sight distance for downstream conflicts
- decision sight distance for changes in speed, path, or direction
- right-turn conflict overlap between through traffic and entering/exiting driveway traffic
- left-turn driving task after the intersection
- downstream corner clearance to access drives or approach roads

The repo should preserve those as policy and geometry concepts, not collapse them into one crash-derived distance. Crash analysis can help identify safety patterns, but geometric and operational logic remain foundational.

### Exploratory Crash Analysis Concepts

The proposal describes several exploratory crash-analysis directions:

- collect crashes within different buffer zones around intersections
- filter crashes upstream and downstream of the physical intersection area
- compare crashes between candidate downstream zones, such as between the intersection and a limiting value versus between the limiting and desirable values
- model crash frequency using variables such as geographic class, intersection geometry, traffic volume, posted speed, median presence, downstream entrances, entrance distance, entrance side, entrance type, commercial access, and trip-generation context
- compare measured and expected crash-type frequencies for downstream geometries, using tests such as chi-square where appropriate

The repo's current signal-centered classification work directly supports the first hard requirement: crashes must be interpretable relative to the signal before downstream-zone comparisons are meaningful.

## Current Repository Alignment

The current repo is aligned with the proposal in these ways:

- it anchors analysis on signalized intersections
- it keeps downstream functional area analysis as the main subject
- it uses roadway, signal, crash, access, speed, AADT, median, and rural/urban context where available
- it recognizes crash analysis as exploratory and evidence-generating
- it treats access points downstream of signals as analytically important
- it is building reproducible validation outputs rather than relying on one-off manual summaries
- it keeps unresolved and ambiguous cases visible instead of forcing labels

The active workflow already contains useful building blocks:

- divided-road study slice
- signal-to-nearest-road enrichment
- empirical flow-orientation experiment
- upstream/downstream crash-classification prototype
- high-confidence downstream descriptive analysis
- context enrichment for AADT, access points, and rural/urban crash context

## Current Repository Non-Alignment

The current repo is not yet the full proposal.

Important gaps:

- the prior analytical vertical slice was intentionally focused on divided roads; the active graph foundation now retains divided and undivided roads but is still a prototype requiring QA
- it does not yet implement explicit downstream distance bands from the proposal
- it does not yet produce regression-ready or model-ready analysis tables as a stable output contract
- it does not yet provide a spreadsheet-style calculation tool
- it does not yet have a trusted roadway-level rural/suburban/urban source
- it does not yet classify access type, commercial access intensity, or trip-generation context deeply enough for the proposal's full modeling variable list
- it does not yet turn exploratory findings into policy guidance or Appendix F language

These gaps are expected. They should not be solved by reactivating old broad machinery unless that machinery proves simpler and more truthful than the bounded active workflow.

## Controlled Future Alignment

The repository can become the analytical backend for the proposal if it grows in controlled phases:

1. Keep the full-roadway graph foundation as the active roadway scaffold while preserving the divided-road workflow as a validation prototype.
2. Use the reviewed graph foundation to produce downstream-zone crash/access/AADT/speed/median summaries by signal.
3. Add explicit downstream distance bands matching proposal concepts, such as physical area to limiting value, limiting value to desirable value, fixed buffers, and speed-based bands.
4. Add comparison-ready outputs for regression or descriptive analysis.
5. Expand analysis cautiously beyond reviewed graph contexts only after graph QA and divided/undivided handling are validated.
6. Add roadway-level rural/suburban/urban context from a better source before using those classes as policy variables.
7. Treat crash findings as safety evidence that informs guidance, not as the sole basis for distance calculation.

These steps are the preferred growth sequence for proposal alignment.

## Phase Guidance for Repo Implementation

### Phase 1: Build and Review the Full-Roadway Graph Foundation

The active roadway scaffold should retain both divided and undivided roads. The older divided-road vertical slice should remain preserved for comparison, but it should not be the only graph foundation.

Required behavior:

- keep graph adjacency separate from true vehicle travel direction
- preserve divided/undivided source-roadway status as descriptive context
- keep strict and empirical directionality evidence separate from low-trust support fields
- report unresolved rates and conflict rates
- keep current/history output lanes stable

### Phase 2: Produce Signal-Level Downstream Context Summaries

The next proposal-facing output should summarize conditions by signal and downstream zone.

Likely fields:

- signal identifiers and route context
- assigned speed and speed source
- median/facility context
- AADT and AADT match status
- downstream access count and density
- upstream access count and density for comparison
- high-confidence downstream crash count
- high-confidence upstream crash count
- unresolved crash count
- rural/urban or future geographic-context fields with provenance
- flow-orientation provenance and classification confidence

This phase should remain descriptive before it becomes inferential.

### Phase 3: Add Explicit Downstream Distance Bands

The proposal's downstream concepts should become explicit, named analysis bands.

Candidate band families:

- fixed-distance bands, such as 0-250 feet, 250-500 feet, and 500-1,000 feet
- speed-based stopping-sight or decision-sight bands
- literature-derived limiting and desirable values
- access-management policy bands, such as corner-clearance distances
- approach-shaped bands using the current signal-centered geometry

Each band must state:

- source or rationale
- applicable roadway context
- whether it is geometric, policy-derived, empirical, or exploratory
- whether it is used for crash counting, access counting, or both
- what it does when flow orientation is unresolved

### Phase 4: Build Comparison-Ready Outputs

Only after bands and classifications are stable should the repo produce model-ready tables.

Candidate output units:

- one row per signal and band
- one row per signal, approach, and band
- one row per access point with signal-relative and band-relative assignment
- one row per crash with signal-relative and band-relative assignment

Candidate dependent variables:

- crash frequency
- crash type frequency
- high-confidence downstream crash frequency
- sideswipe, rear-end, angle, or other conflict-relevant crash groups where coding supports them

Candidate independent variables:

- AADT
- posted or assigned speed
- median presence
- access count and density
- distance to first downstream access
- upstream/downstream band family
- rural/suburban/urban class once a trusted source exists
- roadway functional class if a trusted source exists
- entrance/access type where data quality supports it

Crash-rate or regression claims should wait until denominator coverage, sample size, and unresolved-case behavior are reviewed.

### Phase 5: Expand Beyond Divided Roads

Expansion beyond divided roads should occur only after the divided-road workflow has earned confidence.

Before expansion, document:

- what divided-road assumptions no longer apply
- what new orientation evidence is required
- whether undivided roads require a different classification model
- whether intersection geometry introduces new movement classes
- how unresolved cases will be handled

Expansion should not reuse divided-road labels blindly.

### Phase 6: Add Better Geographic and Policy Context

The proposal anticipates urban, suburban, and rural differentiation. The current repo only has crash `AREA_TYPE` context, which is useful but not enough for policy variables.

Before using geographic class as a modeling or guidance variable, the repo needs a better source, such as:

- Census urban area context
- VDOT roadway classification data
- locality or district context
- functional classification
- MPO or planning-area context where relevant

Crash `AREA_TYPE` may remain a crash-context field, but it should not be treated as roadway truth.

### Phase 7: Interpret Crash Analysis as Evidence, Not a Calculator

The proposal is clear that downstream functional area dimensions are grounded in geometric and operational concepts. Crash analysis is important because it can show safety implications and patterns around downstream access.

Therefore, repo outputs should support statements such as:

- whether crash occurrence differs across candidate downstream zones
- whether access density is associated with downstream crash patterns
- whether certain contexts show outlier behavior
- whether crash-type patterns support concern about downstream conflict mechanisms

Repo outputs should not claim:

- that crash frequency alone defines the downstream functional area
- that a statistically elevated zone is automatically the correct design distance
- that unresolved signal-relative classifications can be ignored

## Documentation Placement and Titles

Recommended active methodology titles:

- `docs/methodology/overview_methodology.md`: **Core Methodology: Signal-Centered Downstream Functional Area Analysis**
- `docs/methodology/proposal_alignment_growth_plan.md`: **Proposal Alignment and Growth Plan: Downstream Functional Area Guidance**

The first document governs the current analytical method. The second document connects that method to the larger proposal and gives the repo a disciplined growth path.

## Completion Standard for Proposal-Aligned Work

A proposal-aligned repo task is not complete until it states:

- which proposal concept it supports
- which active methodology question it answers
- whether it remains divided-road-only
- what evidence source it uses
- what output unit it creates
- how unresolved cases are represented
- what validation was performed
- whether the result is descriptive, exploratory, or suitable for modeling

This standard keeps proposal alignment from becoming uncontrolled scope expansion.
