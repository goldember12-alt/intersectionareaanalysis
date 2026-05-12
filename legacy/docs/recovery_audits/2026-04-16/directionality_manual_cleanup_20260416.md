# Directionality Experiment Manual Cleanup Guide

Date: 2026-04-16

Scope: `work/output/directionality_experiment/` only.

## Final Intended Root-Level Contents

After manual cleanup, the intended root-level contents are:

- `README.md`
- `tables/`
- `review/`
- `runs/`
- `legacy_flat_layout/`
- `runtime_junk_quarantine/`

That is the intended root contract for this module output area.

## Classification Table

| root-level item | classification | reason |
| --- | --- | --- |
| `legacy_flat_layout` | keep | Containment copy folder for preserved legacy flat-layout spill. |
| `review` | keep | Authoritative grouped current review output lane. |
| `runs` | keep | Authoritative grouped current run-summary lane. |
| `runtime_junk_quarantine` | keep | Containment copy folder for preserved runtime junk and failed cleanup diagnostics. |
| `tables` | keep | Authoritative grouped current output lane. |
| `_gpkg_probe.gpkg` | manually delete now | Runtime junk at root; containment copy already exists in `runtime_junk_quarantine/`. |
| `_gpkg_probe.gpkg-journal` | manually delete now | Runtime junk at root; containment copy already exists in `runtime_junk_quarantine/`. |
| `assignment_table.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_123355.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `assignment_table_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_123355.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_crash_dot_only_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_123355.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `baseline_roadway_context_only_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_123355.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `conflict_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_123355.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `evidence_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_assignment_table_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_attached_crashes_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_profile_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_profile_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_profile_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_profile_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_conflict_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_corridor_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_empirical_vs_fallback_disagreement.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_empirical_vs_fallback_disagreement_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_fallback_only_assignments.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_fallback_only_assignments_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_newly_assigned_empirical90.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_newly_assigned_empirical90_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_newly_assigned_single_vehicle_support_only.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_newly_assigned_single_vehicle_support_only_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_reason_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_123447.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_123447.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_123628.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_123628.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_123703.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_123703.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_154426.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_154426.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_154618.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_154618.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_155638.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_155638.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_155752.gpkg` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_20260414_155752.gpkg-journal` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_support_bucket_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_support_bucket_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets_20260414_123447.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets_20260414_123627.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets_20260414_123703.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets_20260414_154426.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_review_targets_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_comparison_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_comparison_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_comparison_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_comparison_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_transition_summary.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_transition_summary_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_transition_summary_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_rule_transition_summary_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_single_vehicle_clean_rows.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_single_vehicle_clean_rows_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_soft_conflicts_80_89.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_soft_conflicts_80_89_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_soft_conflicts_90_plus.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_soft_conflicts_90_plus_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_still_unresolved_after_all_variants.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_still_unresolved_after_all_variants_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_variant_review_targets.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_variant_review_targets_20260414_154618.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_variant_review_targets_20260414_155638.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `expanded_variant_review_targets_20260414_155752.csv` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `README.md` | keep | Intentional root-level contract file written by the current module. |
| `review_support_summary.md` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `review_support_summary_20260414_155752.md` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `run_summary.json` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `run_summary_20260414_123719.json` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `run_summary_20260414_154441.json` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `run_summary_20260414_154633.json` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `run_summary_20260414_155653.json` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |
| `run_summary_20260414_155808.json` | manually delete now | Legacy flat-layout root spill; containment copy already exists in `legacy_flat_layout/` and grouped outputs are authoritative. |

## Recommended Manual Cleanup Order

For File Explorer or an interactive PowerShell session, use this order:

1. Open `work/output/directionality_experiment/`.
2. Confirm the keep set is present: `README.md`, `tables/`, `review/`, `runs/`, `legacy_flat_layout/`, and `runtime_junk_quarantine/`.
3. Do not open or edit anything under `tables/`, `review/`, or `runs/`.
4. Delete the two root-level probe files first:
   - `_gpkg_probe.gpkg`
   - `_gpkg_probe.gpkg-journal`
5. Delete the loose root-level flat-layout legacy files next. A practical order is:
   - root-level `assignment_table*.csv`, `baseline_*.csv`, `conflict_summary*.csv`, and `evidence_summary*.csv`
   - root-level `expanded_*.csv`
   - root-level `expanded_*.gpkg` and `expanded_*.gpkg-journal`
   - root-level `review_support_summary*.md`
   - root-level `run_summary*.json`
6. Leave `legacy_flat_layout/` and `runtime_junk_quarantine/` in place as containment copies.
7. Recheck the root. The remaining intended items should match the keep set above.

## Stop Conditions

Stop immediately and do not delete the item if any of the following is true:

- the item is `README.md`, `tables/`, `review/`, `runs/`, `legacy_flat_layout/`, or `runtime_junk_quarantine/`
- the item is inside `tables/`, `review/`, or `runs/` rather than at the module root
- the root item does not have a matching containment copy in `legacy_flat_layout/` or `runtime_junk_quarantine/`
- the item name is not listed in the table above

## Current Verification Status

- Items classified `verify before deleting`: none in this pass
- Items classified `leave alone for now`: none in this pass
