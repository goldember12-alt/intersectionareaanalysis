# Src File Classification

This note classifies every current source file and records the sorted bucket layout under `src/`.

Rules used:
- `active`: part of the current reduced runnable path
- `transitional`: still in the active package for bounded diagnostics or short-term support
- `legacy-candidate`: not part of the active path and already preserved under `legacy/portability_branch/stage1_portable/`

Package-path note:
- the active package folder is `src/`
- preserved historical copies still live under `legacy/portability_branch/stage1_portable/`

## Sorted Buckets

- `src/active/` holds the authoritative runnable copies for the current bounded workflow.
- `src/transitional/` holds bounded diagnostics still under inspection.
- `src/legacy/` holds a local mirror of the already-preserved legacy portability-branch modules.
- root-level `src/*.py` files may still exist as OneDrive reparse-point leftovers; where possible they now act as wrappers or stubs.

## Active

| File | Classification | Legacy copy already present |
|---|---|---|
| `active/__init__.py` | active | no |
| `active/__main__.py` | active | no |
| `active/config.py` | active | no |
| `active/study_slice.py` | active | no |
| `active/directionality_experiment.py` | active | no |
| `active/README.md` | active | no |

## Transitional

| File | Classification | Legacy copy already present |
|---|---|---|
| `transitional/__init__.py` | transitional | no |
| `transitional/config.py` | transitional | no |
| `transitional/bridge_key_audit.py` | transitional | no |
| `transitional/bridge_key_geojson_audit.py` | transitional | no |

## Legacy-Candidate

All files in this section already have preserved copies in `legacy/portability_branch/stage1_portable/`.
No additional copy-to-legacy action was needed before they became safe deletion candidates.
The `src/legacy/` mirror is for local inspection and organization, not for renewed active use.

| File | Classification | Legacy copy already present |
|---|---|---|
| `bridge_key_boundary.py` | legacy-candidate | yes |
| `bridge_key_direct_validation.py` | legacy-candidate | yes |
| `bridge_key_join_validation.py` | legacy-candidate | yes |
| `bridge_key_lineage_validation.py` | legacy-candidate | yes |
| `bridge_key_study_eligibility_split.py` | legacy-candidate | yes |
| `bridge_key_study_roads_validation.py` | legacy-candidate | yes |
| `bridge_key_unmatched_audit.py` | legacy-candidate | yes |
| `segment_lineage_support.py` | legacy-candidate | yes |
| `stage1b_downstream_safe_packaging_helpers.py` | legacy-candidate | yes |
| `stage1b_linkid_lineage_trace.py` | legacy-candidate | yes |
| `stage1b_oracle_safe_subset_closure_handoff.py` | legacy-candidate | yes |
| `stage1b_segment_link_inheritance.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_downstream_safe_analytical_context.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_downstream_safe_consumer_handoff.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_downstream_safe_consumer_staging.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_downstream_safe_decision_support.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_downstream_safe_review.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_downstream_safe_triage.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_matched_downstream_safe_subset.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_matching_contract_resumed.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_true_match_ready_subset.py` | legacy-candidate | yes |
| `stage1b_segment_oracle_true_match_ready_subset_stability_audit.py` | legacy-candidate | yes |
| `stage1b_study_roads_link_restoration.py` | legacy-candidate | yes |
| `stage1b_study_roads_link_restoration_normalized_route_key.py` | legacy-candidate | yes |
| `stage1b_study_roads_link_restoration_reconciliation.py` | legacy-candidate | yes |
| `stage1c_capability_gap_audit.py` | legacy-candidate | yes |
| `stage1c_crash_access_join_audit.py` | legacy-candidate | yes |
| `stage1c_crash_access_readiness_contract.py` | legacy-candidate | yes |
| `stage1c_crash_access_staging_contract.py` | legacy-candidate | yes |
| `stage1c_nondirectional_completed_slice.py` | legacy-candidate | yes |
| `stage1c_nondirectional_consumer_output.py` | legacy-candidate | yes |
| `stage1c_nondirectional_consumer_slice.py` | legacy-candidate | yes |
| `stage1c_nondirectional_minislice.py` | legacy-candidate | yes |
| `study_scoped_oracle_disambiguation.py` | legacy-candidate | yes |
| `study_scoped_oracle_evidence_refinement.py` | legacy-candidate | yes |
| `study_scoped_oracle_lookup.py` | legacy-candidate | yes |
| `study_scoped_oracle_segment_candidate_narrowing.py` | legacy-candidate | yes |
| `study_scoped_oracle_segment_edge_case_audit.py` | legacy-candidate | yes |
| `study_scoped_oracle_segment_matching_contract.py` | legacy-candidate | yes |
| `study_scoped_oracle_segment_matching_contract_reaudit.py` | legacy-candidate | yes |
| `study_scoped_oracle_segment_ready_handoff.py` | legacy-candidate | yes |
| `study_scoped_oracle_true_match_boundary_sensitivity.py` | legacy-candidate | yes |
| `study_scoped_oracle_true_match_experiment_design.py` | legacy-candidate | yes |
| `study_scoped_oracle_true_match_experiment_results.py` | legacy-candidate | yes |
