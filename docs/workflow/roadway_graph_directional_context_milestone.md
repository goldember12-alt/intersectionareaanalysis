# Roadway Graph Directional Context Milestone

**Status: CURRENT ACTIVE MILESTONE.** This document records the current full prototype product after crash assignment and context enrichment were joined into the roadway-derived directional-bin universe.

## Current Product

The current product is a stable roadway-derived directional-bin context universe for signalized-intersection downstream functional area analysis. It combines the roadway graph scaffold, directional catchments, conservative crash assignment, access context, posted-speed context, AADT context, and crash-level urban/rural context.

The final product output folder is:

`work/output/roadway_graph/analysis/current/directional_bin_context_table/`

The primary table is:

`directional_bin_context.csv`

## Stable Universe

- 0-2,500 ft directional bins are the current prototype analysis universe.
- 0-1,000 ft is the high-priority descriptive subset.
- 1,000-2,500 ft is the sensitivity subset.
- Greater than 2,500 ft remains review-only and is excluded from the main combined context outputs.

## Core Counts

- total bins: 110,710
- 0-1,000 ft bins: 66,074
- 1,000-2,500 ft bins: 44,636
- bins with assigned crashes: 8,552
- crashes represented: 13,216
- bins with access context: 110,710
- bins with stable speed context: 84,857
- bins with stable AADT context: 106,210
- assigned crashes with crash-level urban/rural classification: 13,216
- assigned urban crashes: 11,915
- assigned rural crashes: 1,301
- assigned unknown crash area type: 0
- roadway-level urban/rural context: unavailable, `source_not_found`

## Accepted Context Layers

The combined context table uses these accepted current layers:

- crash assignment and readiness:
  `work/output/roadway_graph/review/current/crash_directional_catchment_assignment_prototype/`
  `work/output/roadway_graph/review/current/crash_directional_assignment_analysis_readiness/`
- access:
  `work/output/roadway_graph/review/current/access_context_join/`
- speed v4:
  `work/output/roadway_graph/review/current/speed_context_join_v4_identity_enriched/`
- AADT v3:
  `work/output/roadway_graph/review/current/aadt_context_join_v3_identity_route_measure/`
- crash AREA_TYPE urban/rural:
  `artifacts/normalized/crashes.parquet`, using `DOCUMENT_NBR` and `AREA_TYPE` only
- roadway urban/rural source decision:
  `work/output/roadway_graph/review/current/urban_rural_source_recovery/`

## Methodological Boundaries

- Crash direction fields were not read or used.
- Context fields do not redefine upstream/downstream.
- Upstream/downstream remains roadway-derived.
- Crash `AREA_TYPE` is crash-level context only.
- Crash `AREA_TYPE` does not populate no-crash bins.
- Crash `AREA_TYPE` is not roadway-level urban/rural truth.
- Roadway-level urban/rural source is unavailable and remains `source_not_found`.
- Greater than 2,500 ft remains review-only.

## Known Limitations

- Blocked divided records remain outside the usable directional universe.
- Ambiguous and unresolved crashes are excluded from assigned-crash summaries.
- Roadway-level urban/rural context is unavailable.
- Speed and AADT review/missing statuses are preserved in the context table.
- The product is descriptive and exploratory, not policy-ready or modeling-ready.
- Additional proposal-facing products need explicit analysis units, denominator decisions, uncertainty treatment, and validation rules.

## Recommended Next Phase

The next phase should not restart source recovery. It should use this prototype universe to decide:

- which descriptive analysis products are needed
- which stakeholder-facing summaries or maps are useful
- whether the prototype should be hardened into a production pipeline
- what validation gates are required before regression, modeling, or policy-facing guidance

Before modeling or policy claims, revisit the proposal/design documentation and define the dependent variable, denominators, unresolved-case handling, evidence provenance, and validation checks.
