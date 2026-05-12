# Core Methodology: Directed Segment Downstream Functional Area Analysis

## Purpose

This project exists to evaluate downstream functional area conditions at signalized intersections in Virginia using roadway, signal, crash, access, speed, volume, and related contextual data.

The goal is not to preserve a legacy implementation path. The goal is to produce a trustworthy, explainable, and maintainable analytical workflow that can support Virginia-specific downstream functional area understanding and guidance.

This repository should therefore be treated as an active analytical redesign effort. Existing code, outputs, contracts, and workflow assumptions are inputs for evaluation, not assumptions that must be preserved. Any existing component may be retained, repurposed, rewritten, moved to legacy storage, or discarded depending on whether it helps accomplish the analytical goals of the project clearly and truthfully.

This document is the core methodology for the repository. The companion document
`docs/methodology/proposal_alignment_growth_plan.md` translates the VTRC final proposal into a repository-facing growth plan. That companion should be read as project-charter alignment and future expansion guidance; it does not replace the bounded directed segment methodology here.

## Core Project Principle

Prefer the simplest method that truthfully solves the current analytical problem.

Complexity is not a virtue by itself. If a proposed method requires repeated bridge logic, fragile lineage recovery, excessive staging layers, or elaborate exception handling, that complexity must be treated as diagnostic information. It may indicate that the method is mismatched to the current problem definition.

The project should favor methods that are:

- understandable
- testable
- bounded in scope
- empirically grounded
- easy to validate
- proportionate to the actual question being asked

## Current Scope

The current practical focus is pivoting to a road-network-first workflow that first builds a full-roadway graph foundation from Travelway geometry. Signals remain critical nodes, but the active graph foundation must retain both divided and undivided roads before crashes, access-context summaries, or other events are attached.

The earlier divided-road directed signal-leg scaffold remains useful as a preserved prototype, but it is superseded for graph foundation purposes. The active graph foundation is documented in `docs/methodology/roadway_graph_methodology.md` and `docs/workflow/roadway_graph_workflow.md`.

The earlier signal-centered crash/access classification workflow remains preserved as an active-but-separate prototype until a later task explicitly migrates it. The directed segment workflow must not use crash records or crash direction fields to infer true vehicle travel direction.

The detailed directed segment methodology is documented in `docs/methodology/directed_segment_methodology.md`.

The directed segment workflow must still not use crash records or crash direction fields to infer true vehicle travel direction. For the full-roadway graph foundation, divided/undivided classification is descriptive source-roadway context only. Divided roads may later support directional/carriageway records, while undivided roads remain centerline/logical segment records until a later crash-direction assignment phase is explicitly implemented.

The prior divided-road vertical slice remains valuable, but the graph foundation should no longer exclude undivided roads.

The methodology should still allow scope reduction when it improves clarity, validity, and deliverability, but graph-foundation scope reduction must be explicit and must not silently discard undivided roads.

## Directed Segment Evidence Scaffold

The working dataset should first be a bounded oriented roadway scaffold rather than a crash-first signal buffer. The scaffold is road-network-first, but still signal-anchored: signals define the primary nodes and divided-road carriageways define oriented legs to adjacent signals, access points, or roadway endpoints.

In practical terms, that means:

1. start from signalized intersection nodes
2. attach each usable signal node to divided-road route/carriageway context
3. build signal-anchored roadway legs on the same route/carriageway
4. order those leg geometries from one fixed anchor to another without claiming true vehicle movement
5. cut oriented legs into fixed distance bins for later crash, access, speed, AADT, and median joins

Crashes should be attached to this scaffold in later passes. The current directed segment pass does not use crash data to infer or validate true vehicle travel direction.

## What the Methodology Must Accomplish

The workflow must ultimately support these outcomes:

1. Compile and manage the roadway, signal, crash, access, speed, volume, and related contextual data needed for downstream analysis.
2. Define downstream study areas or comparison zones in a way that can be explained and validated.
3. Assign roadway-side and downstream context truthfully enough for crash and access interpretation.
4. Measure crash occurrence and related downstream conditions within those study areas.
5. Support comparison across intersections, roadway contexts, and downstream conditions.
6. Identify patterns and outliers that can contribute to Virginia-specific downstream functional area understanding and guidance.

These are the required analytical ends. The exact computational path used to achieve them is open to redesign.

## Supporting Flow-Orientation Principle

Signal-relative flow orientation is now a supporting analytical requirement inside the directed segment workflow, but the method used to infer it is not fixed in advance. Cardinal labels may be useful intermediate aids, but they are not the final analytical purpose by themselves.

The methodology must permit multiple candidate flow-orientation approaches to be explored and compared, including but not limited to:

- network-identity-based methods
- roadway-context-based methods
- empirically inferred methods
- crash-evidence-based methods
- hybrid methods that combine multiple evidence sources

No single legacy assumption, including Oracle dependence, should be treated as mandatory unless it is demonstrated to be the simplest trustworthy solution for the current bounded scope.

A method is acceptable if it can state clearly:

- what evidence it uses
- what assumptions it makes
- what scope it applies to
- how ambiguity is handled
- what outputs it can support
- where it should refuse to assign a label

