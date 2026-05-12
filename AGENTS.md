# AGENTS.md

## Purpose

This file is the operating contract for Codex in this repository.

The repository is an active analytical redesign workspace for Virginia downstream functional area analysis at signalized intersections. It contains active workflow code, useful experiments, generated outputs, legacy artifacts, and older assumptions. Codex must not treat the existing repo as a trusted system.

Trust hierarchy:

1. User instructions for the current task.
2. `docs/methodology/overview_methodology.md`, titled **Core Methodology: Signal-Centered Downstream Functional Area Analysis**.
3. `docs/methodology/proposal_alignment_growth_plan.md`, titled **Proposal Alignment and Growth Plan: Downstream Functional Area Guidance**.
4. This `AGENTS.md` operating contract.
5. Current workflow docs, especially `docs/workflow/active_workflow.md` and `docs/workflow/enrichment_plan.md`.
6. Active source code and generated outputs, treated as evidence to inspect rather than authority to preserve.
7. Legacy docs, legacy code, and old outputs, used only for reference or comparison.

If these sources conflict, follow the higher source and update lower documentation when the task changes methodology, workflow, or output meaning.

## Project Mission

The project supports Virginia downstream functional area analysis at signalized intersections using roadway, signal, crash, access, speed, volume, median, geographic, and related contextual data.

The goal is to produce the simplest trustworthy workflow that can:

- define downstream study areas or comparison zones
- anchor analysis on signalized intersections
- preserve bounded near-signal evidence
- infer signal-relative flow orientation only as needed
- classify crashes and access points as upstream/downstream or approaching/leaving where evidence supports it
- measure crash occurrence and downstream context
- compare sites, roadway contexts, and downstream conditions
- identify patterns and outliers that can inform Virginia-specific guidance

The repo exists to support the larger research charter described in the VTRC proposal: clearer downstream functional area guidance for Appendix F of VDOT's Road Design Manual. The repo is not yet the full proposal. It is currently the analytical backend being grown toward that purpose.

## Core Methodology

The core active methodology is signal-centered downstream functional area analysis.

Signals are the anchor object. The workflow should build bounded near-signal evidence around each signal, then use roadway, crash, access, speed, AADT, median, and contextual data to interpret downstream conditions.

The current practical implementation priority is divided-road analysis. This narrower scope is intentional. A truthful divided-road vertical slice is better than an unfinished universal method.

Codex must always state the bounded question being solved. Examples:

- signal-centered near-signal evidence modeling
- divided-road signal-relative flow orientation
- upstream/downstream crash classification
- downstream access assignment
- downstream distance-band summaries
- proposal-facing descriptive summaries
- comparison-ready modeling outputs

Methods must not silently broaden from one bounded question into a statewide or universal framework.

## Proposal Alignment

The proposal companion document gives the repo a disciplined future path. The required controlled growth sequence is:

1. Keep the current divided-road workflow as the first trustworthy vertical slice.
2. Use it to produce downstream-zone crash/access/AADT/speed/median summaries by signal.
3. Add explicit downstream distance bands matching proposal concepts, such as physical area to limiting value, limiting value to desirable value, fixed buffers, and speed-based bands.
4. Add comparison-ready outputs for regression or descriptive analysis.
5. Expand cautiously beyond divided roads only after the divided-road method is validated.
6. Add roadway-level rural/suburban/urban context from a better source before using those classes as policy variables.
7. Treat crash findings as safety evidence that informs guidance, not as the sole basis for distance calculation.

Do not skip directly to broad regression, spreadsheet calculators, statewide expansion, or policy guidance before the necessary evidence and validation outputs exist.

## Prime Directive

Prefer the simplest method that truthfully solves the current analytical problem.

Complexity must earn its place. If a method requires many bridge layers, lineage-recovery steps, staging contracts, packaging families, exception workflows, or helper stacks, Codex must examine whether the method is mismatched to the current problem.

Good progress is:

- clearer active methodology
- smaller active code paths
- reproducible outputs
- explicit evidence provenance
- visible unresolved cases
- honest validation
- proposal alignment through controlled growth

Good progress is not:

- preserving old machinery by default
- restoring Oracle dependence without proof it is the simplest trustworthy path
- forcing labels for coverage
- hiding uncertainty behind procedural complexity
- broadening beyond divided roads prematurely
- treating crash analysis as a standalone functional-area calculator

## Repository Trust Model

Active code is provisional until inspected.

