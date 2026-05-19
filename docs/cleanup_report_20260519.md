# Repository Cleanup Report - 2026-05-19

## Bounded Question

Clean the repository after completion of the roadway-derived directional-bin context prototype so active docs and active work outputs describe the product rather than temporary recovery, audit, and exploratory scratchwork.

## Summary

- docs cleaned: yes
- work cleaned: yes
- source behavior changed: no
- final/current product outputs deleted: no
- commits made: no

The cleanup moved 184 items and recorded 0 move failures in:

`work/output/roadway_graph/review/current/repo_cleanup_inventory/`

## Active Docs Preserved

- `docs/README.md`
- `docs/overview_methodology.md`
- `docs/methodology/current_methodology_index.md`
- `docs/methodology/overview_methodology.md`
- `docs/methodology/roadway_graph_methodology.md`
- `docs/methodology/proposal_alignment_growth_plan.md`
- `docs/workflow/active_workflow.md`
- `docs/workflow/current_workflow_index.md`
- `docs/workflow/roadway_graph_workflow.md`
- `docs/workflow/roadway_graph_directional_context_milestone.md`
- `docs/design/current_design_index.md`
- `docs/design/roadway_graph_context_enrichment_plan.md`

## Active Output Folders Preserved

- `work/output/roadway_graph/analysis/current/directional_bin_context_table/`
- `work/output/roadway_graph/analysis/current/crash_directional_assignment_descriptive_summary/`
- `work/output/roadway_graph/review/current/reference_signal_directional_scaffold/`
- `work/output/roadway_graph/review/current/reference_signal_directional_scaffold_qa/`
- `work/output/roadway_graph/review/current/reference_signal_directional_bin_catchments/`
- `work/output/roadway_graph/review/current/crash_directional_catchment_assignment_prototype/`
- `work/output/roadway_graph/review/current/crash_directional_catchment_assignment_qa/`
- `work/output/roadway_graph/review/current/crash_directional_assignment_analysis_readiness/`
- `work/output/roadway_graph/review/current/access_context_join/`
- `work/output/roadway_graph/review/current/roadway_identity_metadata_propagation/`
- `work/output/roadway_graph/review/current/speed_context_join_v4_identity_enriched/`
- `work/output/roadway_graph/review/current/aadt_context_join_v3_identity_route_measure/`
- `work/output/roadway_graph/review/current/urban_rural_source_recovery/`
- `work/output/roadway_graph/review/current/context_source_inventory/`
- `work/output/roadway_graph/review/current/posted_speed_source_staging/`
- `work/output/roadway_graph/review/current/aadt_source_staging/`

Crash assignment QA, interpretation-readiness, mapless-review, and eligibility folders were also preserved under `review/current/` as supporting assignment audit evidence.

## Legacy And Archive Folders Created

- `docs/archive/20260519_cleanup/`
- `work/archive/20260519_cleanup/`
- `work/output/roadway_graph/review/history/repo_cleanup_20260519/`
- `work/output/roadway_graph/runs/history/repo_cleanup_20260519/`

## Files Moved

Detailed move records:

- `work/output/roadway_graph/review/current/repo_cleanup_inventory/cleanup_moves.csv`
- `work/output/roadway_graph/review/current/repo_cleanup_inventory/cleanup_failures.csv`
- `work/output/roadway_graph/review/current/repo_cleanup_inventory/cleanup_manifest.json`

Move categories:

- superseded/supporting docs archived after directional context product: 65
- legacy or smoke work outputs archived after directional context product: 10
- superseded roadway_graph diagnostics or intermediate context attempts archived from `review/current`: 15
- loose root review files archived from `review/current`: 92
- root roadway_graph GeoJSON review layer folder archived: 1
- superseded speed v3 smoke run archived from `runs/current`: 1

## Files Not Moved And Why

- `artifacts/normalized/`: preserved as normalized source artifacts for reproducibility.
- `src/active/roadway_graph/`: preserved as active source code.
- `work/output/roadway_graph/tables/current/`: preserved as roadway graph foundation/current table lineage.
- final context product outputs under `analysis/current/directional_bin_context_table/`: preserved.
- accepted final context-layer folders under `review/current/`: preserved.
- crash assignment support QA folders under `review/current/`: preserved because they explain excluded, ambiguous, unresolved, and eligibility cases.

## Stale References Fixed

- `docs/README.md` rewritten to distinguish active docs from archive docs.
- `docs/workflow/current_workflow_index.md` rewritten around the current product.
- `docs/workflow/active_workflow.md` rewritten around the current product and active output folders.
- `docs/design/current_design_index.md` rewritten to remove stale design candidates.
- `docs/workflow/roadway_graph_workflow.md` updated so older detailed workflow references point to `docs/archive/20260519_cleanup/`.
- `docs/workflow/roadway_graph_directional_context_milestone.md` created.
- `docs/overview_methodology.md` added as a pointer to the canonical methodology overview.

## Manual Review Items

- Review whether the preserved crash assignment support QA folders should remain under `review/current/` or be archived after manual review is complete.
- Review whether `roadway_graph_workflow.md` should eventually be shortened to match the product-oriented docs, while keeping the detailed archived step docs available.
- Generated `__pycache__` files were detected under `src/`; recursive deletion was not performed because the shell policy blocked that cleanup command. They are generated junk and can be removed manually if desired.
- Decide whether the prototype should be hardened into a production pipeline before any broader descriptive or modeling outputs are built.

## Validation

Validation performed after cleanup:

- active output folders checked for presence
- cleanup manifest and move/failure records checked
- active documentation references checked with `rg`
- `py_compile` run on active roadway_graph Python files
- `git status --short` run

No data pipelines were rerun.
