# Directionality Output Root Cleanup Memo

Date: 2026-04-16

Scope: `work/output/directionality_experiment/` only.

## Question Being Solved

Make the module output root trustworthy by separating intentional grouped outputs from legacy flat-layout spill and obvious runtime junk without changing analytical logic or grouped output routing.

## Summary

- Root-level items inspected: 157
- Valid current grouped directories: 3
- Valid current root files: 1
- Legacy flat-layout artifacts: 151
- Runtime junk: 2
- Unclear items: 0

## Root-Level Classification Table

| path | classification | why | recommended disposition |
| --- | --- | --- | --- |
| `work/output/directionality_experiment/review` | valid current grouped directory | Active grouped output lane used by the current writer. | Keep active at root. |
| `work/output/directionality_experiment/runs` | valid current grouped directory | Active grouped output lane used by the current writer. | Keep active at root. |
| `work/output/directionality_experiment/tables` | valid current grouped directory | Active grouped output lane used by the current writer. | Keep active at root. |
| `work/output/directionality_experiment/README.md` | valid current root file | Intentional root-level contract and guide for this module output area. | Keep active at root and update text. |
| `work/output/directionality_experiment/_gpkg_probe.gpkg` | runtime junk | Probe artifact, not an intentional analytical deliverable. | Move to `runtime_junk_quarantine/`. |
| `work/output/directionality_experiment/_gpkg_probe.gpkg-journal` | runtime junk | Probe journal artifact, not an intentional analytical deliverable. | Move to `runtime_junk_quarantine/`. |
| `work/output/directionality_experiment/assignment_table.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_123355.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/assignment_table_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_123355.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_crash_dot_only_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_123355.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/baseline_roadway_context_only_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_123355.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/conflict_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_123355.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/evidence_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_assignment_table_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_attached_crashes_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_profile_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_profile_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_profile_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_profile_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_conflict_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_corridor_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_empirical_vs_fallback_disagreement.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_empirical_vs_fallback_disagreement_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_fallback_only_assignments.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_fallback_only_assignments_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_newly_assigned_empirical90.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_newly_assigned_empirical90_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_newly_assigned_single_vehicle_support_only.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_newly_assigned_single_vehicle_support_only_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_reason_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_123447.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_123447.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_123628.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_123628.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_123703.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_123703.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_154426.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_154426.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_154618.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_154618.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_155638.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_155638.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_155752.gpkg` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_20260414_155752.gpkg-journal` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_support_bucket_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_support_bucket_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets_20260414_123447.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets_20260414_123627.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets_20260414_123703.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets_20260414_154426.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_review_targets_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_comparison_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_comparison_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_comparison_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_comparison_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_transition_summary.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_transition_summary_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_transition_summary_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_rule_transition_summary_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_single_vehicle_clean_rows.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_single_vehicle_clean_rows_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_soft_conflicts_80_89.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_soft_conflicts_80_89_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_soft_conflicts_90_plus.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_soft_conflicts_90_plus_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_still_unresolved_after_all_variants.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_still_unresolved_after_all_variants_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_variant_review_targets.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_variant_review_targets_20260414_154618.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_variant_review_targets_20260414_155638.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/expanded_variant_review_targets_20260414_155752.csv` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/review_support_summary.md` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/review_support_summary_20260414_155752.md` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/run_summary.json` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/run_summary_20260414_123719.json` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/run_summary_20260414_154441.json` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/run_summary_20260414_154633.json` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/run_summary_20260414_155653.json` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |
| `work/output/directionality_experiment/run_summary_20260414_155808.json` | legacy flat-layout artifact | Loose root-level flat-layout output from earlier runs; current writer uses grouped subdirectories instead. | Move to `legacy_flat_layout/`. |

## Recommended Safe Actions

- Keep `README.md`, `tables/`, `review/`, and `runs/` active at the root.
- Move all loose legacy flat-layout root files into `work/output/directionality_experiment/legacy_flat_layout/`.
- Move `_gpkg_probe.gpkg` and `_gpkg_probe.gpkg-journal` into `work/output/directionality_experiment/runtime_junk_quarantine/`.
- Leave grouped current outputs untouched.
- Do not delete anything in this pass.

## Execution Results

Executed in this pass:

- Updated the root `README.md` to reflect the real grouped-output contract.
- Created `work/output/directionality_experiment/legacy_flat_layout/`.
- Created `work/output/directionality_experiment/runtime_junk_quarantine/`.
- Copied 151 legacy flat-layout root files into `legacy_flat_layout/`.
- Copied 2 probe artifacts into `runtime_junk_quarantine/`.
- The failed move-method checks left small staging subdirectories under `runtime_junk_quarantine/`; they are quarantine-only test artifacts, not analytical outputs.

Blocked in this environment:

- `Move-Item`, `robocopy /MOV`, and a direct .NET file move all failed on the source files with `UnauthorizedAccessException` or `Access is denied`.
- The affected source files present as OneDrive-backed reparse-point files, so the cleanup could not remove the original root copies.
- As a result, the containment folders now hold preserved copies, but the legacy and junk source files still remain at the module root.

Residual status after this pass:

- The module root contract is now documented clearly.
- The legacy spill and probe junk are now separated conceptually and materially in dedicated containment folders.
- The module root is not yet physically clean, because this environment would not allow source-file removal.

## Notes

- `history/` is not a root-level archive lane in this module. It exists under grouped output families and is only used when replacement of a current target fails due to a lock or permission collision.
- This memo documents the root as inspected before relocation, so the classification remains traceable after the cleanup move.
