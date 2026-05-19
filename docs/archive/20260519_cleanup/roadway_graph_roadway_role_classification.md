# Roadway Graph Roadway Role Classification

**Status: CURRENT ACTIVE.** This is part of the current roadway_graph / Step 5 graph-first workflow.

## Bounded Question

This prototype classifies each crash-ready Step 5 segment and each referenced roadway graph edge into a source-evidence roadway role before any divided-carriageway pairing recovery.

It uses roadway source fields and roadway graph fields only. It does not read crash data, assign crashes, infer vehicle direction, revise divided carriageway pairing, or overwrite existing accepted divided pairs.

## Command

Run with a working Python 3.11 environment:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.roadway_role_classification
```

Optional arguments:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.roadway_role_classification --normalized-root artifacts/normalized
<bootstrap-reported-python> -m src.active.roadway_graph.roadway_role_classification --output-root work/output/roadway_graph
```

## Inputs

- `artifacts/normalized/roads.parquet`
- `work/output/roadway_graph/tables/current/roadway_graph_edges.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_divided_pairing_enriched.csv`
- `work/output/roadway_graph/review/current/roadway_role_framework_audit/proposed_roadway_role_schema.csv`
- `work/output/roadway_graph/review/current/roadway_role_framework_audit/divided_pairing_crosstab_by_field.csv`
- `work/output/roadway_graph/review/current/roadway_role_framework_audit/divided_unpaired_concentration_top_values.csv`

The audit files define the role framework and review need. The executable classifier uses the roadway graph, Step 5, pairing-enriched, and normalized roadway source fields.

Not used:

- crash records
- crash assignment outputs
- crash direction fields
- access points

## Role Classes

- `mainline_divided_carriageway`
- `undivided_centerline`
- `ramp_or_connector`
- `frontage_or_service_road`
- `turn_lane_or_auxiliary`
- `one_way_pair_candidate`
- `unknown_review`

## Method

The classifier applies the audit-recommended precedence:

1. Detect ramps/connectors from `RTE_RAMP_C`, `RTE_CATEGO`, `RTE_TYPE_N`, and route/name text.
2. Detect frontage/service roads before generic divided classification.
3. Detect turn-lane, auxiliary, reversible, and crossover records.
4. Detect one-way pair candidates from one-way facility values and `RIM_COUPLE`.
5. Classify remaining divided source rows as `mainline_divided_carriageway`.
6. Classify remaining undivided source rows as `undivided_centerline`.
7. Send conflicting or weak source evidence to `unknown_review`.

Existing `divided_pair_id`, `paired_opposite_segment_id`, and `divided_pairing_status` fields are carried forward unchanged. The classifier only appends roadway-role fields.

## Outputs

- `work/output/roadway_graph/tables/current/roadway_role_classification.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_role_enriched.csv`
- `work/output/roadway_graph/review/current/roadway_role_classification_summary.csv`
- `work/output/roadway_graph/review/current/roadway_role_by_pairing_status_summary.csv`
- `work/output/roadway_graph/review/current/unpaired_divided_by_roadway_role_summary.csv`
- `work/output/roadway_graph/review/current/roadway_role_review_examples.csv`
- `work/output/roadway_graph/review/geojson/current/roadway_role_review_examples.geojson`

## Current Readout

Current run:

- 4,305 crash-ready Step 5 segment rows classified
- 4,081 referenced graph edge rows classified
- 2,293 segment rows classified as `mainline_divided_carriageway`
- 1,911 segment rows classified as `undivided_centerline`
- 63 segment rows classified as `ramp_or_connector`
- 10 segment rows classified as `frontage_or_service_road`
- 2 segment rows classified as `turn_lane_or_auxiliary`
- 23 segment rows classified as `one_way_pair_candidate`
- 3 segment rows classified as `unknown_review`
- 810 paired divided rows remain `mainline_divided_carriageway`
- 1,483 unpaired divided rows remain `mainline_divided_carriageway`
- among unpaired divided rows, 657 Secondary Route rows and 109 Street Route rows classify as `mainline_divided_carriageway`
- 0 accepted divided-pair fields were overwritten
- 0 rows infer true vehicle direction
- crash data read: `False`

## Pairing Recovery Recommendation

Eligible for future pairing recovery:

- `mainline_divided_carriageway`
- `one_way_pair_candidate`, but only through a separate reviewed one-way couplet method rather than divided-carriageway assumptions

Not eligible for generic divided-carriageway recovery without explicit manual promotion:

- `ramp_or_connector`
- `frontage_or_service_road`
- `turn_lane_or_auxiliary`
- `undivided_centerline`
- `unknown_review`

## Status

This output is descriptive and exploratory. It is suitable for pre-recovery review and for gating future divided-pairing recovery candidates. It is not a crash-assignment result, a vehicle-direction inference, or a modeling-ready roadway variable.
