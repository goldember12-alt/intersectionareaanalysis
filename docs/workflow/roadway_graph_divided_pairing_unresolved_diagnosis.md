# Roadway Graph Divided Pairing Unresolved Diagnosis

**Status: CURRENT ACTIVE.** This is a current roadway_graph result/readout summary retained under workflow for this pass.

## Bounded Question

This diagnosis asks why 1,447 of 2,257 divided Step 5 crash-ready roadway-segment rows remain unpaired in the no-crash divided carriageway pairing module.

It does not read crash records, assign crashes, use crash direction fields, infer direction from crash distributions, revise crash assignment, or force additional pairings.

The bounded method question is:

- within the TRUE-reference-signal Step 5 roadway graph scope, which unpaired divided rows are expected methodological exclusions, which appear to reflect source/Travelway geometry limits, and which are plausible future pairing-logic improvements?

## Inputs Reviewed

The diagnosis used only roadway graph, Step 5, and pairing outputs under `work/output/roadway_graph/`:

- `tables/current/signal_oriented_roadway_segments_crash_ready.csv`
- `tables/current/signal_oriented_roadway_segments_divided_pairing_enriched.csv`
- `tables/current/divided_carriageway_pair_candidates.csv`
- `tables/current/roadway_graph_edges.csv`
- `tables/current/signal_adjacent_edges.csv`
- `tables/current/divided_edge_directional_candidates.csv`
- `review/current/divided_carriageway_pairing_summary.csv`
- `review/current/divided_carriageway_pairing_problem_rows.csv`
- `review/current/divided_carriageway_unpaired_rows.csv`
- `review/current/divided_carriageway_pairing_examples.csv`
- `tables/current/signal_step5_eligibility.csv`
- `review/current/step5_first_prototype_input_signals.csv`

Crash data read: `False`.

## Current Pairing Result

The pairing module result is internally consistent:

- divided rows reviewed: 2,257
- paired divided rows: 810
- accepted divided carriageway pairs: 405
- high-confidence pairs: 335
- medium-confidence pairs: 70
- unpaired divided rows: 1,447
- pairs with both `A_to_B` and `B_to_A` candidates: 405
- `true_vehicle_direction_inferred != false`: 0

The 65% unresolved rate is not a failure by default. The current method intentionally pairs only rows that have a clear opposite physical carriageway under a same TRUE reference signal, compatible route-stem grouping, similar segment bearing, distinct source components, and a right/left bracketing geometry. Rows that do not satisfy that evidence remain unresolved because they are not yet safe for upstream/downstream or approaching/leaving interpretation.

## Reason Summary

The broad module label `no_clear_opposite_carriageway_pair_found` was split into conservative diagnostic categories:

| Reason | Rows | Share of unpaired | Interpretation |
|---|---:|---:|---|
| `pair_search_threshold_too_strict` | 674 | 46.58% | A same-reference signal candidate appears only if route-stem grouping is relaxed. This is a possible improvement queue, not an accepted pair queue. |
| `opposite_carriageway_exists_but_side_score_ambiguous` | 306 | 21.15% | Similar-bearing, distinct-component geometry exists, but the side/bracketing score is near-center or otherwise ambiguous. |
| `source_travelway_missing_opposite_carriageway` | 261 | 18.04% | The row ends at a non-signal/endpoint boundary and no clear same-scope opposite carriageway was found. |
| `opposite_carriageway_not_in_crash_ready_subset` | 123 | 8.50% | The opposite signal boundary is valid but not TRUE Step 5 under the current reference scope. |
| `unknown_unresolved` | 60 | 4.15% | No conservative explanation was strong enough from the available non-crash fields. |
| `endpoint_or_one_sided_graph_edge` | 23 | 1.59% | The segment terminates at a graph endpoint/dead end and should not be forced into a reciprocal pair. |

The classification is diagnostic, not authoritative truth. It uses available roadway graph geometry and Step 5 fields. It does not prove that a broader candidate is a correct opposite carriageway.

## Scope and Methodology Answers

How many are outside TRUE-only/reference-signal-centered scope?

- 632 unpaired rows have `missing_reciprocal_reason = opposite_signal_not_true_reference_but_valid_boundary`.
- 618 have `missing_reciprocal_reason = opposite_anchor_is_non_signal_or_endpoint_boundary`.
- In the best-reason classification, 123 rows are cleanly assigned to `opposite_carriageway_not_in_crash_ready_subset`; many other rows with non-TRUE or non-signal boundaries also have a nearby possible geometry candidate and were placed in the possible-improvement queues instead.

How many are endpoint or one-sided graph edges?

- 63 unpaired rows have `opposite_anchor_type = road_endpoint_dead_end`.
- 23 are conservatively classified as `endpoint_or_one_sided_graph_edge` after giving precedence to possible nearby candidates. These are acceptable methodological exclusions unless source review finds missing opposite geometry.

How many appear to have a possible opposite carriageway nearby but fail grouping or pairing?

- 674 rows have a same-reference-signal candidate only when route-stem grouping is relaxed.
- 306 rows have a same-reference/same-route-stem candidate with similar bearing and distinct component geometry, but side/bracketing is ambiguous.
- Together, 980 rows are plausible review queues for future logic work. They are not accepted pair recoveries yet.

How many appear to be missing opposite carriageway geometry in Travelway?

