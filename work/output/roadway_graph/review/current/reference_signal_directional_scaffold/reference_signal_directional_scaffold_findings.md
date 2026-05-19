# Reference-Signal-Centered Directional Scaffold Findings

**Status:** Read-only candidate/audit output for the roadway_graph / Step 5 directional scaffold.

## Bounded Question

This module builds candidate directional records centered on TRUE reference signals. For every defensible A-to-B scaffold segment, A is the TRUE reference signal and B may be a TRUE signal, non-TRUE signal, non-signalized intersection, endpoint, valid one-sided boundary, or other defensible graph anchor.

It uses roadway, signal, graph, scaffold, geometric-direction, divided-pairing, recovery, role, and endpoint-QA outputs only. It does not read crash data, crash assignment outputs, crash direction fields, or crash distributions.

## Directional Interpretation

- Downstream-of-reference records: 3900
- Upstream-of-reference records: 3900
- Divided physical carriageway records: 810
- Undivided centerline pseudo-direction records: 4024
- 50-foot directional bin records: 304552

Undivided centerlines receive two pseudo-directional records from the same centerline geometry. Bins for both downstream and upstream records are indexed from the TRUE reference signal A.

## Far Anchors

- TRUE-signal far-anchor records: 939
- Non-TRUE signal records: 2251
- Non-signal intersection records: 3806
- Endpoint or one-sided boundary records: 804

The output is reference-signal-centered. If B is also TRUE, B may have separate B-centered records elsewhere in the table.

## Blockers

- divided_physical_direction_not_accepted_or_unpaired: 2966 records
- low_confidence_divided_recovery_review_only: 88 records
- unknown_roadway_role: 6 records

Blocked records are retained for audit visibility and should not be used for later directional crash assignment without a reviewed promotion rule.

## Recommendation

Use only non-review, non-blocked directional records for any later directional crash-assignment prototype. The scaffold is a candidate/audit output, not yet a final crash-assignment-by-direction surface, because unpaired divided rows and low-confidence recovery rows remain blocked or review-only.
