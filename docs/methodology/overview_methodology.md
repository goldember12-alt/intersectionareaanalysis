# Core Methodology: Graph-First Downstream Functional Area Analysis

**Status: CURRENT ACTIVE OVERVIEW.** The detailed current method is documented in `roadway_graph_methodology.md`. This file gives the stable repository-level methodology and explains how older signal-centered work relates to the current graph-first path.

## Purpose

This project evaluates downstream functional area conditions at signalized intersections in Virginia using roadway, signal, crash, access, speed, volume, median, geographic, and related contextual data.

The goal is not to preserve a legacy implementation path. The goal is to produce a trustworthy, explainable, maintainable analytical workflow that can support Virginia-specific downstream functional area understanding and eventual guidance.

The current active methodology is roadway_graph / Step 5 graph-first:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after the roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction -> unresolved/review-only cases preserved.

## Core Principle

Prefer the simplest method that truthfully solves the current analytical problem.

Complexity is not a virtue by itself. If a proposed method requires repeated bridge logic, fragile lineage recovery, excessive staging layers, or elaborate exception handling, that complexity should be treated as diagnostic evidence that the method may be mismatched to the problem.

The workflow should favor methods that are understandable, testable, bounded in scope, empirically grounded where appropriate, easy to validate, and proportionate to the question being asked.

## Current Graph-First Scaffold

The active workflow starts with roadway geometry rather than crashes. It builds a full Travelway graph, associates signals to graph components, applies signal eligibility gates, and then creates signal-to-anchor roadway segments and 50-foot bins.

This scaffold is signal-centered in analytical purpose, but graph-first in construction. Signals remain the reference object for downstream analysis. Roadway geometry supplies the scaffold that defines which signal-to-anchor segments and bins are eligible for later crash/access/context assignment.

The graph-first scaffold intentionally retains both divided and undivided roads. The current method must not silently narrow the graph to divided roads only.

## Why Crashes Are Delayed

Crash data is delayed because crashes should not define the roadway scaffold. The scaffold must first answer no-crash questions:

- Which signals have enough roadway evidence to be reference signals?
- Which signal-to-anchor segments are usable?
- Which bins belong to each usable segment?
- Which rows are divided carriageways, undivided centerlines, ramps, frontage roads, auxiliary lanes, one-way candidates, or unknown review cases?

Only after those roadway questions are answered should crashes be spatially assigned to segment/bin records. Even then, crash assignment is not the same as final upstream/downstream interpretation. The current crash assignment prototype assigns crashes conservatively to the nearest crash-ready segment/bin and leaves event direction and upstream/downstream status unresolved.

## TRUE Signal Eligibility

TRUE signal eligibility exists to protect the reference-signal side of the analysis. A TRUE signal is one whose nearby roadway evidence is complete enough to serve as an analysis anchor under the current graph rules.

FALSE and CONDITIONAL signals are still useful evidence, but they should not silently enter the analysis as reference signals. They may appear in review outputs, supporting context, or future explicitly documented promotion logic.

## Opposite Anchors

The opposite anchor does not have to be a TRUE signal. Step 5 is A-centered: the reference signal must be TRUE, but the other end of a segment may be a valid signal, roadway intersection, or endpoint boundary.

This distinction matters because a non-TRUE opposite signal can still be a valid boundary even when it is not eligible to act as the reference signal for its own analysis row. The method should preserve that boundary evidence without treating the opposite anchor as an approved reference signal.

## Roadway Role Before Pairing Recovery

Roadway role classification comes before divided-pairing recovery because not every unpaired divided-looking row should be recovered the same way.

The current role layer separates mainline divided carriageways from undivided centerlines, ramps/connectors, frontage/service roads, turn lanes/auxiliary features, one-way pair candidates, and unknown review cases. Pairing recovery should focus first on `mainline_divided_carriageway` records and should handle one-way pair candidates only through a separate reviewed one-way method.

This avoids broad graph repair that treats every unresolved row as the same problem.

## Divided Roads

For divided roads, upstream/downstream interpretation should use roadway geometry and accepted carriageway pairing, not crash direction.

The geometric direction model and divided carriageway pairing diagnostic are no-crash methods. They use graph geometry, segment geometry, and pairing evidence to identify accepted high/medium-confidence divided carriageway pairs and unresolved cases. Crash direction remains historical/supporting evidence only unless a later bounded task explicitly re-evaluates it.

## Undivided Roads

Undivided roads are shared centerline records by default. They should not be forced into physical directional carriageways.

Later crash interpretation on undivided roads may need side-of-centerline, approach/leaving, or bidirectional logic, but the current scaffold should preserve undivided centerlines as shared/bidirectional geometry until that method is explicitly designed and validated.

## Unresolved And Review-Only Cases

Unresolved and review-only cases are part of the method, not failures to hide. The workflow should preserve:

- FALSE and CONDITIONAL signal eligibility rows
- excluded or review-only segment rows
- unresolved divided-pairing rows
- unknown roadway-role rows
- crash assignment rows whose event direction or upstream/downstream status is not yet interpretable

Coverage should not be improved by forcing weak labels. The repository should make unresolved rates and review queues visible so later work can target the highest-value recovery problem.

## Historical Signal-Centered Work

Older signal-centered Package 001/002/003, directed_segments, directionality_experiment, and upstream_downstream_prototype documentation is preserved as historical or supporting reference.

That work remains useful because it records earlier divided-road vertical-slice assumptions, crash-evidence directionality experiments, downstream descriptive package designs, and context-enrichment ideas. It is not the current methodology.

Current graph-first work may reuse concepts from those packages only after the graph scaffold, crash-ready subset, roadway role classification, divided-pairing recovery, and crash assignment QA make the reuse appropriate.

## Proposal Alignment

The companion document `proposal_alignment_growth_plan.md` describes how this analytical backend should grow toward the larger VTRC proposal. The current method supports that growth by establishing a defensible roadway scaffold first.

Proposal-facing outputs should remain descriptive or exploratory until the workflow defines the downstream band family, analysis unit, denominator availability, unresolved-case handling, evidence provenance, and validation checks.

Crash findings can inform downstream guidance, but they should not be treated as the sole basis for functional-area distance.

## Current Next Step

The divided-pairing recovery prototype now exists as review-only evidence. The next technical step is QGIS review of its low-confidence candidates and still-unresolved rows. A narrower recovery rule should be promoted only if mapped review supports it, and broad graph repair or modeling claims should still wait.

## Documentation Map

Use these documents first:

- `current_methodology_index.md`
- `roadway_graph_methodology.md`
- `proposal_alignment_growth_plan.md`
- `../workflow/current_workflow_index.md`
- `../workflow/roadway_graph_workflow.md`
- `../workflow/active_workflow.md`

Raw generated outputs belong under `work/output/`. Curated readouts belong under `docs/results/` or, for now, under `docs/workflow/` when they are still operational roadway_graph readouts. Polished/shareable reports belong under `docs/reports/`.