Generated outputs are evidence, not architecture.

Legacy material may be useful for field discovery, comparison, or historical traceability, but it must not govern active design.

Codex may move, retire, or replace active components when they do not serve the current methodology. When uncertain, prefer moving material to a clearly named legacy area over immediate deletion.

Raw inputs are protected unless the user explicitly says otherwise.

## Active Repository Shape

Current active docs:

- `docs/methodology/overview_methodology.md`
- `docs/methodology/proposal_alignment_growth_plan.md`
- `docs/methodology/flow_method_comparison.md`
- `docs/workflow/active_workflow.md`
- `docs/workflow/enrichment_plan.md`
- `docs/results/directionality_experiment_results.md`

Current active code surface:

- `src/__main__.py`
- `src/active/__main__.py`
- `src/active/config.py`
- `src/active/study_slice.py`
- `src/active/directionality_experiment.py`
- `src/active/upstream_downstream_prototype.py`
- `src/active/high_confidence_upstream_downstream_analysis.py`
- `src/active/context_enrichment.py`
- `src/active/context_enrichment_access_same_corridor_prototype.py`

Current transitional diagnostics:

- `src/transitional/bridge_key_audit.py`
- `src/transitional/bridge_key_geojson_audit.py`

Current active generated-output pattern:

- stable latest artifacts under `current/`
- timestamped retained artifacts under `history/`
- run metadata under `runs/current/` and `runs/history/`
- review summaries and GeoJSON layers where mapped review is useful

Treat grouped `current/` lanes and local README files as the active output contract when older loose output files also exist.

## Current Workflow

The standard package CLI slice is intentionally small:

```powershell
<bootstrap-reported-python> -m src stage-inputs
<bootstrap-reported-python> -m src normalize-stage
<bootstrap-reported-python> -m src build-study-slice
<bootstrap-reported-python> -m src enrich-study-signals-nearest-road
<bootstrap-reported-python> -m src check-parity
```

The restored active analytical modules are direct-entry:

```powershell
<bootstrap-reported-python> -m src.active.directionality_experiment
<bootstrap-reported-python> -m src.active.upstream_downstream_prototype
<bootstrap-reported-python> -m src.active.high_confidence_upstream_downstream_analysis
<bootstrap-reported-python> -m src.active.context_enrichment
<bootstrap-reported-python> -m src.active.context_enrichment_access_same_corridor_prototype
```

Do not invent a new package family or broad orchestration layer unless the bounded implementation proves it is needed.

## Environment Bootstrap

Use the repository bootstrap layer for interpreter discovery.

Preferred entrypoint:

```powershell
.\scripts\bootstrap.cmd
```

`scripts/bootstrap.ps1` is the implementation, but direct PowerShell script execution may be blocked by execution policy. The wrapper is the default documented entry story.

Practical environment rules:

- Python 3.11 is the expected base.
- The active interpreter may be external to the repo.
- TEMP/TMP and pip cache may be externalized.
- Use the interpreter path reported by bootstrap.
- Do not assume `.\.venv\Scripts\python.exe`.
- Do not create or recreate a repo-local `.venv` when external venv mode is already in use unless the user explicitly asks.

## Directionality and Classification Rules

Signal-relative flow orientation is a supporting subproblem, not the final architecture.

Cardinal labels may be useful intermediate aids only when they support upstream/downstream or approaching/leaving interpretation near signals.

Candidate flow-orientation methods may include:

- filtered empirical crash evidence
- roadway context
- network identity
- supplemental traffic-volume support
- hybrid methods with explicit evidence hierarchy

For divided-road analysis, filtered empirical crash evidence is a serious primary candidate when available and coherent. Roadway context and route naming are support-only unless validated for stronger use.

Current empirical conclusions to preserve:

- non-Oracle empirical flow inference is viable enough to continue in some divided-road contexts
- strict unanimity is trustworthy but sparse
- a 90% dominant-share relaxation is a promising bounded variant
- single-vehicle-clean cases are diagnostically useful
- route-name fallback remains support-only and low-trust

Never force signal-relative labels where evidence is weak. Use unresolved, ambiguous, conflict, or support-only statuses honestly.

## Proposal-Facing Output Rules

When adding proposal-facing outputs, prefer signal-centered units first.

Good next output units include:

- one row per signal and downstream band
- one row per signal, approach, and downstream band
- one row per crash with signal-relative and band-relative classification
- one row per access point with signal-relative and band-relative classification

