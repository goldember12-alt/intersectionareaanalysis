# Roadway Graph Divided Carriageway Pairing

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This diagnostic improves divided-road geometry support before any revised crash assignment or upstream/downstream interpretation.

It asks:

- where the Step 5 crash-ready divided rows around TRUE reference signals contain two physical carriageway geometries that can be paired as right/left candidates under a right-hand-traffic rule?

It does not read crash data, assign crashes, use crash direction fields, infer direction from crash distributions, modify old signal-centered crash/access modules, or promote termination-refined outputs.

## Command

Run with the bootstrap-reported interpreter:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.divided_carriageway_pairing
```

## Inputs

- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_50ft_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_geometric_direction.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_segment_bins_geometric_direction.csv`
- `work/output/roadway_graph/tables/current/roadway_graph_edges.csv`
- `work/output/roadway_graph/tables/current/signal_adjacent_edges.csv`
- `work/output/roadway_graph/tables/current/divided_edge_directional_candidates.csv`

The module reads roadway graph tables only. Crash records are not read.

## Outputs

- `work/output/roadway_graph/tables/current/divided_carriageway_pair_candidates.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_divided_pairing_enriched.csv`
- `work/output/roadway_graph/review/current/divided_carriageway_pairing_summary.csv`
- `work/output/roadway_graph/review/current/divided_carriageway_pairing_problem_rows.csv`
- `work/output/roadway_graph/review/current/divided_carriageway_unpaired_rows.csv`
- `work/output/roadway_graph/review/current/divided_carriageway_pairing_examples.csv`
- `work/output/roadway_graph/review/geojson/current/divided_carriageway_pairing_review.geojson`
- `work/output/roadway_graph/review/geojson/current/divided_carriageway_unpaired_review.geojson`

## Method

The pairing method works inside each TRUE reference signal and route stem. Route stems remove simple directional suffixes such as `N`, `S`, `E`, `W`, `NB`, `SB`, `EB`, and `WB` so that paired carriageways such as `US-29N` and `US-29S` can be compared as one corridor family.

Candidate pairs must:

- belong to the same TRUE reference signal and route stem
- use different `base_graph_edge_id` values
- use different `road_component_id` values
- avoid identical physical geometry signatures
- have similar outbound bearing from the reference signal
- bracket a shared A to B reference vector with one right-side and one left-side geometry

Accepted pairs use the right-hand-traffic convention:

- right side of A to B = `A_to_B` movement candidate
- left side of A to B = `B_to_A` movement candidate

The method does not pair unrelated nearby roads, ramps, or cross streets when they fail the same-signal, same-route-stem, different-component, same-leg-bearing, and bracketing checks.

## Current Results

Current no-crash readout:

- divided rows: 2,257
- paired divided rows: 810
- unpaired divided rows: 1,447
- accepted divided pair candidates: 405
- high-confidence pairs: 335
- medium-confidence pairs: 70
- low-confidence pairs: 0
- pairs with both `A_to_B` and `B_to_A` candidates: 405
- divided rows still unresolved: 1,447
- `true_vehicle_direction_inferred != false`: 0
- crash data read: `False`

All 1,947 undivided rows are preserved in the enriched segment output with `divided_pairing_status = not_applicable`.

## Interpretation

This diagnostic improves the prior geometric direction model by looking beyond exact anchor-pair grouping. Exact anchor-pair grouping was too strict because opposite divided carriageways often use different Travelway components and nearby but not identical non-signalized anchors.

The paired rows are stronger candidates for a future revised crash assignment prototype because they have explicit right/left physical carriageway relationships and candidate A to B / B to A movement orientation fields. The pairing still does not infer actual vehicle direction from crash records.

The 1,447 unpaired rows remain unresolved. They may represent one-sided source geometry, incomplete Travelway legs, endpoint-only legs, route-stem mismatches, geometry too close to the reference line, or cases needing a broader network-pairing rule.

A follow-up no-crash diagnosis of the 1,447 unresolved divided rows is documented in:

- `docs/workflow/roadway_graph_divided_pairing_unresolved_diagnosis.md`

That diagnosis keeps the current pairing logic unchanged and writes review summaries under `work/output/roadway_graph/review/current/`, including reason summaries, route/anchor/length/status breakdowns, possible logic-improvement queues, and a QGIS manual-review sample.

## Recommendation

Do not revise crash assignment or upstream/downstream interpretation using all divided rows yet.

The 405 accepted divided pairs are ready for small QGIS spot check using `divided_carriageway_pairing_review.geojson`. If the spot check confirms the pairing logic, a revised crash assignment prototype can use the paired divided rows as a higher-confidence directional subset while leaving unpaired divided rows unresolved.

The unpaired review layer should be used to determine whether the next improvement should target route-stem matching, opposite-carriageway discovery from `roadway_graph_edges.csv`, or source-roadway incompleteness handling.
