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

The current active methodology is the stable-lineage expanded roadway scaffold workflow:

base staged signals -> represented signal universe -> calibrated expected physical-leg model -> recovery-first scaffold completion -> divided/carriageway subbranch normalization -> source/data limitation ledger -> stable Travelway lineage persistence at bin generation -> review-only speed/AADT/access context -> crash/catchment design only after scaffold and lineage QA.

This is still graph-first in evidence discipline: roadway geometry and source Travelway lineage define the scaffold before crashes are assigned. It is no longer just an early Step 5 foundation prototype. The current product is a review-only 2,739-signal represented universe with 262,329 scaffold bins, all speed+AADT-ready, with stable Travelway lineage persisted for nearly every bin.

## Current Methodology Documents

- `roadway_graph_methodology.md`: primary stable-lineage signal-relative scaffold methodology.
- `overview_methodology.md`: repository-level methodology posture, including recovery-first philosophy, source limitations, and access doctrine.
- `proposal_alignment_growth_plan.md`: controlled proposal-alignment growth plan for turning the scaffold into descriptive and later comparison-ready outputs.
- `access_code_mapping_notes.md` under `docs/workflow/`: typed access v2 raw-code mapping notes, including the review-only `R`/`RC` RIRO correction.
- `roadway_graph_lineage_requirements.md` under `docs/workflow/`: stable Travelway lineage field requirements for future scaffold, access, crash, and source-limitation outputs.

## Current Quantitative State

- Base staged signals: 3,933
- Final represented review-only signals: 2,739
- Final represented share: about 69.6%
- Final speed+AADT-ready signals: 2,739
- Final scaffold bins: 262,329

Final calibrated physical-leg distribution:

- one-leg: 234
- two-leg: 195
- three-leg: 798
- four-leg: 1,511
- five-plus: 1
- two-leg-or-less combined: 429

Scaffold recovery branch status:

- Branch A, direct missing-leg recovery: complete after final context refresh.
- Branch B, divided/carriageway normalization: complete enough to proceed.
- Branch C, source limitation/holdout: reduced to manual, external-data, and source limitations.

Remaining source/data limitation ledger:

- source_limited_holdout: 281
- grade_separated_or_mainline_contamination: 49
- still_insufficient_geometry_evidence: 54

## Current Methodological Rules

- Preserve and recover every defensible signal, physical leg, bin, and context record.
- Do not force weak scaffold labels for coverage.
- Treat remaining losses as explicit source/data limitations, grade/mainline holdouts, still-insufficient evidence, or manual-review classes.
- Treat physical legs as signalized-intersection approaches, not graph edges, route names, source rows, carriageways, or candidate associations.
- Represent divided carriageways, ramps, source-line splits, and route/facility changes as subbranches or QA attributes unless evidence supports a distinct physical approach.
- Persist stable Travelway lineage during scaffold/bin generation. Retrospective backfill is not enough.
- Preserve raw access codes alongside corrected typed access categories.

## Historical Or Superseded Methodology References

- `../../legacy/docs/methodology/directed_segment_methodology.md`: superseded prior divided-road vertical-slice reference.
- `../../legacy/docs/methodology/flow_method_comparison.md`: historical directionality experiment/method comparison.

Older TRUE-reference, divided-pairing-next, and Step 5 foundation wording should be read as historical context unless a current workflow document explicitly reactivates a bounded part of it.

## Next Methodology Work

Current next methodology work is:

1. Finalize the access doctrine/readout around spatial 100 ft, conservative Travelway-windowed sensitivity, broad Travelway-normalized source-coverage diagnostics, typed v2 enrichment, and untyped broad access density.
2. Prepare figure, table, and paper materials that explain the final scaffold, calibrated physical-leg distribution, source-limitation ledger, lineage discipline, and access-source limitations.
3. Design crash/catchment assignment using the stable-lineage scaffold and explicit source/data limitation flags.

No current methodology task should treat divided-pairing QGIS review as the next technical step; that branch has been reduced through recovery and normalization work.