Before creating regression-ready outputs, the workflow must define:

- the downstream band family
- the analysis unit
- the dependent variable
- denominator availability
- unresolved-case handling
- evidence provenance
- validation checks

Do not compute crash-rate, regression, or policy claims before denominator coverage and classification uncertainty have been reviewed.

Crash analysis should inform downstream guidance. It should not be treated as the sole basis for downstream functional area distance.

## Rural, Suburban, and Urban Context

The proposal needs geographic differentiation. The current repo has crash `AREA_TYPE` context, but that is crash-context evidence, not roadway truth.

Do not use crash `AREA_TYPE` as a roadway-level rural/suburban/urban policy variable.

Before using geographic class in modeling or guidance, add and validate a better roadway or area source, such as Census urban area, VDOT classification, functional classification, locality, district, MPO, or another documented source.

Suburban classification is not currently solved.

## Validation Requirements

Validation must match the method being used.

Useful validation includes:

- source row counts
- output row counts
- duplicate-key checks
- field completeness
- geometry usability checks
- AADT/access/crash assignment status counts
- unresolved and conflict rates
- evidence agreement rates
- mapped spot checks
- before/after comparison where useful
- comparison with legacy outputs only as supporting context

Every analytical task should report:

- what was checked
- what was not checked
- what remains uncertain
- which assumptions remain provisional

Do not claim equivalence, correctness, or readiness for modeling unless it was actually examined.

## Documentation Rules

Update active docs when changing:

- methodology
- scope
- active workflow commands
- output semantics
- validation logic
- proposal alignment
- active versus legacy placement

Documentation roles:

- `docs/methodology/overview_methodology.md`: core active methodology
- `docs/methodology/proposal_alignment_growth_plan.md`: proposal alignment and future growth path
- `docs/workflow/active_workflow.md`: current commands and output contracts
- `docs/workflow/enrichment_plan.md`: active context-enrichment contract
- `AGENTS.md`: Codex operating contract
- `legacy/`: consolidated historical preservation root for legacy docs, code, outputs, and reference material

Do not let active docs drift behind code changes.

## Legacy and Retirement Rules

When a component appears unhelpful to the active methodology:

1. Identify what it does.
2. Explain why it is inactive, confusing, duplicative, or methodologically mismatched.
3. Decide whether to delete it or move it to legacy.
4. Update docs and active paths.
5. Verify the active workflow no longer depends on it.

When uncertain, move to legacy rather than delete.

Do not import from legacy in active code unless the task explicitly re-evaluates and promotes a specific piece of logic.

## Operating Sequence for New Work

For methodology or redesign tasks:

1. Read `docs/methodology/overview_methodology.md`.
2. Read `docs/methodology/proposal_alignment_growth_plan.md` if the task touches proposal scope, future guidance, downstream bands, modeling, or broader expansion.
3. Read `docs/workflow/active_workflow.md` for current commands and outputs.
4. State the bounded question being solved.
5. Identify relevant active components.
6. Identify likely legacy/noise components.
7. Choose the smallest truthful next step.
8. Define validation before or alongside implementation.

For narrow bug fixes, inspect the relevant code and docs first, then make the smallest safe change.

## Task Completion Standard

A task is not complete until the relevant combination of code, configuration, docs, validation notes, output checks, and active/legacy placement decisions has been updated consistently.

For redesign or methodology work, final reporting must state:

- what was kept active
- what was added
- what was moved to legacy or removed
- what remains uncertain
- how the change aligns with the core methodology
- how the change relates to the proposal growth plan, when relevant

For proposal-aligned work, also state:

- which proposal concept it supports
- whether it remains divided-road-only
- what evidence source it uses
- what output unit it creates
- whether the output is descriptive, exploratory, or modeling-ready

## Non-Negotiables

Codex must not:

- treat the current repo as trusted by default
- assume Oracle is required
- assume migration parity is the goal
- preserve old staging or packaging layers without clear value
- silently keep legacy artifacts in active paths
- force labels where evidence is weak
- treat support-only roadway context as final truth
- use crash `AREA_TYPE` as roadway-level geographic truth
- broaden beyond divided roads without saying so
- treat crash findings as the sole basis for functional-area distance
- claim validation that was not performed
- hide ambiguity behind complexity

The repository is being redesigned into a smaller, clearer, more trustworthy analytical system that can grow into the proposal's analytical backend without losing evidence discipline.
