# Current Methodology Index

## Six-Folder Contract

- `docs/design/` = proposed schemas, planning, future designs
- `docs/methodology/` = stable methodological explanations
- `docs/diagrams/` = figure/source diagram assets
- `docs/reports/` = polished/shareable reports
- `docs/results/` = curated result/readout summaries, not raw CSVs
- `docs/workflow/` = active commands, output contracts, and operational notes

## Methodology Folder Contract

`docs/methodology/` is for stable, high-level methodological documents explaining what the active method is and why it is defensible. It should not hold one-off run logs, temporary QA notes, or legacy method docs unless they are clearly labeled as historical reference.

## Current Active Method

The current active methodology is the roadway_graph / Step 5 graph-first workflow:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after the roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction -> unresolved/review-only cases preserved.

## Current Methodology Documents

- `roadway_graph_methodology.md`: primary current graph-first methodology.
- `proposal_alignment_growth_plan.md`: current proposal-alignment growth plan; keep as a companion to graph-first methodology.
- `overview_methodology.md`: stable graph-first overview and repository-level methodology posture.

## Historical Or Superseded Methodology References

- `../../legacy/docs/methodology/directed_segment_methodology.md`: superseded prior divided-road vertical-slice reference.
- `../../legacy/docs/methodology/flow_method_comparison.md`: historical directionality experiment/method comparison.

## Next Methodology Work

Future methodology updates should document divided-pairing recovery after it is implemented and validated. Until then, use `roadway_graph_methodology.md` and `overview_methodology.md` as the current methodological anchors.
