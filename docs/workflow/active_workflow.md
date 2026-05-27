# Current Workflow and Output Contracts

**Status: CURRENT ACTIVE.** This file describes the active roadway-derived directional context product after the May 19, 2026 cleanup pass.

## Bounded Product

The current bounded product is a graph-first roadway-derived directional-bin context universe for signalized intersections.

The active method remains:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> roadway-derived directional scaffold -> roadway-only directional catchments -> conservative crash assignment -> readiness-gated assigned-crash universe -> access, speed, AADT, and crash-level urban/rural context enrichment.

The product is descriptive and prototype-ready. It is not policy-ready or modeling-ready.

## Final Product Output

Final active v2/v5 context table:

`work/output/roadway_graph/analysis/current/directional_bin_context_table_active/directional_bin_context_active.csv`

Preserved v1/v4 baseline context table:

`work/output/roadway_graph/analysis/current/directional_bin_context_table/directional_bin_context.csv`

Companion outputs in the same folder include:

- `directional_bin_context_0_1000ft.csv`
- `directional_bin_context_1000_2500ft.csv`
- `directional_crash_context.csv`
- `reference_signal_context_summary.csv`
- `crash_area_type_context_summary.csv`
- `crash_area_type_by_distance_window.csv`
- `crash_area_type_by_signal_relative_direction.csv`
- `crash_area_type_by_roadway_representation.csv`
- `combined_context_join_qa.csv`
- `directional_bin_context_findings.md`
- `directional_bin_context_manifest.json`

Current active v2/v5 product counts:

- total bins: 110,710
- 0-1,000 ft bins: 66,074
- 1,000-2,500 ft bins: 44,636
- bins with assigned crashes: 8,552
- represented assigned crashes: 13,216
- bins with access context: 110,710
- bins with stable speed context: 105,835
- bins with stable AADT context: 106,210
- assigned crashes with crash-level urban/rural classification: 13,216
- roadway-level urban/rural context: unavailable, `source_not_found`

Speed v5 is now the active speed context. AADT denominator v2 is now the active exposure policy for refreshed rate and modeling-readiness outputs. The older v1/v4 context, rate, suppression, and model-readiness folders are retained as baseline/legacy comparison.

## Active Direct-Entry Commands

Use the repository bootstrap-reported Python interpreter, normally `.\.venv\Scripts\python.exe` in this working copy.

The current direct-entry roadway_graph sequence is:

```powershell
.\.venv\Scripts\python.exe -m src.active.roadway_graph
.\.venv\Scripts\python.exe -m src.active.roadway_graph.geometric_direction
.\.venv\Scripts\python.exe -m src.active.roadway_graph.divided_carriageway_pairing
.\.venv\Scripts\python.exe -m src.active.roadway_graph.roadway_role_classification
.\.venv\Scripts\python.exe -m src.active.roadway_graph.reference_signal_directional_scaffold
.\.venv\Scripts\python.exe -m src.active.roadway_graph.reference_signal_directional_scaffold_qa
.\.venv\Scripts\python.exe -m src.active.roadway_graph.reference_signal_directional_bin_catchments
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_directional_catchment_assignment_prototype
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_directional_catchment_assignment_qa
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_directional_assignment_analysis_readiness
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_directional_assignment_descriptive_summary
.\.venv\Scripts\python.exe -m src.active.roadway_graph.context_source_inventory
.\.venv\Scripts\python.exe -m src.active.roadway_graph.access_context_join
.\.venv\Scripts\python.exe -m src.active.roadway_graph.stage_posted_speed_source
.\.venv\Scripts\python.exe -m src.active.roadway_graph.stage_aadt_source
.\.venv\Scripts\python.exe -m src.active.roadway_graph.roadway_identity_metadata_propagation
.\.venv\Scripts\python.exe -m src.active.roadway_graph.speed_context_join_v4_identity_enriched
.\.venv\Scripts\python.exe -m src.active.roadway_graph.aadt_context_join_v3_identity_route_measure
.\.venv\Scripts\python.exe -m src.active.roadway_graph.urban_rural_source_recovery
.\.venv\Scripts\python.exe -m src.active.roadway_graph.directional_bin_context_table
.\.venv\Scripts\python.exe -m src.active.roadway_graph.directional_context_descriptive_summaries
.\.venv\Scripts\python.exe -m src.active.roadway_graph.signal_context_review_queue
.\.venv\Scripts\python.exe -m src.active.roadway_graph.directional_context_distance_band_profiles
.\.venv\Scripts\python.exe -m src.active.roadway_graph.signal_direction_context_profiles
.\.venv\Scripts\python.exe -m src.active.roadway_graph.stakeholder_context_table_package
.\.venv\Scripts\python.exe -m src.active.roadway_graph.aadt_direction_factor_audit
.\.venv\Scripts\python.exe -m src.active.roadway_graph.descriptive_crash_rate_direction_factor_sensitivity
.\.venv\Scripts\python.exe -m src.active.roadway_graph.active_rate_denominator_policy_update
.\.venv\Scripts\python.exe -m src.active.roadway_graph.access_type_inventory
.\.venv\Scripts\python.exe -m src.active.roadway_graph.normalized_source_attribute_audit
.\.venv\Scripts\python.exe -m src.active.roadway_graph.new_speed_route_source_inventory
.\.venv\Scripts\python.exe -m src.active.roadway_graph.speed_context_join_v5_new_source_supplement
.\.venv\Scripts\python.exe -m src.active.roadway_graph.active_speed_context_policy_update
.\.venv\Scripts\python.exe -m src.active.roadway_graph.directional_bin_context_table_active_refresh
.\.venv\Scripts\python.exe -m src.active.roadway_graph.roadway_graph_report_figures_active_refresh
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_simplified_internal_model_active
.\.venv\Scripts\python.exe -m src.active.roadway_graph.crash_count_negative_binomial_stabilization_active
.\.venv\Scripts\python.exe -m src.active.roadway_graph.internal_modeling_conclusion_readiness_active
```

