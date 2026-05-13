# Documentation Reorganization Audit

## Bounded Question

This audit classifies the current `docs/` tree so the active roadway_graph / Step 5 graph-first workflow can be separated from older signal-centered, directed-segment, directionality, upstream/downstream, and context-enrichment documentation.

No code, generated outputs, or existing documentation files were modified. No files were moved or deleted.

## Folder Contract

The proposed active documentation contract is:

| Folder | Purpose | Status | Should contain | Should not contain |
| --- | --- | --- | --- | --- |
| `docs/design/` | Design notes, proposed schemas, planning sketches, architecture proposals, candidate workflows, and future implementation plans. | May be provisional or speculative. | Design memos, proposed table contracts, planned diagram descriptions, recovery strategies, alternate methodology proposals. | Current run commands, final methodology, polished reports, generated result summaries better stored in `results`. |
| `docs/methodology/` | Stable high-level methodological documents explaining what the active method is and why it is defensible. | Current or deliberately retained methodological reference. | Overview methodology, graph-first methodology, signal/roadway/crash assignment principles, interpretation boundaries. | One-off run logs, temporary QA notes, legacy method docs unless clearly labeled as historical reference. |
| `docs/diagrams/` | Diagram source files and rendered diagrams/figures explaining workflows, data relationships, spatial concepts, or package structure. | Visual assets only. | Mermaid/Graphviz/source diagrams, exported PNG/SVG/PDF diagrams, figure notes tightly tied to a diagram. | Long methodology prose, run logs, output summaries. |
| `docs/reports/` | Polished, forward-facing documents or report-ready markdown/PDF sources that have been manually reviewed or are intended for sharing. | Shareable or near-shareable. | Reviewed findings memos, proposal-facing reports, rendered-report source markdown, final narrative reports. | Active scratch notes, unreviewed workflow memos, raw audit logs. |
| `docs/results/` | Curated narrative summaries of important audit, QA, and experiment findings. | Summarized results, not raw generated outputs. | Concise findings summaries for eligibility gating, Step 5 readiness, divided pairing, roadway role classification, crash assignment QA, and similar major outputs. | Every generated CSV; raw tables stay under `work/output/.../review/current/`. |
| `docs/workflow/` | Active working documentation explaining what is run now, output contracts, commands, QA procedures, and current module status. | Operational truth for current work. | Active workflow, module run instructions, current output contracts, current QA/readout docs, implementation notes. | Legacy method docs unless temporarily retained with a status banner, polished reports, long-term stable methodology better suited for `methodology`. |

## Current Roadway Graph Methodology Docs

The docs that directly describe the current roadway_graph / Step 5 graph-first method are:

- `docs/methodology/roadway_graph_methodology.md`
- `docs/workflow/roadway_graph_workflow.md`
- `docs/workflow/roadway_graph_step5_eligibility_gating.md`
- `docs/workflow/roadway_graph_step5_eligibility_audit.md`
- `docs/workflow/roadway_graph_edge_termination_refinement.md`
- `docs/workflow/roadway_graph_step5_oriented_segment_prototype.md`
- `docs/workflow/roadway_graph_step5_oriented_segment_qa.md`
- `docs/workflow/roadway_graph_step5_readiness_revision.md`
- `docs/workflow/roadway_graph_step5_crash_ready_subset.md`
- `docs/workflow/roadway_graph_step5_crash_ready_summary_qa.md`
- `docs/workflow/roadway_graph_crash_assignment_prototype.md`
- `docs/workflow/roadway_graph_geometric_direction_model.md`
- `docs/workflow/roadway_graph_divided_carriageway_pairing.md`
- `docs/workflow/roadway_graph_divided_pairing_unresolved_diagnosis.md`
- `docs/workflow/roadway_graph_divided_undivided_directional_framework_audit.md`
- `docs/workflow/roadway_graph_roadway_role_classification.md`
- `docs/workflow/roadway_graph_qgis_review_layers.md`
- `docs/workflow/roadway_graph_initial_qa_readout.md`
- `docs/workflow/roadway_graph_foundation_audit.md`
- `docs/workflow/roadway_graph_manual_review_diagnosis.md`

These should remain in `docs/`. The stable graph-first overview belongs in `docs/methodology/`; run commands and output contracts belong in `docs/workflow/`; curated QA/readout summaries can be moved or copied into `docs/results/` after Stage A banners and indexes make their status clear.

## Older Signal-Centered Work

The older signal-centered or pre-graph packages are documented by:

