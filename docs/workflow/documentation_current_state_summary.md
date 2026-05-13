# Documentation Current State Summary

## Current Active Workflow

The current active methodology is roadway_graph / Step 5 graph-first:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after the roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction -> unresolved/review-only cases preserved.

## Key Current Docs

- `docs/methodology/current_methodology_index.md`
- `docs/methodology/overview_methodology.md`
- `docs/methodology/roadway_graph_methodology.md`
- `docs/workflow/current_workflow_index.md`
- `docs/workflow/active_workflow.md`
- `docs/workflow/roadway_graph_workflow.md`
- `docs/results/current_results_index.md`

## Key Current Outputs

Raw/generated outputs remain under `work/output/`, not `docs/`.

Current roadway_graph outputs are under `work/output/roadway_graph/`, especially:

- `tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`
- `tables/current/signal_oriented_roadway_segments_geometric_direction.csv`
- `tables/current/signal_oriented_segment_bins_geometric_direction.csv`
- `tables/current/divided_carriageway_pair_candidates.csv`
- `tables/current/signal_oriented_roadway_segments_divided_pairing_enriched.csv`
- `tables/current/roadway_role_classification.csv`
- `tables/current/signal_oriented_roadway_segments_role_enriched.csv`

## What Not To Touch

- Do not modify generated outputs under `work/output/` unless explicitly asked.
- Do not treat `directionality_experiment`, `upstream_downstream_prototype`, `directed_segments`, or signal-centered Package 001/002/003 docs as current methodology.
- Do not use crash direction to define current upstream/downstream interpretation.
- Do not broaden into modeling or policy guidance before denominator coverage, unresolved cases, and validation are reviewed.
- Do not move context_enrichment or access_route_conflict docs until a graph-first crash/access migration decision is made.

## Next Technical Task

Implement divided-pairing recovery using roadway role classification.

Start with unpaired `mainline_divided_carriageway` rows. Preserve accepted high/medium-confidence pairs. Keep unresolved/review-only cases visible. Treat one-way pair candidates through a separate reviewed one-way method. Do not perform broad graph repair or modeling in this next step.
