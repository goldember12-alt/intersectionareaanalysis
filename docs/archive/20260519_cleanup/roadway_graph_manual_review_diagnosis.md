# Roadway Graph Manual Review Diagnosis

**Status: CURRENT ACTIVE.** This is a current roadway_graph result/readout summary retained under workflow for this pass.

## Bounded Question

This memo diagnoses the 30-row manual QGIS review of the roadway graph prototype as a pre-Step 5 data-sufficiency and termination-rule check.

It does not read crash data, assign crashes, infer true vehicle direction, implement Step 5 oriented segments, or modify the older signal-centered crash/access modules.

Manual review source:

- `work/output/roadway_graph/review/current/manual_graph_review_results.csv`

Derived diagnosis outputs:

- `work/output/roadway_graph/review/current/manual_review_diagnosis_summary.csv`
- `work/output/roadway_graph/review/current/manual_review_signal_classification.csv`
- `work/output/roadway_graph/review/current/source_roadway_incomplete_examples.csv`
- `work/output/roadway_graph/review/current/edge_termination_issue_examples.csv`
- `work/output/roadway_graph/review/current/step5_candidate_examples_from_manual_review.csv`

## Manual Review Readout

The review covered 30 signals:

| Finding | Count |
| --- | ---: |
| Reviewed signals | 30 |
| `ready_for_step5 = TRUE` | 6 |
| `ready_for_step5 = FALSE` | 24 |
| Reviewed failures with missing Travelway/base roadway legs | 24 |
| Reviewed failures with `signal_location_correct = FALSE` | 7 |
| Reviewed failures with broader signal-location or signal-inventory concern | 9 |
| Reviewed failures with `possible_topology_fragmentation = TRUE` | 24 |
| Confirmed graph-only topology failures isolated from source incompleteness | 0 |
| Passing or near-passing rows with edge termination issues | 4 |
| Over-connected rows | 1 |
| Possible grade-separation rows | 0 |
| Manual Step 5 candidates before termination gating | 6 |
| Clean candidate after derived diagnosis flags | 1 |

The dominant result is source roadway sufficiency, not graph search failure. All 24 reviewed failures are under-connected and cross-street-missing cases where the manual notes or flags identify missing Travelway/base roadway legs. These cases should be excluded from Step 5 by default or held for manual/source review. The graph should not invent missing roadway geometry.

## Diagnosis Categories

### `source_roadway_incomplete`

Count in reviewed failures: 24.

These are signals where the Travelway/base roadway source is missing one or more important roadway legs near the signal. This includes zero-edge, one-edge, two-edge, and one three-to-four-edge review case. In this batch, source incompleteness is the primary diagnosis for every manual failure.

Action:

- exclude from Step 5 by default
- allow manual promotion only when a reviewer documents that the missing leg is not needed for the bounded analysis
- do not fabricate roadway legs from signal location, access points, or crash evidence
- resolve only by adding or validating a better roadway source, or by explicitly narrowing the analysis question

### `signal_location_questionable`

Strict count in reviewed failures: 7 with `signal_location_correct = FALSE`.

Broader count in reviewed failures: 9 when notes about multiple plausible signal locations or one signal representing multiple nearby intersections are included.

One additional manual-ready row has a signal-inventory question: signal 916 appears to need a signal anchor at Sunrise Valley Drive and Monroe Street, but that signal point does not appear to exist in the source. That is not the same as a bad reviewed signal location, but it still affects graph termination and Step 5 readiness.

Action:

- hold strict bad-location rows for signal-source correction or manual exclusion
- distinguish bad reviewed signal location from missing neighboring signal inventory
- do not use graph logic to compensate for a materially misplaced signal point

### `topology_fragmentation_or_unsplit_intersection`

Manual flag count in reviewed failures: 24.

The topology flag overlaps with the source-roadway-incomplete failures in this sample. The manual notes usually identify missing Travelway road legs, so these rows do not prove that graph logic alone can repair the issue. At least one row also mentions possible source representation or unsplit/centerline behavior, but the reviewed failure still includes missing source geometry.

Action:

- keep topology fragmentation as a review flag
- add explicit graph diagnostics for unsplit intersections and near-miss endpoints
- do not treat topology repair as sufficient when a roadway leg is absent from the source

### `edge_termination_too_far`

Count among passing or near-passing rows: 4.

Manual-ready rows 426, 643, 134, and 161 show edge termination concerns. The common issue is that a highlighted edge continues past a nearer non-signalized roadway intersection, or may be using a distant access point when a roadway-network anchor should come first.

Action:

- solve with graph termination rules before Step 5
- treat non-signalized roadway intersections as valid termini
- flag any segment that crosses an intermediate intersection before ending at a farther signal, access point, endpoint, or cutoff

### `over_connected`

Count: 1.

Signal 756 is manually over-connected and under-connected. The note says it should only have two edges, while Travelway is missing an entrance into Sterling Town Center. Because source incompleteness is also present, this row should not be promoted to Step 5 until the intended leg set is reviewed.

### `grade_separation_possible`

Count: 0.

No reviewed rows were marked as possible grade-separation cases. The category should remain in future review because interchanges, ramps, and separated crossings are high-risk graph contexts.

### `usable_for_step5_candidate`

Manual count: 6.

These are the six rows marked `ready_for_step5 = TRUE` in the manual review. The derived diagnosis keeps them as manual candidates but applies additional Step 5 gating:

- four require edge termination rule fixes or review
- one requires signal-location or neighboring signal-inventory review
- one has no derived diagnosis flag in this sample

Manual `ready_for_step5` should therefore be interpreted as a base candidate signal, not final Step 5 eligibility.

