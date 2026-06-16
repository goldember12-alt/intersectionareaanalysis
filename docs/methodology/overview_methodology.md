# Core Methodology: Stable-Lineage Scaffold for Downstream Functional Area Analysis

**Status: CURRENT ACTIVE OVERVIEW.** The detailed current method is documented in `roadway_graph_methodology.md`. This file gives the repository-level methodology and explains how the current recovery-first, stable-lineage roadway scaffold supports later access and crash/catchment analysis.

## Purpose

This project evaluates downstream functional area conditions at signalized intersections in Virginia using roadway, signal, access, crash, speed, volume, median, geographic, and related contextual data.

The goal is not to preserve a legacy implementation path. The goal is to produce a trustworthy, explainable, maintainable analytical workflow that can support Virginia-specific downstream functional area understanding and eventual guidance.

The current active methodology is:

base staged signals -> represented signal universe -> calibrated expected physical-leg model -> recovery-first scaffold completion -> divided/carriageway subbranch normalization -> source/data limitation ledger -> stable Travelway lineage persistence at bin generation -> review-only speed/AADT/access context -> crash/catchment design only after scaffold and lineage QA.

## Core Principle

Prefer the simplest method that truthfully solves the current analytical problem.

Complexity is not a virtue by itself. If a proposed method requires repeated bridge logic, fragile lineage recovery, excessive staging layers, or elaborate exception handling, that complexity should be treated as diagnostic evidence that the method may be mismatched to the problem.

The workflow should favor methods that are understandable, testable, bounded in scope, empirically grounded where appropriate, easy to validate, and proportionate to the question being asked.

## Recovery-First Philosophy

The project now treats scaffold recovery as an explicit methodology step rather than a side diagnostic. The goal is to preserve and recover every defensible signal, physical leg, bin, and context record before access or crash assignment.

Recovery does not mean forcing uncertain labels. It means:

- recover missing physical legs where source Travelway, graph, and intersection-zone evidence support them;
- normalize divided carriageways, ramps, source-line splits, route/facility changes, and candidate-branch artifacts as subbranches or QA attributes under physical legs;
- keep partial but defensible records visible;
- carry unresolved records as review-only flags;
- distill remaining losses into clear source/data limitations, grade/mainline holdouts, still-insufficient evidence, or manual-review classes.

Source limitation findings are part of the project value. They explain where available source systems do not support a defensible signal-relative scaffold, access inventory, or later crash/catchment claim.

## Final Represented Universe

The current review-only represented universe contains:

- base staged signals: 3,933
- represented signals: 2,739
- represented share: about 69.6%
- speed+AADT-ready signals: 2,739
- final scaffold bins: 262,329

This universe is review-only. It is mature enough to support access doctrine and crash/catchment design, but it should not be described as a promoted active production output until the handoff is explicitly made.

## Final Physical-Leg Model

The calibrated final physical-leg distribution is:

- one-leg: 234
- two-leg: 195
- three-leg: 798
- four-leg: 1,511
- five-plus: 1
- two-leg-or-less combined: 429

Four-leg intersections dominate, three-leg intersections are the next major class, five-plus cases have been reduced to near zero, and two-leg-or-less cases are carried with source/geometry explanation flags.

A physical leg is a signalized-intersection approach. It is not a graph edge, source row, route name, carriageway, or candidate association. Divided carriageways, ramps, route/facility changes, and source-line splits should generally be represented as subbranches or attributes under a physical leg unless evidence supports a distinct physical approach.

Intersection-zone and geometry-bearing logic are central. They define approach sectors, missing-leg candidates, divided/subbranch normalization, and review queues without relying on crash evidence.

## Stable Travelway Lineage

Stable Travelway lineage is a core pipeline requirement. It must be persisted during scaffold/bin generation, not only reconstructed later.

The stable-lineage scaffold regeneration produced:

- regenerated signals: 2,739
- regenerated bins: 262,329
- high-confidence stable Travelway lineage: 262,327
- low-confidence lineage: 2
- unmatched bins: 0
- prior unmatched bins recovered: 111,200 / 111,200

Every future scaffold, access, crash, and source-limitation output that depends on Travelway geometry should carry:

- `stable_travelway_id`
- `stable_signal_id`
- `source_signal_id`
- `stable_bin_id`
- `source_layer`
- `source_route_id`
- `source_route_name`
- `source_route_common`
- `source_measure_start`
- `source_measure_end`
- `source_feature_local_fid`
- `geometry_hash`
- `lineage_match_method`
- `lineage_confidence`

GeoPackage `fid` is package-local and must not be used as the sole source-lineage key.

## Source/Data Limitation Ledger

The scaffold recovery branches are currently summarized as:

