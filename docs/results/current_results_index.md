# Current Results Index

## Six-Folder Contract

- `docs/design/` = proposed schemas, planning, future designs
- `docs/methodology/` = stable methodological explanations
- `docs/diagrams/` = figure/source diagram assets
- `docs/reports/` = polished/shareable reports
- `docs/results/` = curated result/readout summaries, not raw CSVs
- `docs/workflow/` = active commands, output contracts, and operational notes

## Results Folder Contract

`docs/results/` is for curated narrative summaries of important audit, QA, and experiment findings. It is not a raw output folder. Raw CSV, GeoJSON, run metadata, and review tables should remain under `work/output/.../current/` and `work/output/.../history/`.

## Current Workflow Readouts

The current graph-first result/readout summaries are still mostly stored in `docs/workflow/` because they remain operational roadway_graph readouts. Do not use raw CSVs here; raw tables remain under `work/output/roadway_graph/`.

Current workflow readouts:

- `../workflow/roadway_graph_initial_qa_readout.md`
- `../workflow/roadway_graph_foundation_audit.md`
- `../workflow/roadway_graph_manual_review_diagnosis.md`
- `../workflow/roadway_graph_step5_eligibility_audit.md`
- `../workflow/roadway_graph_step5_oriented_segment_qa.md`
- `../workflow/roadway_graph_step5_readiness_revision.md`
- `../workflow/roadway_graph_step5_crash_ready_summary_qa.md`
- `../workflow/roadway_graph_divided_pairing_unresolved_diagnosis.md`
- `../workflow/roadway_graph_divided_undivided_directional_framework_audit.md`
- `../workflow/roadway_graph_roadway_role_classification.md`
- `../workflow/roadway_graph_crash_assignment_prototype.md`

Future consolidation may move these curated readouts into `docs/results/`, but this pass leaves them in place to avoid unnecessary relocation before commit.

## Historical Result Summaries

- `../../legacy/docs/results/directionality_experiment_results.md`: historical divided-road empirical flow-orientation result summary.
- `../../legacy/docs/results/directed_signal_leg_initial_qa_readout.md`: historical directed signal-leg QA readout.

## Result Documentation Gaps

Roadway_graph has strong operational readouts, but the curated results folder itself lacks final graph-first summary pages for:

- eligibility gating
- Step 5 readiness
- crash-ready segment/bin subset
- divided pairing
- roadway role classification
- crash assignment QA

Those should be created or moved here after Stage A status banners.