## What Graph Logic Can Solve

Graph logic can address:

- termination at the first valid roadway-network anchor
- detection of intermediate non-signalized intersections crossed by an edge
- near-miss endpoint snapping where source lines should meet but are slightly disconnected
- duplicate or excessive adjacent edges around the same physical leg
- explicit review flags for over-connected, under-connected, unsplit, or ambiguous adjacency
- access fallback only when no better roadway-network anchor exists
- maximum-cutoff review-only segments when no valid anchor is found

Graph logic cannot truthfully solve:

- missing Travelway road legs
- materially misplaced signal points
- missing neighboring signal inventory, except by flagging it
- grade separation without sufficient roadway/elevation/source evidence
- true vehicle direction or upstream/downstream orientation in this pre-Step 5 phase

## Termination Rule

Each graph edge or leg should terminate at the first valid anchor along the roadway path:

1. another signalized intersection
2. a non-signalized roadway intersection
3. a dead end or roadway endpoint
4. an access point only if sufficiently far from the signal and no better roadway-network anchor exists
5. a maximum cutoff, marked review-only, if no valid anchor is found

Access points are fallback/support termini, not primary graph termini.

Non-signalized intersections are valid termini. A segment should not run through an intermediate roadway intersection to a farther signal, access point, endpoint, or cutoff without setting `intermediate_intersection_crossed_flag = TRUE` and requiring review.

## Step 5 Eligibility Recommendation

Before Step 5 oriented segments are implemented, apply these eligibility rules:

1. Exclude zero-edge and one-edge signals by default unless manually promoted.
2. Treat two-edge signals as suspect unless review confirms the intersection is truly two-legged or the bounded project only needs one roadway.
3. Require `source_roadway_complete_enough = TRUE`.
4. Require the observed adjacent leg count to be compatible with the expected intersection form.
5. Require no unresolved missing-leg notes.
6. Require signal location to be acceptable, or manually corrected/promoted.
7. Require edge termination at the first valid anchor.
8. Require no intermediate roadway intersection crossing unless explicitly allowed and documented.
9. Require access termini to be fallback/support only.
10. Keep maximum-cutoff segments review-only.

Zero-edge and one-edge signals should be excluded by default from Step 5 because this review shows they are strong indicators of missing roadway geometry or insufficient signal/source alignment. Manual promotion should be possible, but only with a documented reason.

Two-edge signals should be treated as suspect. Some may be true two-legged intersections or valid for a one-roadway bounded question, but this review shows the two-edge bucket can also represent missing cross streets or missing access/roadway legs.

## Proposed Signal Eligibility Schema

Proposed fields:

- `signal_id`
- `source_roadway_complete_enough`
- `usable_for_step5`
- `step5_exclusion_reason`
- `manual_promotion_allowed`
- `manual_promotion_reason`
- `requires_manual_review`
- `signal_location_status`
- `signal_location_notes`
- `adjacent_leg_count_expected_from_review`
- `adjacent_leg_count_observed`
- `adjacent_leg_count_status`
- `missing_leg_notes`
- `source_roadway_incomplete`
- `signal_location_questionable`
- `topology_fragmentation_or_unsplit_intersection`
- `over_connected`
- `grade_separation_possible`

Recommended values for `step5_exclusion_reason` include:

- `source_roadway_incomplete`
- `signal_location_questionable`
- `adjacent_leg_count_insufficient`
- `two_edge_suspect`
- `topology_fragmentation_or_unsplit_intersection`
- `over_connected`
- `grade_separation_possible`
- `edge_termination_unresolved`
- `manual_review_required`

## Proposed Edge Termination Schema

Proposed fields:

- `edge_id`
- `signal_id`
- `from_anchor_type`
- `from_anchor_id`
- `edge_termination_status`
- `edge_termination_anchor_type`
- `edge_termination_anchor_id`
- `edge_termination_reason`
- `termination_distance_ft`
- `intermediate_intersection_crossed_flag`
- `intermediate_intersection_anchor_id`
- `access_used_as_fallback_flag`
- `max_cutoff_used_flag`
- `requires_manual_review`
- `termination_notes`

Recommended values for `edge_termination_status` include:

- `valid_signal_anchor`
- `valid_non_signalized_intersection_anchor`
- `valid_roadway_endpoint_anchor`
- `access_fallback_anchor`
- `max_cutoff_review_only`
- `too_far_crossed_intermediate_intersection`
- `missing_signal_anchor_possible`
- `unresolved`

## Revised Graph Output Fields Needed Before Step 5

Signal-level outputs should add:

- `source_roadway_complete_enough`
- `usable_for_step5`
- `step5_exclusion_reason`
- `manual_promotion_allowed`
- `adjacent_leg_count_expected_from_review`
- `adjacent_leg_count_observed`
- `missing_leg_notes`
- `requires_manual_review`

Edge-level outputs should add:

- `edge_termination_status`
- `edge_termination_anchor_type`
- `edge_termination_anchor_id`
- `edge_termination_reason`
- `intermediate_intersection_crossed_flag`
- `requires_manual_review`

These fields should be added before Step 5 so oriented segments are created only from reviewed, source-sufficient graph evidence.

## Proposal Alignment

This diagnosis supports the proposal-facing graph foundation needed before downstream crash/access/AADT/speed/median summaries. It remains pre-crash, pre-directional, and descriptive. It does not create modeling-ready outputs. It improves the roadway scaffold by distinguishing graph-logic issues from source-data sufficiency failures, which is necessary before downstream distance bands or comparison-ready analysis tables can be trusted.