- Branch A, direct missing-leg recovery: complete after final context refresh.
- Branch B, divided/carriageway normalization: complete enough to proceed.
- Branch C, source limitation/holdout: reduced to manual, external-data, and source limitations.

Remaining source/data limitation ledger:

- source_limited_holdout: 281
- grade_separated_or_mainline_contamination: 49
- still_insufficient_geometry_evidence: 54

These are not hidden losses. They should remain visible in downstream access and crash/catchment outputs as QA flags.

## Access Doctrine

Access is not currently the highest-priority recovery issue. Manual review and source accounting indicate substantial source coverage limitations, especially major-route bias.

Current access source counts:

- untyped source points: 70,595
- typed v2 source points: 28,762

Nearly all access source points appear to be on major route classes. Low access capture should therefore not be interpreted automatically as scaffold failure.

Current access doctrine:

- Untyped access remains the broad count/density layer.
- Typed v2 access remains an enrichment layer.
- Spatial 100 ft catchment is the conservative primary review product.
- Conservative Travelway-windowed access is a source-identity sensitivity/enrichment product.
- Broad Travelway-normalized access is source-coverage diagnostic evidence only because it has long-route overcapture risk.
- Access points may legitimately multi-assign to more than one signal-relative context.
- Unweighted/double-counted and source-preserving weighted products must remain separate.
- Raw typed access codes must be preserved next to corrected categories.

Typed v2 code mapping currently treats `R` and `RC` as `right_in_right_out`; `I`, `M`, `S`, `AS`, and `AU` remain `other_review`.

## Map-Review Lessons

Manual map review sharpened several methodological requirements:

- `signal_000045` demonstrated the need for stable source Travelway lineage. The reviewed source Travelway leg FID 52369 remains candidate/ambiguous, while FID 46419 is the best match for 50 bins. Stable IDs, not package-local FIDs alone, must support these claims.
- `signal_002692` is primarily a complex multi-signal ownership/source-signal limitation. Opposite carriageway legs should not be forced onto the wrong signal when missing source signals likely own that carriageway.
- The Wellington Road / University Boulevard HMMS signal exists in normalized/staged records but not in the final represented universe. This is a signal-source lineage and complex exclusion issue, not a Travelway FID issue.

## Why Crashes Are Delayed

Crash data is delayed because crashes should not define the roadway scaffold. The scaffold must first answer no-crash questions:

- Which represented signals have enough source/graph geometry evidence?
- Which physical legs and subbranches are defensible?
- Which bins have stable Travelway lineage, route/measure context, speed, AADT, and exposure readiness?
- Which records remain source-limited, grade/mainline, still-insufficient, or manual-review holdouts?

Only after those questions are answered should crashes be spatially or route/measure assigned to signal-relative records. Crash findings can inform downstream guidance, but they should not be treated as the sole basis for downstream functional area distance.

## Historical Signal-Centered Work

Older signal-centered Package 001/002/003, directed_segments, directionality_experiment, upstream_downstream_prototype, and early TRUE-reference graph-foundation documentation are preserved as historical or supporting reference.

That work remains useful because it records earlier assumptions, crash-evidence directionality experiments, descriptive package designs, and context-enrichment ideas. It is not the current methodology.

## Proposal Alignment

The companion document `proposal_alignment_growth_plan.md` describes how this analytical backend should grow toward the larger VTRC proposal. The current method supports that growth by establishing a stable-lineage signal-relative scaffold first.

Proposal-facing outputs should remain descriptive or exploratory until the workflow defines the downstream band family, analysis unit, denominator availability, unresolved-case handling, evidence provenance, and validation checks.

Crash findings can inform downstream guidance, but they should not be treated as the sole basis for functional-area distance.

## Current Next Step

The current next step is to finalize the access doctrine/readout and prepare figure/paper materials around:

- final represented signal universe and physical-leg distribution;
- stable Travelway lineage discipline;
- source/data limitation ledger;
- access source coverage limitations and major-route bias;
- conservative spatial access and Travelway-windowed sensitivity evidence.

After that, crash/catchment assignment should be designed using the stable-lineage scaffold and carried QA flags.

## Documentation Map

Use these documents first:

- `current_methodology_index.md`
- `roadway_graph_methodology.md`
- `proposal_alignment_growth_plan.md`
- `../workflow/current_workflow_index.md`
- `../workflow/roadway_graph_workflow.md`
- `../workflow/active_workflow.md`
- `../workflow/access_code_mapping_notes.md`
- `../workflow/roadway_graph_lineage_requirements.md`

Raw generated outputs belong under `work/output/`. Curated readouts belong under `docs/results/` or, for now, under `docs/workflow/` when they are still operational roadway_graph readouts. Polished/shareable reports belong under `docs/reports/`.
