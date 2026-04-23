# Stage 1 Portability Bootstrap

This repository now includes a repo-local bootstrap path for Stage 1 portability work.

## Command

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m stage1_portable
.\.venv\Scripts\python.exe -m stage1_portable stage-inputs
.\.venv\Scripts\python.exe -m stage1_portable normalize-stage
.\.venv\Scripts\python.exe -m stage1_portable build-study-slice
.\.venv\Scripts\python.exe -m stage1_portable enrich-study-signals-nearest-road
.\.venv\Scripts\python.exe -m stage1_portable enrich-study-signals-speed-context
.\.venv\Scripts\python.exe -m stage1_portable derive-study-signals-functional-distance
.\.venv\Scripts\python.exe -m stage1_portable build-study-signals-buffers
.\.venv\Scripts\python.exe -m stage1_portable build-study-signals-functional-donut
.\.venv\Scripts\python.exe -m stage1_portable build-study-signals-multizone
.\.venv\Scripts\python.exe -m stage1_portable build-road-zone-intersection-raw
.\.venv\Scripts\python.exe -m stage1_portable inspect-aadt-traffic-volume-bridge
.\.venv\Scripts\python.exe -m stage1_portable inspect-aadt-traffic-volume-geojson-bridge
.\.venv\Scripts\python.exe -m stage1_portable validate-event-source-id-linkid-bridge
.\.venv\Scripts\python.exe -m stage1_portable audit-event-source-id-linkid-unmatched
.\.venv\Scripts\python.exe -m stage1_portable build-event-source-id-linkid-bridge-boundary
.\.venv\Scripts\python.exe -m stage1_portable validate-bridge-boundary-to-normalized-roads
.\.venv\Scripts\python.exe -m stage1_portable validate-normalized-roads-to-study-roads-bridge
.\.venv\Scripts\python.exe -m stage1_portable build-study-eligibility-bridge-split
.\.venv\Scripts\python.exe -m stage1_portable diagnose-study-scoped-oracle-runtime
.\.venv\Scripts\python.exe -m stage1_portable run-study-scoped-oracle-lookup
.\.venv\Scripts\python.exe -m stage1_portable disambiguate-study-scoped-oracle-returns
.\.venv\Scripts\python.exe -m stage1_portable refine-study-scoped-oracle-evidence
.\.venv\Scripts\python.exe -m stage1_portable define-study-scoped-oracle-segment-ready-handoff
.\.venv\Scripts\python.exe -m stage1_portable audit-study-scoped-oracle-segment-matching-contract
.\.venv\Scripts\python.exe -m stage1_portable build-segment-lineage-support
.\.venv\Scripts\python.exe -m stage1_portable reaudit-study-scoped-oracle-segment-matching-contract
.\.venv\Scripts\python.exe -m stage1_portable audit-study-scoped-oracle-segment-candidate-narrowing
.\.venv\Scripts\python.exe -m stage1_portable audit-study-scoped-oracle-segment-edge-cases
.\.venv\Scripts\python.exe -m stage1_portable design-study-scoped-oracle-true-match-experiment
.\.venv\Scripts\python.exe -m stage1_portable execute-study-scoped-oracle-true-match-experiment
.\.venv\Scripts\python.exe -m stage1_portable audit-study-scoped-oracle-true-match-boundary-sensitivity
.\.venv\Scripts\python.exe -m stage1_portable trace-stage1b-linkid-lineage
.\.venv\Scripts\python.exe -m stage1_portable restore-study-roads-parent-linkid
.\.venv\Scripts\python.exe -m stage1_portable restore-study-roads-parent-linkid-normalized-routekey
.\\.venv\\Scripts\\python.exe -m stage1_portable inherit-stage1b-segment-link-identity
.\.venv\Scripts\python.exe -m stage1_portable reaudit-stage1b-segment-oracle-matching-contract
.\.venv\Scripts\python.exe -m stage1_portable execute-stage1b-segment-oracle-true-match-ready-subset
.\.venv\Scripts\python.exe -m stage1_portable audit-stage1b-segment-oracle-true-match-ready-subset-stability
.\.venv\Scripts\python.exe -m stage1_portable define-stage1b-segment-oracle-downstream-safe-subset
.\.venv\Scripts\python.exe -m stage1_portable define-stage1b-segment-oracle-downstream-safe-consumer-handoff
.\.venv\Scripts\python.exe -m stage1_portable build-stage1b-segment-oracle-downstream-safe-consumer-staging
.\.venv\Scripts\python.exe -m stage1_portable build-stage1b-segment-oracle-downstream-safe-analytical-context
.\.venv\Scripts\python.exe -m stage1_portable build-stage1b-segment-oracle-downstream-safe-review
.\.venv\Scripts\python.exe -m stage1_portable build-stage1b-segment-oracle-downstream-safe-triage
.\.venv\Scripts\python.exe -m stage1_portable build-stage1b-segment-oracle-downstream-safe-decision-support
.\.venv\Scripts\python.exe -m stage1_portable build-stage1b-oracle-safe-subset-closure-handoff
.\.venv\Scripts\python.exe -m stage1_portable build-stage1c-nondirectional-consumer-slice
.\.venv\Scripts\python.exe -m stage1_portable build-stage1c-nondirectional-consumer-output
.\.venv\Scripts\python.exe -m stage1_portable build-stage1c-nondirectional-minislice
.\.venv\Scripts\python.exe -m stage1_portable audit-stage1c-capability-gap
.\.venv\Scripts\python.exe -m stage1_portable define-stage1c-crash-access-readiness-contract
.\.venv\Scripts\python.exe -m stage1_portable define-stage1c-crash-access-staging-contract
.\.venv\Scripts\python.exe -m stage1_portable audit-stage1c-crash-access-join
.\.venv\Scripts\python.exe -m stage1_portable build-stage1c-nondirectional-completed-slice
.\.venv\Scripts\python.exe -m stage1_portable audit-study-roads-link-restoration-reconciliation
.\.venv\Scripts\python.exe -m stage1_portable validate-aadt-traffic-volume-linkid-join
```

## What it does

- resolves the repository root without ArcGIS Pro
- loads portable runtime settings from `config/stage1_portable.toml`
- reports the active legacy source path and legacy entrypoints
- checks whether the Stage 1 open-source dependencies are installed
- validates the configured raw input geodatabase paths
- attempts layer-name validation with `pyogrio` or `fiona` when available
- can stage the six configured raw input layers into `artifacts/staging/*.parquet`
- writes a staging manifest to `artifacts/staging/stage1_input_manifest.json`
- assembles a portable canonical `signals` input that reproduces the legacy `Master_Signal_Layer` intent by merging configured raw signal sources when present
- can build a separate analysis-ready normalized tier in `artifacts/normalized/*.parquet`
- writes a normalization manifest to `artifacts/normalized/stage1_normalized_manifest.json`
- can build the first bounded Stage 1B runtime slice for `Study_Roads_Divided` and `Study_Signals` from normalized inputs
- writes Stage 1B slice outputs to `artifacts/output/stage1b_study_slice/*.parquet`
- writes a bounded Stage 1B QC/parity summary to `artifacts/parity/stage1b_study_slice_qc.json`
- can enrich `Study_Signals` with nearest `Study_Roads_Divided` context as the next bounded Stage 1B step
- writes nearest-road enrichment QC to `artifacts/parity/stage1b_signal_nearest_road_qc.json`
- can enrich `Study_Signals_NearestRoad` with posted-speed context from the normalized speed layer as the next bounded Stage 1B step
- writes posted-speed enrichment QC to `artifacts/parity/stage1b_signal_speed_context_qc.json`
- can derive signal-level `Dist_Lim` and `Dist_Des` from `Assigned_Speed` as the next bounded Stage 1B step
- writes functional-distance derivation QC to `artifacts/parity/stage1b_signal_functional_distance_qc.json`
- can create the first raw signal-centered buffer products from `Dist_Lim` and `Dist_Des` without dissolve or road interaction logic
- writes raw buffer QC to `artifacts/parity/stage1b_signal_buffer_qc.json`
- can derive the per-signal functional donut geometry from the two raw buffer outputs without dissolve or road interaction logic
- writes donut geometry QC to `artifacts/parity/stage1b_signal_donut_qc.json`
- can combine Zone 1 and Zone 2 outputs into a single staged multi-zone geometry layer for later road interaction
- writes staged multi-zone QC to `artifacts/parity/stage1b_signal_multizone_qc.json`
- can intersect study roads with the staged multi-zone layer to create the first raw road-zone geometry output
- writes raw road-zone QC to `artifacts/parity/stage1b_road_zone_intersection_qc.json`
- can inspect the newly added traffic-volume layer against the configured `New_AADT` source for Oracle bridge-key readiness without changing pipeline logic
- writes the traffic-volume versus AADT bridge-key comparison summary to `artifacts/parity/stage1_aadt_traffic_volume_bridge_qc.json`
- can inspect the GeoJSON form of the same traffic-volume dataset against the shapefile export and configured `New_AADT` source to test whether GeoJSON preserves a missing direct bridge key
- writes the GeoJSON traffic-volume bridge-key preservation summary to `artifacts/parity/stage1_aadt_traffic_volume_geojson_bridge_qc.json`
- can validate whether traffic-volume `EVENT_SOURCE_ID` should be treated as the direct GIS-side bridge key by comparing it directly to AADT `LINKID`
- writes the direct `EVENT_SOURCE_ID` versus `LINKID` bridge-key summary to `artifacts/parity/stage1_event_source_id_linkid_bridge_qc.json`
- can audit the remaining direct-key-unmatched traffic-volume rows and test only targeted fallback recovery on that bounded exception set
- writes the unmatched direct-key exception summary to `artifacts/parity/stage1_event_source_id_linkid_unmatched_qc.json`
- can build the intended merged/base-layer bridge-bearing boundary by carrying recoverable EVENT_SOURCE_ID/LINKID matches forward onto the preferred traffic-volume surface and splitting unresolved rows into an explicit exception output
- writes the bridge-bearing base-layer output to `artifacts/output/stage1_bridge_boundary/Traffic_Volume_AADT_BridgeBoundary.parquet`
- writes the unresolved bridge-key exception layer to `artifacts/output/stage1_bridge_boundary/Traffic_Volume_AADT_BridgeBoundary_Exceptions.parquet`
- writes the merged/base-layer bridge-boundary QC summary to `artifacts/parity/stage1_event_source_id_linkid_bridge_boundary_qc.json`
- can validate the next downstream road-lineage handoff from the bridge-bearing boundary into the earliest statewide portable roads boundary rather than forcing immediate propagation into later study-only road slices
- writes the road-lineage validation output to `artifacts/output/stage1_bridge_boundary/Normalized_Roads_BridgePropagationValidation.parquet`
- writes the bridge-ready rows that still fail clean road-lineage propagation to `artifacts/output/stage1_bridge_boundary/Traffic_Volume_AADT_BridgeBoundary_RoadPropagationExceptions.parquet`
- writes the downstream road-lineage propagation QC summary to `artifacts/parity/stage1_bridge_boundary_to_normalized_roads_qc.json`
- can validate the next study-slice handoff from the clean normalized-road bridge subset into `Study_Roads_Divided` without reverting to the raw bridge boundary as the primary source
- writes the study-road handoff validation output to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_BridgePropagationValidation.parquet`
- writes the clean normalized-road rows that stay outside the study-road handoff or otherwise fail it to `artifacts/output/stage1_bridge_boundary/Normalized_Roads_CleanBridge_StudyRoadExceptions.parquet`
- writes the normalized-roads-to-study-roads handoff QC summary to `artifacts/parity/stage1_normalized_roads_to_study_roads_bridge_qc.json`
- can build the narrower GIS-side study-eligibility split that formalizes the 1,268-row study-scoped Oracle-prep subset separately from the preserved statewide outside-study clean normalized-road branch
- writes the study-scoped bridge-bearing subset to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OraclePrepSubset.parquet`
- writes the preserved outside-study statewide branch to `artifacts/output/stage1_bridge_boundary/Normalized_Roads_CleanBridge_StatewideOutsideStudyBranch.parquet`
- writes the study-eligibility split QC summary to `artifacts/parity/stage1_study_eligibility_bridge_split_qc.json`
- can attempt the first live read-only Oracle lookup against the study-scoped subset only using the repo-local Python path and Oracle client/runtime settings
- can diagnose the exact repo-local Python runtime used by the study-scoped Oracle lookup command before another live Oracle retry
- writes the study-scoped Oracle runtime diagnostic to `artifacts/parity/stage1_study_scoped_oracle_runtime_diagnostic.json`
- writes the study-scoped Oracle join-status output to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleJoinValidation.parquet`
- writes live Oracle lookup rows to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleLookupRows.parquet` only when the Oracle connection and query succeed
- writes the live Oracle lookup/QC summary to `artifacts/parity/stage1_study_scoped_oracle_lookup_qc.json`
- can classify the study-scoped Oracle-return boundary into clean route-confirmed, ambiguous multi-route-return, mismatch-only, and no-match cases without propagating those Oracle results downstream
- writes the study-scoped Oracle disambiguation layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleDisambiguation.parquet`
- writes the study-scoped Oracle disambiguation QC summary to `artifacts/parity/stage1_study_scoped_oracle_disambiguation_qc.json`
- can refine the study-scoped non-clean Oracle rows into stronger support versus still-unresolved evidence buckets using Oracle node, sequence, milepoint, and offset patterns without propagating into segment lineage
- writes the study-scoped Oracle evidence-refinement layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleEvidenceRefinement.parquet`
- writes the study-scoped Oracle evidence-refinement QC summary to `artifacts/parity/stage1_study_scoped_oracle_evidence_refinement_qc.json`
- can define whether any refined-support study-scoped rows now have a stable enough Oracle-side signature for a later segment-ready handoff candidate without propagating anything into segment lineage
- writes the study-scoped Oracle segment-ready handoff-definition layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleSegmentReadyHandoff.parquet`
- writes the study-scoped Oracle segment-ready handoff QC summary to `artifacts/parity/stage1_study_scoped_oracle_segment_ready_handoff_qc.json`
- can audit whether the current portable segment Oracle-prep boundary truthfully contains comparable fields for the Oracle handoff-ready subset without performing any segment propagation
- writes the study-scoped Oracle-to-segment matching-contract layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleSegmentMatchingContract.parquet`
- writes the study-scoped Oracle-to-segment matching-contract QC summary to `artifacts/parity/stage1_study_scoped_oracle_segment_matching_contract_qc.json`
- can augment the current segment Oracle-prep boundary with only the minimum truthful support-only lineage fields needed for a later re-audit of the blocked Oracle handoff-ready subset
- writes the augmented segment-lineage support boundary to `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep_LineageSupport.parquet`
- writes the segment-lineage support QC summary to `artifacts/parity/stage1b_segment_lineage_support_qc.json`
- can re-audit the study-scoped Oracle-to-segment matching contract after the segment-lineage support augmentation to determine whether support-only measure-window evidence changes any previously blocked route-overlap outcomes without performing propagation
- writes the study-scoped Oracle-to-segment matching-contract re-audit layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleSegmentMatchingContract_Reaudit.parquet`
- writes the study-scoped Oracle-to-segment matching-contract re-audit QC summary to `artifacts/parity/stage1_study_scoped_oracle_segment_matching_contract_reaudit_qc.json`
- can audit whether the stronger measure-assisted study-scoped rows can be reduced from broad route-level GIS candidate sets to smaller plausible support-only candidate sets using route measure-window overlap without performing any propagation
- writes the study-scoped Oracle segment candidate-narrowing audit layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleSegmentCandidateNarrowing.parquet`
- writes the study-scoped Oracle segment candidate-narrowing QC summary to `artifacts/parity/stage1_study_scoped_oracle_segment_candidate_narrowing_qc.json`
- can audit the three single-remaining and five no-overlap edge cases from the candidate-narrowing layer to determine whether they look plausible, weak, support-sensitive, or conflict-driven for a later bounded experiment without performing any propagation
- writes the study-scoped Oracle segment edge-case audit layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleSegmentEdgeCaseAudit.parquet`
- writes the study-scoped Oracle segment edge-case audit QC summary to `artifacts/parity/stage1_study_scoped_oracle_segment_edge_case_audit_qc.json`
- can define the exact allowed evidence, acceptance criteria, rejection criteria, and unresolved-conflict criteria for a later tightly bounded Oracle-to-segment true-match experiment on the five informative edge-case rows without executing that experiment
- writes the study-scoped Oracle true-match experiment-design layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleTrueMatchExperimentDesign.parquet`
- writes the study-scoped Oracle true-match experiment-design QC summary to `artifacts/parity/stage1_study_scoped_oracle_true_match_experiment_design_qc.json`
- can execute the already-designed tightly bounded five-row Oracle-to-segment true-match experiment and record only provisional-accept, reject, or unresolved-conflict experiment outcomes without any broad propagation
- writes the study-scoped Oracle true-match experiment-results layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleTrueMatchExperimentResults.parquet`
- writes the study-scoped Oracle true-match experiment-results QC summary to `artifacts/parity/stage1_study_scoped_oracle_true_match_experiment_results_qc.json`
- can re-audit only the two unresolved experiment rows under explicit inclusive, strict, and narrowly tolerance-adjusted boundary-window interpretations to determine whether they are robust enough for any further micro-scope follow-up
- writes the study-scoped Oracle true-match boundary-sensitivity layer to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_CleanBridge_OracleTrueMatchBoundarySensitivity.parquet`
- writes the study-scoped Oracle true-match boundary-sensitivity QC summary to `artifacts/parity/stage1_study_scoped_oracle_true_match_boundary_sensitivity_qc.json`
- can trace where validated GIS-side LINKID support is still present, where it disappears across the later Stage 1B study-road and segment lineage chain, and which restoration strategy class is justified before any further Oracle-to-segment matching work
- writes the Stage 1B LINKID lineage trace layer to `artifacts/output/stage1_bridge_boundary/Stage1B_LINKID_LineageTrace.parquet`
- writes the Stage 1B LINKID lineage trace QC summary to `artifacts/parity/stage1b_linkid_lineage_trace_qc.json`
- can restore `AADT_LINKID` and `BridgeKey_EVENT_SOURCE_ID_Canonical` back onto `Study_Roads_Divided` by exact parent-lineage reattachment using `EVENT_SOUR + RTE_NM + FROM_MEASURE + TO_MEASURE`, without yet inheriting those fields into downstream segment outputs
- writes the restored study-road boundary to `artifacts/output/stage1b_study_slice/Study_Roads_Divided_LinkRestored.parquet`
- writes the study-road link-restoration QC summary to `artifacts/parity/stage1b_study_roads_link_restoration_qc.json`
- can retry that same bounded study-road restoration using `EVENT_SOUR + normalized(RTE_NM) + FROM_MEASURE + TO_MEASURE` when the raw exact-key gap is proven to be route-format drift only
- writes the normalized-route-key restored study-road boundary to `artifacts/output/stage1b_study_slice/Study_Roads_Divided_LinkRestored_NormalizedRouteKey.parquet`
- writes the normalized-route-key study-road link-restoration QC summary to `artifacts/parity/stage1b_study_roads_link_restoration_normalized_route_key_qc.json`
- can deterministically carry the restored bridge-bearing identity from `Study_Roads_Divided_LinkRestored_NormalizedRouteKey` into the downstream Stage 1B segment Oracle-prep chain using only truthful existing lineage helpers
- writes the downstream inherited Oracle-prep boundary to `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep_LinkInherited.parquet`
- writes the Stage 1B segment link-inheritance QC summary to `artifacts/parity/stage1b_segment_link_inheritance_qc.json`
- can reassess Oracle matching-contract readiness on the deterministically inherited bridge-bearing segment subset without performing any actual Oracle-to-segment match
- writes the resumed Oracle matching-contract audit layer to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatchingContract_Resumed.parquet`
- writes the resumed Stage 1B segment Oracle matching-contract QC summary to `artifacts/parity/stage1b_segment_oracle_matching_contract_resumed_qc.json`
- can execute the first real Oracle-to-segment match only on the 84 resumed contract-ready bridge-bearing segment rows while keeping the partial and blocked inherited rows out of scope
- writes the bounded ready-subset Oracle true-match output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleTrueMatch_ReadySubset.parquet`
- writes the bounded ready-subset Oracle true-match QC summary to `artifacts/parity/stage1b_segment_oracle_true_match_ready_subset_qc.json`
- can audit only the 77 prior clean ready-subset matches and 7 prior unresolved ready-subset rows to define a downstream-safe matched subset candidate plus an explicit quarantine subset without performing any new Oracle matching
- writes the bounded ready-subset stability-audit output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleTrueMatch_ReadySubset_StabilityAudit.parquet`
- writes the bounded ready-subset stability-audit QC summary to `artifacts/parity/stage1b_segment_oracle_true_match_ready_subset_stability_qc.json`
- can define the exact downstream-safe matched subset boundary from that authoritative stability audit by including only stable rows, preserving strict-versus-caution classification, and excluding all quarantined rows
- writes the downstream-safe matched subset output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeSubset.parquet`
- writes the downstream-safe matched subset QC summary to `artifacts/parity/stage1b_segment_oracle_matched_downstream_safe_subset_qc.json`
- can define the first formal downstream-safe consumer handoff boundary from that authoritative 77-row subset while preserving strict-versus-caution handling and explicit allowed-versus-disallowed use restrictions
- writes the downstream-safe consumer handoff output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeConsumerHandoff.parquet`
- writes the downstream-safe consumer handoff QC summary to `artifacts/parity/stage1b_segment_oracle_downstream_safe_consumer_handoff_qc.json`
- can create the first downstream-consumer-ready staging boundary from that authoritative 77-row consumer handoff while preserving strict-versus-caution handling and existing use restrictions
- writes the downstream-safe consumer staging output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeConsumerStaging.parquet`
- writes the downstream-safe consumer staging QC summary to `artifacts/parity/stage1b_segment_oracle_downstream_safe_consumer_staging_qc.json`
- can create the first downstream-safe analytical context bundle from that authoritative 77-row consumer staging boundary while preserving strict-versus-caution handling, grouped summaries, and existing use restrictions
- writes the downstream-safe analytical context output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeAnalyticalContext.parquet`
- writes the downstream-safe analytical context summaries to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeAnalyticalContext_Summaries.csv`
- writes the downstream-safe analytical context QC summary to `artifacts/parity/stage1b_segment_oracle_downstream_safe_analytical_context_qc.json`
- can create the first downstream-safe review package from that authoritative 77-row analytical-context bundle while preserving strict-versus-caution handling, review grouping/prioritization metadata, and existing use restrictions
- writes the downstream-safe review output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeReview.parquet`
- writes the downstream-safe review summaries to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeReview_Summaries.csv`
- writes the downstream-safe review QC summary to `artifacts/parity/stage1b_segment_oracle_downstream_safe_review_qc.json`
- can create the first downstream-safe triage package from that authoritative 77-row review boundary while preserving strict-versus-caution handling, triage grouping/prioritization metadata, and existing use restrictions
- writes the downstream-safe triage output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeTriage.parquet`
- writes the downstream-safe triage summaries to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeTriage_Summaries.csv`
- writes the downstream-safe triage QC summary to `artifacts/parity/stage1b_segment_oracle_downstream_safe_triage_qc.json`
- can create the first downstream-safe decision-support package from that authoritative 77-row triage boundary while preserving strict-versus-caution handling, recommended-action metadata, and existing use restrictions
- writes the downstream-safe decision-support output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeDecisionSupport.parquet`
- writes the downstream-safe decision-support summaries to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_DownstreamSafeDecisionSupport_Summaries.csv`
- writes the downstream-safe decision-support QC summary to `artifacts/parity/stage1b_segment_oracle_downstream_safe_decision_support_qc.json`
- can formally close the bounded Oracle-safe-subset branch of Stage 1B and create the explicit Stage 1C handoff boundary from that authoritative 77-row decision-support package while preserving strict-versus-caution handling and existing restrictions
- writes the Stage 1B closure / Stage 1C handoff output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1B_ClosureHandoff.parquet`
- writes the Stage 1B closure / Stage 1C handoff summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1B_ClosureHandoff_Summary.csv`
- writes the Stage 1B closure / Stage 1C handoff QC summary to `artifacts/parity/stage1b_oracle_safe_subset_closure_handoff_qc.json`
- can create the first runnable Stage 1C non-directional consumer slice from that authoritative 77-row closure/handoff boundary while preserving strict-versus-caution handling, validated-use guidance, and existing restrictions
- writes the Stage 1C non-directional consumer slice output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerSlice.parquet`
- writes the Stage 1C non-directional consumer slice summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerSlice_Summary.csv`
- writes the Stage 1C non-directional consumer slice QC summary to `artifacts/parity/stage1c_nondirectional_consumer_slice_qc.json`
- can create the first real Stage 1C non-directional consumer output layer from that authoritative 77-row consumer slice while preserving strict-versus-caution handling, validated-use guidance, and existing restrictions
- writes the Stage 1C non-directional consumer output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerOutput.parquet`
- writes the Stage 1C non-directional consumer output summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalConsumerOutput_Summary.csv`
- writes the Stage 1C non-directional consumer output QC summary to `artifacts/parity/stage1c_nondirectional_consumer_output_qc.json`
- can create the first bounded runnable non-directional Stage 1C mini vertical slice from that authoritative 77-row consumer output while preserving strict-versus-caution handling, validated-use guidance, and existing restrictions
- writes the Stage 1C non-directional mini-slice output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalMiniSlice.parquet`
- writes the Stage 1C non-directional mini-slice summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalMiniSlice_Summary.csv`
- writes the Stage 1C non-directional mini-slice QC summary to `artifacts/parity/stage1c_nondirectional_minislice_qc.json`
- can audit how much of the AGENTS Stage 1C vertical-slice contract that authoritative 77-row non-directional mini-slice now satisfies, what remains missing, and what the next bounded expansion target should be
- writes the Stage 1C capability/gap audit output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CapabilityGapAudit.parquet`
- writes the Stage 1C capability/gap audit summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CapabilityGapAudit_Summary.csv`
- writes the Stage 1C capability/gap audit QC summary to `artifacts/parity/stage1c_capability_gap_audit_qc.json`
- can define the bounded crash/access-readiness contract for that same authoritative 77-row branch by identifying which lineage fields are already present, which crash/access staging fields remain missing, and what the next justified crash/access target should be without performing assignment
- writes the Stage 1C crash/access-readiness contract output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CrashAccessReadinessContract.parquet`
- writes the Stage 1C crash/access-readiness contract summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CrashAccessReadinessContract_Summary.csv`
- writes the Stage 1C crash/access-readiness contract QC summary to `artifacts/parity/stage1c_crash_access_readiness_contract_qc.json`
- can define the bounded combined crash/access staging contract for that same authoritative 77-row branch by staging normalized crash/access source-boundary fields plus join-preparation metadata without performing final assignment
- writes the Stage 1C crash/access staging-contract output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CrashAccessStagingContract.parquet`
- writes the Stage 1C crash/access staging-contract summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CrashAccessStagingContract_Summary.csv`
- writes the Stage 1C crash/access staging-contract QC summary to `artifacts/parity/stage1c_crash_access_staging_contract_qc.json`
- can audit whether those staged crash/access source-boundary fields can land cleanly enough on that same authoritative 77-row branch to justify a later bounded assignment step without performing final crash or access assignment
- writes the Stage 1C crash/access join-audit output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CrashAccessJoinAudit.parquet`
- writes the Stage 1C crash/access join-audit summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_CrashAccessJoinAudit_Summary.csv`
- writes the Stage 1C crash/access join-audit QC summary to `artifacts/parity/stage1c_crash_access_join_audit_qc.json`
- can complete the bounded non-directional Stage 1C crash-side bundle for that same authoritative 77-row branch by assigning only the crash rows justified by the join audit while explicitly holding access back
- writes the completed Stage 1C non-directional slice output to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice.parquet`
- writes the completed Stage 1C non-directional slice summary to `artifacts/output/stage1_bridge_boundary/Functional_Segments_OracleMatched_Stage1C_NonDirectionalCompletedSlice_Summary.csv`
- writes the completed Stage 1C non-directional slice QC summary to `artifacts/parity/stage1c_nondirectional_completed_slice_qc.json`
- can audit the 335 authoritative parent rows that fail to land back on `Study_Roads_Divided` by the raw exact parent key to determine whether the restoration gap reflects route/key drift, measure drift, or deeper target-boundary divergence before any downstream inheritance is attempted
- writes the study-road link-restoration reconciliation audit to `artifacts/output/stage1_bridge_boundary/Study_Roads_Divided_LinkRestoration_Reconciliation.parquet`
- writes the study-road link-restoration reconciliation QC summary to `artifacts/parity/stage1b_study_roads_link_restoration_reconciliation_qc.json`
- can validate record-level `LINKID` joinability from the configured `New_AADT` source onto traffic-volume lineage using exact route-plus-measure strategies
- writes the record-level `LINKID` joinability summary to `artifacts/parity/stage1_aadt_traffic_volume_linkid_join_qc.json`
- keeps the Stage 1 open-source path compatible with later supplemental bridge-key inputs and Oracle-backed enrichment when those are needed to preserve analytical meaning
- treats repo-local Oracle exports as useful transition artifacts rather than the only allowed long-term Oracle mechanism

## Current scope

This tooling now covers the Stage 1A portability boundary, the first bounded Stage 1B runtime slice, the bounded study-eligibility bridge split needed before the first live Oracle step on the study-scoped branch, the bounded post-lookup Oracle-return disambiguation layer, the bounded evidence-refinement layer on the already-classified non-clean study-scoped rows, the bounded Oracle-side segment-ready handoff-definition layer, the bounded Oracle-to-segment matching-contract audit layer, the bounded segment-lineage support augmentation layer, the bounded post-augmentation matching-contract re-audit layer, the bounded support-only candidate-narrowing audit on the stronger measure-assisted subset, the bounded follow-up edge-case audit on the most extreme narrowing outcomes, the bounded true-match experiment-design layer for the five informative edge-case rows, the bounded execution of that same five-row experiment under the pre-written evidence contract, the bounded boundary-rule sensitivity re-audit of the two unresolved experiment rows, the bounded LINKID lineage trace that identifies where bridge-bearing identity is lost before later segment-lineage matching work, the bounded parent-lineage reattachment of those bridge-bearing fields back onto `Study_Roads_Divided`, the bounded reconciliation audit that explains the remaining non-landing parent rows before any downstream inheritance is attempted, the bounded normalized-route-key retry that tests whether route-name whitespace normalization closes that remaining study-road restoration gap, the bounded deterministic inheritance step that carries the restored bridge-bearing parent subset into the downstream Stage 1B segment Oracle-prep chain as far as truthful lineage allows, the bounded resumed Oracle matching-contract audit on that inherited subset, the first tightly bounded true Oracle-to-segment match execution on the 84 resumed contract-ready bridge-bearing segment rows only, the bounded post-match stability/quarantine audit that reclassifies only the resulting 77 prior clean matches and 7 prior unresolved rows without reopening matching scope, the bounded downstream-safe subset-definition step that writes the exact 77-row matched subset boundary for later work while preserving the caution distinction, the bounded downstream-safe consumer handoff step that formalizes allowed versus disallowed later consumer use within that same 77-row boundary, the bounded downstream-safe consumer staging step that carries those same 77 rows plus curated allowed Oracle/context metadata into a consumer-ready staging boundary without adding directionality or reopening scope, the bounded downstream-safe analytical context step that turns that same 77-row staging boundary into a consumer-ready analytical slice plus grouped summaries without adding directionality, crashes, or access assignments, the bounded downstream-safe review step that turns that same 77-row analytical slice into a review-ready package with clearer review grouping and prioritization metadata, the bounded downstream-safe triage step that turns that same 77-row review package into a triage-oriented inspection boundary with explicit review-order metadata, the bounded downstream-safe decision-support step that turns that same 77-row triage package into a decision-support boundary with explicit recommended-action metadata, the bounded Stage 1B closure / Stage 1C handoff step that formally closes that same 77-row Oracle-safe-subset branch and defines the exact restricted boundary a later Stage 1C vertical slice may consume, and the first runnable Stage 1C non-directional consumer slice that proves that same 77-row Oracle-safe boundary can now feed a real downstream consumer slice without reopening matching scope or assigning directionality, crashes, or access. It does not execute the full GIS pipeline.

Within Stage 1, trustworthy downstream directionality should not be forced from geometry-only lineage when the needed network-reference keys are missing. The current portability path therefore allows for later comparison of traffic-volume and AADT lineage, insertion of a GIS-side bridge key at the cleanest justified boundary, and configured live Oracle access if pre-exported CSVs are not sufficient for faithful downstream-direction enrichment.

See `docs/stage1_staging_contract.md` for the explicit Stage 1A portable input boundary and parity contract.
See `docs/stage1b_study_slice.md` for the bounded Stage 1B study-road and study-signal slice.
See `docs/stage2_oracle_safe_branch_architecture_summary.md` for the Stage 2 architecture-first summary of the bounded Oracle-safe branch.
See `docs/stage2_oracle_safe_branch_traceability_map.md` for the command-to-artifact traceability map of that same branch.
