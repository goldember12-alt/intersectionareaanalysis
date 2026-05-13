# Current Workflow Index

## Six-Folder Contract

- `docs/design/` = proposed schemas, planning, future designs
- `docs/methodology/` = stable methodological explanations
- `docs/diagrams/` = figure/source diagram assets
- `docs/reports/` = polished/shareable reports
- `docs/results/` = curated result/readout summaries, not raw CSVs
- `docs/workflow/` = active commands, output contracts, and operational notes

## Workflow Folder Contract

`docs/workflow/` is for active working documentation: commands, output contracts, QA procedures, current module status, and implementation notes. It should not hold polished reports, stable methodology, or legacy method docs except temporarily with clear status notes.

## Current Active Roadway Graph Workflow

Use these first for the graph-first workflow:

- `roadway_graph_workflow.md`
- `roadway_graph_step5_eligibility_gating.md`
- `roadway_graph_step5_oriented_segment_prototype.md`
- `roadway_graph_step5_crash_ready_subset.md`
- `roadway_graph_crash_assignment_prototype.md`
- `roadway_graph_geometric_direction_model.md`
- `roadway_graph_divided_carriageway_pairing.md`
- `roadway_graph_roadway_role_classification.md`
- `roadway_graph_qgis_review_layers.md`

## Current Support Workflow

- `active_workflow.md`: operational map for the current graph-first workflow plus historical/supporting direct-entry modules.
- `staging_and_normalization_contract.md`: current staging/normalization support contract.
- `windows_file_lock_manual_cleanup_guide.md`: current operational cleanup guide.
- `github_publishing_guide.md`: current repository publishing guide.

## Next Technical Step

The next implementation task is divided-pairing recovery using roadway role classification. Start with unpaired `mainline_divided_carriageway` rows, preserve accepted high/medium-confidence pairs, avoid broad graph repair, and do not use crash direction as an upstream/downstream source.

## Current Audit Outputs

- `documentation_reorganization_audit.md`
- `documentation_file_classification.csv`
- `documentation_relocation_plan.csv`
- `documentation_link_update_plan.csv`
- `documentation_reorganization_stage_a_b_completed.md`
- `documentation_reorganization_move_log.csv`
- `documentation_reorganization_link_check.csv`
- `documentation_final_consolidation.md`
- `documentation_final_link_check.csv`
- `documentation_current_state_summary.md`

## Supporting Or Historical Workflow Docs

- Directed segment workflow docs moved to `../../legacy/docs/workflow/` or `../../legacy/docs/results/`.
- Directionality and upstream/downstream prototype docs moved to `../../legacy/docs/` where the relocation plan marked them clearly superseded.
- Context enrichment docs are supporting references unless a later graph-first crash/access migration promotes them.
- Proposal descriptive Package 001/002/003 docs remain in `docs/workflow/` with legacy signal-centered package banners for now.
- `package_003_signal_outlier_map_review_batch_A_guide.md` moved to `../../legacy/docs/workflow/package_003_signal_outlier_map_review_batch_A_guide.md`.