## Empirical Flow Orientation for Divided Roads

Prior divided-road experiments found that filtered empirical crash evidence may be useful for diagnostic comparison in some contexts. That remains legacy/prototype evidence only for the current pivot. The directed segment workflow must first use road-network/source evidence and must not use crash evidence to infer or validate direction in this pass.

Historical crash-evidence experiments remain useful as background, not as an active direction source for the directed segment build. The prior read was:

- a non-Oracle empirical method can produce credible local carriageway flow orientation in at least some divided-road contexts
- strict unanimity is trustworthy but sparse
- a 90% dominant-share relaxation appears promising as a bounded empirical variant
- single-vehicle-clean cases are diagnostically useful
- route-name fallback remains secondary and low-trust

That work answered an important subproblem for the older prototype. It does not govern the current directed segment pass, which must keep roadway direction independent from crash observations.

## Required Method-Design Behavior

Any redesigned method must do the following:

### 1. Be explicit about the question it is solving

For example:
- full-network flow orientation
- signal-relative flow orientation on divided carriageways near signals
- upstream/downstream labeling relative to the signal
- approaching-versus-leaving interpretation support
- crash-side assignment
- access-side assignment

Methods should not silently broaden from a bounded question to a more general one.

### 2. Rank candidate methods by sufficiency, not inheritance

When comparing methods, the preferred ordering criteria are:

- truthfulness
- scope fit
- simplicity
- explainability
- validation burden
- implementation burden
- coverage

Legacy similarity is not a primary criterion.

### 3. Treat unresolved cases honestly

If a method cannot assign signal-relative orientation confidently for some rows, corridors, or intersections, those cases should remain unresolved rather than being forced into a weak or misleading label.

### 4. Preserve analytical meaning, not legacy machinery

Outputs should preserve the meaning needed by the analysis, but intermediate logic may be redesigned aggressively.

## Evidence Standards

All analytical claims should identify the kind of evidence they rely on.

Useful evidence categories include:

- direct observed attribute evidence
- geometric support evidence
- roadway-context evidence
- empirically inferred evidence from repeated observations
- externally linked network evidence
- hybrid evidence from multiple sources

The methodology must distinguish between strong evidence and support-only evidence. A support field should not be presented as final truth unless it has been validated for that purpose.

## Validation Philosophy

Validation should be built around the redesigned method actually being used, not around preserving inherited effort.

Validation may include:

- row and feature counts
- field completeness
- geometry usability checks
- agreement rates among filtered empirical crash evidence and support-only context fields
- spot checks on mapped corridors
- comparison of candidate methods on the same bounded subset
- explicit unresolved-rate reporting
- behavioral comparisons against earlier outputs where useful

Legacy parity is useful when it helps interpret redesign choices, but parity is not the project goal by itself.

## Repository Treatment Principle

The current repository should be treated as a source of artifacts, experiments, partial methods, and reusable components.

It should not be treated as a trusted system.

Existing code and documents may contain:

- useful logic
- useful data contracts
- useful field mappings
- useful QC patterns
- useful outputs for comparison
- legacy assumptions that should be removed
- overbuilt structures caused by earlier methodological commitments

The redesign process must therefore scrutinize all existing components aggressively. Retain only what is helpful to the simplified and truthful workflow. Move preserved but non-active material into clearly marked legacy areas so that active development does not remain entangled with obsolete logic.

## Documentation Role

This document defines project goals and methodological posture. It intentionally does not lock the project into one inherited execution path.

A separate operating contract should govern how the repository is evaluated, simplified, reorganized, and rebuilt under this methodology.

That operating contract should instruct the coding agent to:

- treat current code as untrusted until examined
- prefer aggressive simplification where justified
- keep only components that clearly serve the current methodology
- isolate legacy material from active code paths
- compare multiple candidate methods when the current one appears overcomplicated
- treat excessive implementation effort as a signal to re-examine assumptions
- prioritize concise, testable vertical slices over deep inherited complexity

## Practical Redesign Sequence

The intended sequence from this document is:

1. Establish the new high-level methodology and project goals.
2. Use that methodology to define a new operating contract for repository redesign.
3. Evaluate the existing repository as an artifact collection rather than as a trusted baseline.
4. Preserve potentially useful materials in legacy storage where appropriate.
5. Build the new active workflow around the simplest methods that truthfully support the project goals.
6. Expand only after a bounded, validated approach is working.

## Summary

This project is not a migration exercise for its own sake.

It is a redesign effort whose purpose is to produce the simplest trustworthy workflow for downstream functional area analysis in Virginia.

Existing code is evidence, not authority.
Existing methodology is a candidate, not a command.
The project should be framed around signals and bounded near-signal evidence, not around roadway rows as an end in themselves.
Signal-relative flow orientation is required as a supporting inference, but the method for assigning it remains open.
Cardinal labels are useful only insofar as they support upstream/downstream or approaching/leaving interpretation near signals.
The repository should be simplified aggressively until the active workflow matches the real analytical problem instead of inherited implementation momentum.