- `docs/methodology/overview_methodology.md`
- `docs/methodology/directed_segment_methodology.md`
- `docs/methodology/flow_method_comparison.md`
- `docs/results/directionality_experiment_results.md`
- `docs/design/flow_decision_diagram_outline.md`
- `docs/design/upstream_downstream_decision_flow.md`
- `docs/design/upstream_downstream_diagram_outline.md`
- `docs/diagrams/directionality_decision_diagram.*`
- `docs/diagrams/upstream_downstream_decision_diagram.*`
- `docs/workflow/directed_segment_workflow.md`
- `docs/workflow/directed_signal_leg_initial_qa_readout.md`
- `docs/workflow/directed_signal_leg_qgis_review_layers.md`
- `docs/workflow/proposal_facing_descriptive_analysis_package_001.md`
- `docs/workflow/proposal_facing_descriptive_analysis_package_002.md`
- `docs/workflow/proposal_facing_descriptive_findings_package_003.md`
- `docs/workflow/package_003_signal_outlier_map_review_batch_A_guide.md`
- `docs/workflow/enrichment_plan.md`
- `docs/workflow/context_enrichment_*.md`
- `docs/workflow/access_route_conflict_*.md`

These should not be deleted. They should be retained as supporting reference, historical method evidence, or legacy package documentation depending on whether the current roadway_graph workflow still uses the concept.

## Still Useful But Historical

The most useful historical material is:

- Directed-segment methodology and workflow docs, because they preserve the divided-road vertical-slice design that roadway_graph superseded for graph foundation purposes.
- Directionality experiment results and decision diagrams, because they document why crash-direction inference should not govern the current graph-first scaffold.
- Context enrichment and proposal descriptive package docs, because they preserve access/AADT/distance-band ideas that may be reused after the graph scaffold is clean.
- Early data-processing diagram assets and staging contracts, because they explain staging/normalization context and repository recovery decisions.

These should receive short status banners in Stage A before any relocation.

## Move To `legacy/docs/`

Recommended clear legacy or historical moves after Stage A:

- `docs/methodology/directed_segment_methodology.md`
- `docs/methodology/flow_method_comparison.md`
- `docs/results/directionality_experiment_results.md`
- `docs/workflow/directed_segment_workflow.md`
- `docs/workflow/directed_signal_leg_initial_qa_readout.md`
- `docs/workflow/directed_signal_leg_qgis_review_layers.md`
- `docs/design/flow_decision_diagram_outline.md`
- `docs/design/upstream_downstream_decision_flow.md`
- `docs/design/upstream_downstream_diagram_outline.md`
- `docs/diagrams/directionality_decision_diagram.*`
- `docs/diagrams/upstream_downstream_decision_diagram.*`
- `docs/workflow/package_003_signal_outlier_map_review_batch_A_guide.md`
- older `proposal_facing_descriptive_*` package docs unless promoted into `docs/reports/`

Context enrichment docs are less clear: move them only after deciding whether they remain near-term support for graph-ready crash/access work.

## Remain Under `docs/workflow/`

Keep active operational roadway_graph docs in `docs/workflow/`:

- `active_workflow.md`, after pointer updates in Stage C
- `roadway_graph_workflow.md`
- roadway_graph module run docs and output contracts
- roadway_graph QA and review docs while they remain active working readouts
- `staging_and_normalization_contract.md`
- `windows_file_lock_manual_cleanup_guide.md`
- `github_publishing_guide.md`
- the new workflow index and audit files from this task

## Move To `docs/methodology/`

Keep or move stable methodology documents here:

- `roadway_graph_methodology.md`
- `proposal_alignment_growth_plan.md`
- a future rewritten graph-first `overview_methodology.md`
- any future stable roadway/signal/crash assignment principle document

The current `overview_methodology.md` is mixed: it already mentions the graph pivot, but its title and several sections still reflect directed-segment and signal-centered framing. It should be revised in Stage D, not moved.

## Move To `docs/results/`

Candidates for `docs/results/` are curated QA/readout summaries, especially:

- `roadway_graph_initial_qa_readout.md`
- `roadway_graph_foundation_audit.md`
- `roadway_graph_step5_eligibility_audit.md`
- `roadway_graph_step5_oriented_segment_qa.md`
- `roadway_graph_step5_readiness_revision.md`
- `roadway_graph_step5_crash_ready_summary_qa.md`
- `roadway_graph_divided_pairing_unresolved_diagnosis.md`
- `roadway_graph_divided_undivided_directional_framework_audit.md`

Do not move raw generated outputs into `docs/results/`.

## Candidates For `docs/reports/`

The current report candidates are:

- `docs/reports/current_work_package_memo_2026_05_06.md`
- `docs/reports/current_work_package_memo_2026_05_06.pdf`
- possibly `docs/workflow/proposal_facing_descriptive_findings_package_003.md`, if manually reviewed and reframed as a report rather than an operational package memo

`docs/reports/style_examples/` is a style/reference asset, not a current report.

## Belong In `docs/design/`

Current and future design/planning docs belong here:

- graph-first recovery plans
- proposed table contracts
- alternate methodology proposals
- future implementation plans
- planning sketches that are not operational commands

