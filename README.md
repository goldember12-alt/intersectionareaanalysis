# IntersectionCrashAnalysis

This repository is in an active redesign state, but the current bounded workflow is runnable again.

Start with:

- [docs/README.md](docs/README.md)
- [docs/methodology/overview_methodology.md](docs/methodology/overview_methodology.md)
- [AGENTS.md](AGENTS.md)
- [docs/workflow/active_workflow.md](docs/workflow/active_workflow.md)
- [docs/workflow/enrichment_plan.md](docs/workflow/enrichment_plan.md)

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