The final eighteen commands are read-only against the accepted combined context table, descriptive summary outputs, current rate-prototype outputs, existing access join review outputs, source/normalized attribute schemas, new candidate source layers, existing speed v4/v5 review outputs, active policy records, and active v2/v5 downstream outputs. They create descriptive summary tables, manual review-prioritization queues, fixed distance-band profiles, signal-direction profiles, compact stakeholder table-package outputs, an AADT `DIRECTION_FACTOR` denominator audit, a direction-factor exposure sensitivity for the approved window-grain descriptive rate prototype, an active denominator policy promotion record, an access type inventory/feasibility review, a source-vs-normalized attribute preservation audit, a new speed/route source inventory, a speed v5 new-source supplement comparison, an active speed context policy promotion record, the active v2/v5 downstream refresh package, active v2/v5 report figures, the active v2/v5 simplified internal model rerun, the active v2/v5 negative-binomial stabilization diagnostic, and the active internal modeling conclusion support package. Do not rerun the upstream sequence casually. It is listed so the product lineage is understandable.

## Active Current Output Folders

Preserve these as current:

- `work/output/roadway_graph/analysis/current/directional_bin_context_table/`
- `work/output/roadway_graph/analysis/current/directional_bin_context_table_active/`
- `work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries/`
- `work/output/roadway_graph/analysis/current/directional_context_descriptive_summaries_active/`
- `work/output/roadway_graph/analysis/current/signal_context_review_queue/`
- `work/output/roadway_graph/analysis/current/directional_context_distance_band_profiles/`
- `work/output/roadway_graph/analysis/current/signal_direction_context_profiles/`
- `work/output/roadway_graph/analysis/current/stakeholder_context_table_package/`
- `work/output/roadway_graph/analysis/current/aadt_direction_factor_audit/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_direction_factor_sensitivity/`
- `work/output/roadway_graph/analysis/current/active_rate_denominator_policy/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_prototype_active/`
- `work/output/roadway_graph/analysis/current/descriptive_crash_rate_suppression_review_active/`
- `work/output/roadway_graph/analysis/current/crash_count_modeling_readiness_dataset_active/`
- `work/output/roadway_graph/analysis/current/active_refresh_impact_summary/`
- `work/output/roadway_graph/report/current_active/`
- `work/output/roadway_graph/analysis/current/crash_count_simplified_internal_model_active/`
- `work/output/roadway_graph/analysis/current/crash_count_negative_binomial_stabilization_active/`
- `work/output/roadway_graph/analysis/current/internal_modeling_conclusion_readiness_active/`
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
- `work/output/roadway_graph/review/current/access_type_inventory/`
- `work/output/roadway_graph/review/current/normalized_source_attribute_audit/`
- `work/output/roadway_graph/review/current/new_speed_route_source_inventory/`
- `work/output/roadway_graph/review/current/speed_context_join_v5_new_source_supplement/`
- `work/output/roadway_graph/review/current/active_speed_context_policy/`

Supporting provenance folders:

- `work/output/roadway_graph/review/current/context_source_inventory/`
- `work/output/roadway_graph/review/current/posted_speed_source_staging/`
- `work/output/roadway_graph/review/current/aadt_source_staging/`

## Archived Output Folders

Archived or superseded output roots:

- `work/archive/20260519_cleanup/`
- `work/output/roadway_graph/review/history/repo_cleanup_20260519/`

These preserve older signal-centered outputs, directed-segment outputs, smoke runs, superseded speed/AADT attempts, one-off audits, and loose root review files. Treat them as historical evidence only.

## Methodological Boundaries

- Do not modify scaffold construction during context-table work.
- Do not modify catchments during context-table work.
- Do not modify crash assignment during context-table work.
- Do not modify access, speed, or AADT joins during context-table work.
- Do not use crash direction fields.
- Do not use context fields to redefine upstream/downstream.
- Apply `DIRECTION_FACTOR` only in the approved active denominator v2 context. Null factors use the documented bidirectional fallback, invalid factors are flagged, and older v1 outputs remain baseline/legacy until refreshed.
- Treat speed v5 new-source supplement as the active speed context for future refreshes. Do not overwrite speed v4 outputs; retain them as baseline/legacy comparison.
- Do not use crash `AREA_TYPE` as roadway-level urban/rural truth.
- Do not populate no-crash bins from crash `AREA_TYPE`.
- Preserve `>2,500 ft` rows as review-only unless a later bounded task changes the analysis universe.

## Standard Package CLI Slice

The older standard package CLI slice still exists for staging and normalization support:

```powershell
.\.venv\Scripts\python.exe -m src stage-inputs
.\.venv\Scripts\python.exe -m src normalize-stage
.\.venv\Scripts\python.exe -m src build-study-slice
.\.venv\Scripts\python.exe -m src enrich-study-signals-nearest-road
.\.venv\Scripts\python.exe -m src check-parity
```

This slice is not the final directional-context product pipeline.

## Next Phase

Recommended next phase:

- review the fixed distance-band profiles
- review the signal-direction profile tables
- review the compact stakeholder table package
- review the AADT direction-factor audit and the direction-factor exposure sensitivity before deciding whether a later denominator policy should use `DIRECTION_FACTOR`, source directional AADT rows, or continue with bidirectional AADT
- decide whether to harden the prototype into a production pipeline
- define modeling-readiness requirements before any regression or policy claim