- 261 rows are classified as `source_travelway_missing_opposite_carriageway`.
- These are mostly non-signalized-boundary rows where the current crash-ready subset does not expose a clear opposite candidate.

How many may be divided-classification false positives?

- 0 were classified as `divided_classification_questionable` in this conservative pass.
- That does not prove there are no source classification issues; it only means the available facility/median fields did not produce a stronger false-positive category than the other reasons.

## Pairing Logic Findings

Unpaired rows are concentrated by route, but not only on one corridor. The largest route-common counts include:

- `US-60E`: 22 unpaired, 25 paired
- `US-1N`: 21 unpaired, 24 paired
- `US-60W`: 20 unpaired, 25 paired
- `US-460E`: 20 unpaired, 25 paired
- `US-17N`: 18 unpaired, 0 paired
- `VA-10E`: 16 unpaired, 2 paired
- `Big Bethel RD (PR - City of Hampton)`: 15 unpaired, 0 paired

Unpaired rows are generally longer than paired rows:

- paired average length: 875.96 ft
- unpaired average length: 1,568.99 ft
- the `2500_plus` band has 243 unpaired rows versus 24 paired rows

That pattern is consistent with longer Travelway fragments spanning endpoints, non-signalized anchors, or route/family changes that are harder to pair with the strict same-reference rule.

Unpaired rows are concentrated around non-standard opposite anchors:

- `signalized_intersection`: 829 unpaired rows
- `non_signalized_roadway_intersection`: 555 unpaired rows
- `road_endpoint_dead_end`: 63 unpaired rows

`segment_family_id` is not the main active blocker in the current pairing module. The current module already pairs across different segment families when same reference signal, route stem, bearing, component, and bracketing checks pass. The larger remaining blocker is not exact segment family grouping; it is the combination of route-stem scope, ambiguous side-score geometry, one-to-one candidate assignment, and source geometry completeness.

Broader pairing across same `reference_signal_id` plus route/route-family plus similar bearing might recover a subset, especially the 674 `pair_search_threshold_too_strict` rows. However, the current diagnostic finds candidates by relaxing route-stem grouping, which can also introduce cross-street, ramp, frontage, or service-road false positives. This should be tested only as a bounded QGIS/source-data review queue.

Using a road centerline or reference axis would likely help with the 306 side-score ambiguous rows. It could distinguish true opposite carriageways from geometry that is simply close to, overlapping, or not bracketing the inferred reference line. Relaxing search radius or side-score thresholds without that support would raise false-pairing risk.

## Acceptable Exclusions vs Future Improvements

Acceptable methodological exclusions:

- `opposite_carriageway_not_in_crash_ready_subset`
- `endpoint_or_one_sided_graph_edge`
- auxiliary/ramp/frontage cases if confirmed in manual review

Source or scope limitations:

- `source_travelway_missing_opposite_carriageway`
- short or fragmented geometry where present
- future confirmed divided-classification false positives

Possible pairing-logic improvements:

- route-stem relaxation only within a strict same-reference, similar-bearing, reviewed route-family rule
- a centerline/reference-axis method for ambiguous side-score candidates
- source Travelway review for non-signalized-boundary rows before assuming code can recover them
- non-greedy or conflict-aware candidate selection only after mapped review confirms many-to-one cases are real opposite-carriageway alternatives

## Manual Review Sample

The manual review sample was written to:

- `review/current/divided_pairing_unresolved_manual_review_sample.csv`
- `review/geojson/current/divided_pairing_unresolved_manual_review_sample.geojson`

It contains:

- 10 likely acceptable endpoint/one-sided rows
- 10 likely missing Travelway opposite-carriageway rows
- 10 likely pairable-but-not-grouped rows
- 10 ambiguous side-score rows
- 0 possible divided-classification false positives, because no conservative false-positive group was available

The sample includes review group, oriented segment, segment family, reference signal, anchors, route fields, component/facility/median context, length, unresolved reason, possible candidate ID where available, side score where available, and blank manual-review fields.

## Output Artifacts

New diagnosis outputs:

- `review/current/divided_pairing_unresolved_reason_summary.csv`
- `review/current/divided_pairing_unresolved_by_anchor_type.csv`
- `review/current/divided_pairing_unresolved_by_route.csv`
- `review/current/divided_pairing_unresolved_by_length_band.csv`
- `review/current/divided_pairing_unresolved_by_reference_signal_status.csv`
- `review/current/divided_pairing_unresolved_possible_logic_improvements.csv`
- `review/current/divided_pairing_unresolved_manual_review_sample.csv`
- `review/geojson/current/divided_pairing_unresolved_manual_review_sample.geojson`

The reproducible local diagnostic helper is:

- `scripts/diagnose_divided_pairing_unresolved.ps1`

## Recommendation

Do not revise crash assignment yet and do not force pairings.

Keep the current pairing logic as the accepted high-confidence/medium-confidence subset and document the 65% unresolved rate as expected under the current TRUE-only, reference-signal-centered, no-crash methodology.

The next step should be manual/source-data review before expanding paired divided rows. If review confirms the candidate queues, revise pairing logic only for clearly defined subsets:

- route-family relaxation for reviewed same-reference corridors
- centerline/reference-axis support for ambiguous side-score cases
- source Travelway repair or exclusion notes for missing-opposite-geometry cases

Until then, all 1,447 rows remain unresolved for upstream/downstream interpretation.
