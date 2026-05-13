# IntersectionCrashAnalysis

This repository is in an active redesign state, but the current bounded workflow is runnable again.

Start with:

- [docs/README.md](docs/README.md)
- [docs/methodology/current_methodology_index.md](docs/methodology/current_methodology_index.md)
- [docs/methodology/roadway_graph_methodology.md](docs/methodology/roadway_graph_methodology.md)
- [docs/workflow/current_workflow_index.md](docs/workflow/current_workflow_index.md)
- [docs/workflow/roadway_graph_workflow.md](docs/workflow/roadway_graph_workflow.md)
- [docs/methodology/overview_methodology.md](docs/methodology/overview_methodology.md)
- [docs/methodology/proposal_alignment_growth_plan.md](docs/methodology/proposal_alignment_growth_plan.md)
- [AGENTS.md](AGENTS.md)
- [docs/workflow/active_workflow.md](docs/workflow/active_workflow.md)

## Canonical Working Copy

The canonical working copy for this repository should live outside OneDrive, under a normal local development path such as:

- `C:\Users\Jameson.Clements\source\IntersectionCrashAnalysis`

Treat any OneDrive-hosted copy as transitional only. The workflow writes frequently under `work/` and depends on stable replacement of grouped `current/` outputs, so sync-driven file locking is a real operational risk.

If you are converting a prior OneDrive working tree into the local canonical copy, copy the ignored local working-state directories deliberately when needed:

- `artifacts/`
- `work/`
- `legacy/`
- `Intersection Crash Analysis Layers/`

Do not rely on moving a repo-local `.venv/` between locations. Use the bootstrap flow to discover or recreate the active interpreter instead.

## Current Active Workflow Surface

The current active analytical method is graph-first:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after the roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction -> unresolved/review-only cases preserved.

The current active workflow has two layers:

1. Standard package CLI slice under `-m src`
   - `bootstrap`
   - `stage-inputs`
   - `normalize-stage`
   - `build-study-slice`
   - `enrich-study-signals-nearest-road`
   - `check-parity`
2. Current graph-first direct-entry analytical modules under `src/active/roadway_graph/`
   - `python -m src.active.roadway_graph`
   - `python -m src.active.roadway_graph.crash_assignment`
   - `python -m src.active.roadway_graph.geometric_direction`
   - `python -m src.active.roadway_graph.divided_carriageway_pairing`
   - `python -m src.active.roadway_graph.roadway_role_classification`

The older signal-centered Package 001/002/003, directed_segments, directionality_experiment, and upstream_downstream_prototype docs are preserved as historical or supporting reference, not the current methodology.

## Output Areas

The current active graph-first outputs are under:

- `work/output/roadway_graph/`

Historical or supporting output areas include:

- `work/output/stage1b_study_slice/`
- `work/parity/`
- `work/output/directionality_experiment/`
- `work/output/upstream_downstream_prototype/`
- `work/output/upstream_downstream_prototype/high_confidence_descriptive_analysis/`

Grouped `current/` output contracts still matter where present. Some older flat-layout residue may remain in parts of `work/`, so trust grouped `current/` lanes and local `README.md` files over older loose files when both are present.

Manual QGIS PNG exports are not regenerated automatically by the Python steps.

## Repo layout

- `src/active/roadway_graph/` - current graph-first roadway_graph modules
- `src/active/` - standard active runtime plus historical/supporting direct-entry modules
- `src/transitional/` - transitional diagnostics still referenced by the narrowed workflow
- `config/` - active runtime config
- `scripts/` - bootstrap and environment entrypoints
- `artifacts/` - active local staged and normalized intermediates
- `work/` - ignored runtime outputs and review products
- `docs/` - active methodology, workflow, planning, and design docs
- `legacy/` - consolidated historical preservation root for retired code, archived docs, recovery audits, old outputs, and reference material