Existing signal-centered diagram outlines already fit `docs/design/`, but should be marked historical or moved to `legacy/docs/design/` after Stage A.

## Belong In `docs/diagrams/`

Diagram source and rendered assets belong here only when they remain current visual assets. The current diagram files are visual assets, but most are historical signal-centered or directionality assets:

- `directionality_decision_diagram.*`: historical directionality prototype
- `upstream_downstream_decision_diagram.*`: historical upstream/downstream prototype
- `early_data_processing_decision_diagram.*`: supporting reference unless current staging docs still use it

Future graph-first diagrams should be added here with names that start with `roadway_graph_` or `step5_`.

## Link Update Needs

Files with links or named references that must be updated if relocation happens include:

- `README.md`
- `AGENTS.md`
- `docs/README.md`
- `docs/methodology/overview_methodology.md`
- `docs/methodology/proposal_alignment_growth_plan.md`
- `docs/workflow/active_workflow.md`
- `docs/workflow/roadway_graph_workflow.md`
- `docs/workflow/staging_and_normalization_contract.md`
- `docs/workflow/enrichment_plan.md`
- context enrichment docs that cross-reference each other
- proposal package docs that cross-reference Package 001/002/003

Detailed planned edits are listed in `docs/workflow/documentation_link_update_plan.csv`.

## Referenced By README, AGENTS, Active Workflow, Or Overview

High-level references currently found:

- `README.md` points to `docs/README.md`, `overview_methodology.md`, `proposal_alignment_growth_plan.md`, `active_workflow.md`, and `enrichment_plan.md`, and still lists directionality/upstream-downstream outputs as restored areas.
- `AGENTS.md` still names signal-centered methodology and active direct-entry modules; it should be updated after Stage A to name roadway_graph as the current active methodology.
- `docs/workflow/active_workflow.md` contains the most complete mixed operational map, including current roadway_graph modules and older direct-entry modules.
- `docs/methodology/overview_methodology.md` mentions the graph pivot but remains titled and structured around directed-segment methodology.

## Work/Output Family Documentation Coverage

| Work/output family | Matching docs | Status |
| --- | --- | --- |
| `roadway_graph` | Strong coverage in methodology, workflow, QA, Step 5, crash assignment, geometric direction, divided pairing, and roadway role docs. | Current active. |
| `directed_segments` | `directed_segment_methodology.md`, `directed_segment_workflow.md`, QA/readout docs. | Superseded by roadway_graph for graph foundation; historical prototype. |
| `directionality_experiment` | `directionality_experiment_results.md`, flow comparison, decision diagram docs/assets. | Historical/superseded for current graph-first direction interpretation. |
| `upstream_downstream_prototype` | Design flow docs, active_workflow sections, context integration memo. | Legacy signal-centered prototype. |
| `context_enrichment` | Strong workflow memo coverage and `enrichment_plan.md`. | Supporting reference; not current graph-first scaffold. |
| `context_enrichment_access_same_corridor_prototype` | Same-corridor checklist/completion/recommendation docs and seed CSV. | Supporting or historical validation prototype. |
| `proposal_descriptive` | Package 001/002/003 docs and distance-band/table contracts. | Historical/proposal-facing reference unless promoted into reports. |
| `stage1b_study_slice` | `staging_and_normalization_contract.md`, active_workflow standard slice. | Current support/staging. |

Clear documentation gaps:

- A concise current graph-first methodology index was missing before this task.
- A current workflow index separating graph-first from historical modules was missing.
- A current results index for roadway_graph QA/readout summaries was missing.
- A design index distinguishing speculative plans from active workflow was missing.
- A diagrams index distinguishing historical figures from future graph-first diagrams was missing.
- No graph-first diagram asset is present yet.

## Recommended Staged Relocation Plan

### Stage A: Add indexes and status banners

Use the indexes created in this task as navigation anchors. Add short status banners to existing docs that are superseded, historical, supporting reference, or current graph-first. Do not rewrite methodology content beyond those notes.

### Stage B: Move clearly legacy docs to `legacy/docs/`

Move historical signal-centered, directed-segment, directionality, and upstream/downstream prototype docs only after banners and link impacts are reviewed. Preserve directory shape under `legacy/docs/` where useful, such as `legacy/docs/workflow/` and `legacy/docs/diagrams/`.

### Stage C: Update links and README/AGENTS/active_workflow pointers

Update `README.md`, `AGENTS.md`, `docs/README.md`, `docs/workflow/active_workflow.md`, and major cross-links so the current active method points first to roadway_graph and Step 5 graph-first docs.

### Stage D: Optionally consolidate current methodology docs

Rewrite or replace the mixed `overview_methodology.md` with a stable graph-first overview. Keep `roadway_graph_methodology.md` as the detailed foundation method, and keep proposal alignment as the growth-plan companion.
