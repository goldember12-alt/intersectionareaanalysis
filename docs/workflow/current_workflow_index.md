# Current Workflow Index

**Status: CURRENT ACTIVE.** This is the short navigation page for the roadway-derived directional context product.

## Start Here

- `active_workflow.md`: current command surface and output contract.
- `roadway_graph_workflow.md`: roadway graph foundation workflow and graph-first methodological guardrails.
- `roadway_graph_directional_context_milestone.md`: current milestone for the full 0-2,500 ft directional-bin context universe.
- `../design/roadway_graph_context_enrichment_plan.md`: design record for access, speed, AADT, and context enrichment.
- `../methodology/roadway_graph_methodology.md`: core graph-first methodology.
- `../methodology/overview_methodology.md`: repository-level methodology posture.
- `../methodology/proposal_alignment_growth_plan.md`: controlled proposal-alignment growth path.

## Current Product

The current product is the stable roadway-derived 0-2,500 ft directional-bin context universe:

- 0-1,000 ft: high-priority descriptive subset.
- 1,000-2,500 ft: sensitivity subset.
- greater than 2,500 ft: review-only, excluded from the combined table.

Final product outputs live under:

`work/output/roadway_graph/analysis/current/directional_bin_context_table/`

The combined table joins accepted context layers onto one row per usable directional bin. It includes crash assignment/readiness counts, assigned-crash `AREA_TYPE` context, access context, speed v4 context, AADT v3 context, and explicit roadway urban/rural `source_not_found` fields.

## Active Output Folders

Keep these `current` output folders as the active product and reproducibility/audit surface:

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

Supporting source/staging inventories that remain useful for provenance:

- `work/output/roadway_graph/review/current/context_source_inventory/`
- `work/output/roadway_graph/review/current/posted_speed_source_staging/`
- `work/output/roadway_graph/review/current/aadt_source_staging/`

## Archived Material

Superseded docs and one-off audits from the cleanup pass were moved to:

- `docs/archive/20260519_cleanup/`
- `work/archive/20260519_cleanup/`
- `work/output/roadway_graph/review/history/repo_cleanup_20260519/`

Treat archived material as history or comparison evidence only. Do not use archived docs or outputs as current methodology unless a later task explicitly promotes a specific item back into the active workflow.

## Methodological Boundaries

- Crash direction fields are not used.
- Context fields do not redefine upstream/downstream.
- Crash `AREA_TYPE` is crash-level context only.
- Roadway-level urban/rural remains unavailable with `roadway_urban_rural_context_status = source_not_found`.
- Ambiguous and unresolved crashes remain outside the assigned-crash summary universe.
- The table is a prototype descriptive analysis universe, not policy-ready or modeling-ready.
