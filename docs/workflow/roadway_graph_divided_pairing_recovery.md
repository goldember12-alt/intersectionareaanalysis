# Roadway Graph Divided Pairing Recovery

**Status: CURRENT ACTIVE REVIEW PROTOTYPE.** This is a no-crash, candidate-only recovery pass. It does not update the existing accepted divided pairs and does not promote recovered candidates into the default geometric direction model.

## Bounded Question

Can additional divided carriageway pair candidates be identified among currently unpaired `mainline_divided_carriageway` Step 5 rows using roadway role classification and conservative local geometry evidence?

This pass is review-only. It does not read crash data, assign crashes, use crash direction fields, infer direction from crash distributions, revise old signal-centered crash/access modules, or overwrite accepted divided-pair fields.

## Command

Run with the bootstrap-reported interpreter:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.divided_pairing_recovery
```

## Inputs

Under `work/output/roadway_graph/`:

- `tables/current/signal_oriented_roadway_segments_role_enriched.csv`
- `tables/current/roadway_role_classification.csv`
- `tables/current/signal_oriented_roadway_segments_divided_pairing_enriched.csv`
- `tables/current/divided_carriageway_pair_candidates.csv`
- `review/current/divided_pairing_unresolved_reason_summary.csv`
- `review/current/divided_pairing_unresolved_possible_logic_improvements.csv`
- `tables/current/roadway_graph_nodes.csv`
- `tables/current/roadway_graph_edges.csv`

Crash records are not read.

## Method

The prototype only attempts generic divided-pair recovery for rows classified as `mainline_divided_carriageway`.

Rows classified as `ramp_or_connector`, `frontage_or_service_road`, `turn_lane_or_auxiliary`, `one_way_pair_candidate`, `unknown_review`, or `undivided_centerline` are excluded from generic recovery. One-way pair candidates require a separate reviewed one-way couplet method.

Candidate generation uses:

- normalized route stems from route name/common fields with cautious direction-suffix removal
- nearby opposite-anchor clustering within each TRUE reference signal
- local sampled tangent/lateral-offset scoring that ignores endpoint flare zones
- parallelism, projected overlap, lateral separation, length/geometry compatibility, and same-cluster support

Route stem is only a candidate generator. It is not final evidence.

## Outputs

- `work/output/roadway_graph/tables/current/divided_carriageway_pair_candidates_recovery.csv`
- `work/output/roadway_graph/tables/current/signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv`
- `work/output/roadway_graph/review/current/divided_pairing_recovery_summary.csv`
- `work/output/roadway_graph/review/current/divided_pairing_recovered_rows.csv`
- `work/output/roadway_graph/review/current/divided_pairing_still_unresolved_rows.csv`
- `work/output/roadway_graph/review/current/divided_pairing_recovery_problem_rows.csv`
- `work/output/roadway_graph/review/current/divided_pairing_recovery_by_route_type.csv`
- `work/output/roadway_graph/review/current/divided_pairing_recovery_by_reason.csv`
- `work/output/roadway_graph/review/current/divided_pairing_recovery_promotion_recommendation.csv`
- `work/output/roadway_graph/review/geojson/current/divided_pairing_recovery_review.geojson`
- `work/output/roadway_graph/review/geojson/current/divided_pairing_still_unresolved_review.geojson`

## Classification

Recovery rows use:

- `existing_accepted_pair`
- `recovered_high`
- `recovered_medium`
- `recovered_low_review_only`
- `still_unresolved_source_missing`
- `still_unresolved_endpoint_or_one_sided`
- `still_unresolved_ambiguous_geometry`
- `still_unresolved_role_excluded`
- `still_unresolved_unknown`

The current run produced no `recovered_high` or `recovered_medium` rows. That is an intentional conservative outcome: candidate coverage increased only as low-confidence review evidence where geometry was not strong enough for promotion.

## Current Readout

Current recovery run:

- divided rows reviewed: 2,293
- existing accepted pair rows preserved: 810
- existing accepted pairs preserved: 405
- newly recovered high rows: 0
- newly recovered medium rows: 0
- newly recovered high/medium pairs: 0
- low-confidence review-only rows: 44
- low-confidence review-only candidate pairs: 22
- still unresolved rows: 1,439
- true vehicle direction inferred not false: 0
- generic recovery rows with excluded roles: 0
- accepted pair IDs overwritten: 0
- crash data read: `False`

Still unresolved rows:

- `still_unresolved_endpoint_or_one_sided`: 616
- `still_unresolved_unknown`: 787

The recovery summary also carries through the unresolved-diagnosis queues:

- route-stem/scope relaxation candidates: 674
- ambiguous side-score candidates: 306
- source Travelway missing opposite carriageway: 261
- opposite carriageway not in crash-ready TRUE subset: 123
- endpoint/one-sided graph-edge exclusions: 23
- unknown unresolved: 60

## Secondary And Street Route Review

The required route-type split is in:

- `review/current/divided_pairing_recovery_by_route_type.csv`

Secondary Route and Street Route unpaired mainline rows remain mostly unresolved, with only low-confidence review-only candidates produced. No high/medium recovery was promoted from these route groups in this pass.

## Promotion Recommendation

Do not promote this recovery output into the default geometric direction model yet.

The current accepted 405 divided pairs remain the only promoted divided-pairing evidence. The 22 low-confidence recovery candidate pairs should remain review-only. If future threshold changes produce `recovered_high` or `recovered_medium` rows, they should be promoted only after a small QGIS spot check using `divided_pairing_recovery_review.geojson`.

## QA Checks

This run verified:

- no crash data read
- no crash assignment performed
- no crash direction fields used
- no direction inferred from crash distributions
- `true_vehicle_direction_inferred` remains `False`
- accepted divided pair IDs and statuses are preserved
- ramp/frontage/auxiliary/unknown roles are excluded from generic recovery
- recovery output is separate from existing divided-pairing and geometric-direction outputs
