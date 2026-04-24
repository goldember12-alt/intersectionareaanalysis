# IntersectionCrashAnalysis

This repository is in an active redesign state, but the current bounded workflow is runnable again.

Start with:

- [docs/README.md](docs/README.md)
- [docs/methodology/overview_methodology.md](docs/methodology/overview_methodology.md)
- [docs/methodology/proposal_alignment_growth_plan.md](docs/methodology/proposal_alignment_growth_plan.md)
- [AGENTS.md](AGENTS.md)
- [docs/workflow/active_workflow.md](docs/workflow/active_workflow.md)
- [docs/workflow/enrichment_plan.md](docs/workflow/enrichment_plan.md)

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

## Current active workflow surface

The current active workflow has two layers:

1. Standard package CLI slice under `-m src`
   - `bootstrap`
   - `stage-inputs`
   - `normalize-stage`
   - `build-study-slice`
   - `enrich-study-signals-nearest-road`
   - `check-parity`
2. Restored direct-entry analytical modules under `src/active/`
   - `python -m src.active.directionality_experiment`
   - `python -m src.active.upstream_downstream_prototype`
   - `python -m src.active.high_confidence_upstream_downstream_analysis`

The direct-entry modules are meaningful again, but they are not yet integrated into the main package CLI.

## Restored output areas

The working tree now has regenerated outputs for:

- `work/output/stage1b_study_slice/`
- `work/parity/`
- `work/output/directionality_experiment/`
- `work/output/upstream_downstream_prototype/`
- `work/output/upstream_downstream_prototype/high_confidence_descriptive_analysis/`

Grouped `current/` output contracts now exist for directionality, prototype, and high-confidence downstream analysis. Some older flat-layout residue may still remain in parts of `work/` from pre-hardening runs, so trust the grouped `current/` lanes and local `README.md` files over older loose files when both are present.

Manual QGIS PNG exports are not regenerated automatically by the Python steps.

## Repo layout

- `src/active/` - current bounded runtime plus restored direct-entry experimental/downstream modules
- `src/transitional/` - transitional diagnostics still referenced by the narrowed workflow
- `config/` - active runtime config
- `scripts/` - bootstrap and environment entrypoints
- `artifacts/` - tracked staged and normalized intermediates
- `work/` - ignored runtime outputs and review products
- `docs/` - active methodology, workflow, planning, and design docs
- `docs/legacy/` - recent dated recovery and cleanup notes kept for historical context
- `legacy/` - older archived code, docs, and reference material




