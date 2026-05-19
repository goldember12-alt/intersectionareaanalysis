# Documentation Final Consolidation

## Summary

This pass finalized the documentation navigation after Stage A and cautious Stage B. It did not move additional files, delete documentation, modify code, modify generated outputs, commit, or push.

## Current Active Methodology

The current active methodology is roadway_graph / Step 5 graph-first:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after the roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction -> unresolved/review-only cases preserved.

## Files Changed

Primary consolidation edits:

- `README.md`
- `AGENTS.md`
- `docs/README.md`
- `legacy/docs/README.md`
- `docs/methodology/overview_methodology.md`
- `docs/methodology/current_methodology_index.md`
- `docs/workflow/current_workflow_index.md`
- `docs/results/current_results_index.md`
- `docs/workflow/active_workflow.md`
- `docs/workflow/roadway_graph_workflow.md`
- `legacy/docs/repo_redesign_plan_legacy_copy_20260421.md`

Final closeout files added:

- `docs/workflow/documentation_final_consolidation.md`
- `docs/workflow/documentation_final_link_check.csv`
- `docs/workflow/documentation_current_state_summary.md`

Earlier Stage A/B artifacts remain part of the documentation reorganization record:

- `docs/workflow/documentation_reorganization_stage_a_b_completed.md`
- `docs/workflow/documentation_reorganization_move_log.csv`
- `docs/workflow/documentation_reorganization_link_check.csv`

## What Was Verified

- README, AGENTS, docs/README, active_workflow, and overview_methodology agree that roadway_graph / Step 5 graph-first is current.
- `overview_methodology.md` is now a stable graph-first overview rather than a mixed directed-segment/signal-centered overview.
- `active_workflow.md` and `roadway_graph_workflow.md` agree on current roadway_graph module status, crash-ready inputs, crash assignment prototype status, geometric direction, divided pairing, roadway role classification, and the next recommended step.
- `docs/results/current_results_index.md` points to curated readout docs and makes clear that raw CSVs remain under `work/output/`.
- Moved legacy docs remain reachable under `legacy/docs/`.
- Context enrichment and access-route conflict docs remain in place as supporting references.
- Proposal Package 001/002/003 docs remain in place with legacy/prior-package status.
- Current roadway_graph docs remain under `docs/`.
- `docs/reports/current_work_package_memo_2026_05_06.md` and `.pdf` remain under `docs/reports/`.

## Legacy/Superseded Documentation Status

The following are historical or supporting reference, not current methodology:

- signal-centered Package 001/002/003
- directed_segments
- directionality_experiment
- upstream_downstream_prototype
- high-confidence downstream descriptive analysis
- context_enrichment and access_route_conflict docs, until a later graph-first crash/access migration decision

## Known Remaining Documentation Issues

- `docs/reports/style_examples/draft.md` references missing figure files under `figures/`. These links were pre-existing and unrelated to the roadway_graph documentation consolidation.
- Older recovery-audit files under `legacy/docs/recovery_audits/` still contain old `docs/...` paths as historical text. They were not rewritten because they preserve dated recovery context.
- Roadway_graph curated readouts still mostly live under `docs/workflow/`; future consolidation may move them to `docs/results/` after the next technical pass.
- `docs/workflow/documentation_final_link_check.csv` and other CSV closeout artifacts are ignored by the repo-wide `*.csv` rule unless explicitly force-added during staging.

## Recommended Commit Message

```text
Consolidate graph-first documentation navigation
```

## Next Work

The next technical task is QGIS review of the divided-pairing recovery prototype, focused on low-confidence candidates and still-unresolved `mainline_divided_carriageway` rows. Do not jump to broad graph repair, statewide modeling, or policy guidance before that review is complete.
