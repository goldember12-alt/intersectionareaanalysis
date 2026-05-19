# Documentation Reorganization Stage A/B Completed

## Bounded Question

This pass separated current roadway_graph / Step 5 graph-first documentation from superseded signal-centered, directed_segments, directionality, and upstream_downstream prototype documentation without modifying code or generated outputs.

## Current Active Method

The current active method is graph-first:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after the roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction -> unresolved/review-only cases preserved.

## Stage A Completed

- Added short status banners to current roadway_graph docs, support docs, historical/superseded docs, and prior signal-centered package docs.
- Updated the six current index files so they point first to the roadway_graph / Step 5 graph-first workflow.
- Added the six-folder contract to the index/navigation layer:
  - `docs/design/` = proposed schemas, planning, future designs
  - `docs/methodology/` = stable methodological explanations
  - `docs/diagrams/` = figure/source diagram assets
  - `docs/reports/` = polished/shareable reports
  - `docs/results/` = curated result/readout summaries, not raw CSVs
  - `docs/workflow/` = active commands, output contracts, and operational notes
- Updated `README.md`, `AGENTS.md`, `docs/README.md`, `docs/workflow/active_workflow.md`, and `docs/methodology/overview_methodology.md` so roadway_graph is the current methodology pointer.

## Stage B Completed

Created `legacy/docs/` and moved only clearly superseded historical docs from the relocation plan:

- directed_segments methodology/workflow/readout docs
- directionality experiment result docs and decision diagram assets
- upstream_downstream prototype decision-flow docs and diagram assets
- `package_003_signal_outlier_map_review_batch_A_guide.md`
- dated repository recovery audit

The full move list is recorded in `docs/workflow/documentation_reorganization_move_log.csv`.

## Kept Active

- Current roadway_graph methodology and workflow docs stayed under `docs/`.
- Current roadway_graph Step 5, geometric direction, divided pairing, roadway role, crash-ready, QGIS, and readout docs stayed under `docs/workflow/`.
- Current report memo files stayed under `docs/reports/`.

## Kept In Place As Support Or Prior Package Context

- Context enrichment docs stayed under `docs/workflow/` with supporting-reference banners.
- Access route-conflict docs stayed under `docs/workflow/` with supporting-reference banners.
- Proposal Package 001/002/003 docs stayed under `docs/workflow/` with legacy signal-centered package banners.
- Proposal table-contract and distance-band design notes stayed under `docs/workflow/` as current support/planning references.

## Validation

- Verified every moved file exists at its new `legacy/docs/` location.
- Verified old moved locations are no longer present under `docs/`.
- Verified current roadway_graph docs remain under `docs/workflow/`.
- Verified no context_enrichment or access_route_conflict docs were moved to `legacy/docs/`.
- Verified `docs/reports/current_work_package_memo_2026_05_06.md` and `.pdf` were not moved.
- Verified no generated outputs under `work/output/` were modified.
- Verified markdown links; only pre-existing missing links in `docs/reports/style_examples/draft.md` were found.

## Remaining Uncertainty

- `docs/methodology/overview_methodology.md` still contains some historical framing and should get a focused graph-first rewrite in a later stage.
- Context enrichment and access-route docs remain supporting references until a graph-first crash/access migration decides what to promote, rewrite, or archive.
- Roadway_graph result/readout docs still mostly live in `docs/workflow/`; moving curated summaries into `docs/results/` should be a later, separate pass.
