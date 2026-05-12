# Package 003 Signal Outlier Map Review Batch A Guide

## Bounded Purpose

Batch A is a focused map-review packet for Package 003 signals flagged with both:

- high-confidence downstream crashes
- downstream access points

This is a review packet only. It does not change matching, crash classification, enrichment, access recovery, band generation, or production logic. It does not support modeling, causal, policy, Appendix F, or guidance claims.

## Packet Files

Primary CSV packet:

- `work/output/proposal_descriptive/package_003/review/current/signal_outlier_map_review_batch_A.csv`

Summary metadata:

- `work/output/proposal_descriptive/package_003/review/current/signal_outlier_map_review_batch_A_summary.json`

GeoJSON review layers:

- `work/output/proposal_descriptive/package_003/review/current/batch_A_signals.geojson`
- `work/output/proposal_descriptive/package_003/review/current/batch_A_study_areas.geojson`
- `work/output/proposal_descriptive/package_003/review/current/batch_A_approach_rows.geojson`
- `work/output/proposal_descriptive/package_003/review/current/batch_A_downstream_high_confidence_crashes.geojson`
- `work/output/proposal_descriptive/package_003/review/current/batch_A_downstream_access_points.geojson`
- `work/output/proposal_descriptive/package_003/review/current/batch_A_unresolved_admitted_crashes.geojson`
- `work/output/proposal_descriptive/package_003/review/current/batch_A_unresolved_or_conflict_access_points.geojson`

Batch A contains:

- 18 signals
- 111 high-confidence downstream crash points
- 54 downstream access points
- 246 unresolved admitted crash points
- 23 unresolved or conflict access points

## Selection Rule

Batch A uses rows from:

- `work/output/proposal_descriptive/package_003/tables/current/signal_outlier_review_queue.csv`

Selection rule:

- `ReviewReasons` contains `both_downstream_crashes_and_downstream_access_present`

Rows are sorted by:

- review reason count
- high-confidence downstream crash count
- downstream access count
- unresolved crash count
- unresolved access count

## Recommended QGIS Load Order

1. `batch_A_study_areas.geojson`
2. `batch_A_approach_rows.geojson`
3. `batch_A_signals.geojson`
4. `batch_A_downstream_high_confidence_crashes.geojson`
5. `batch_A_downstream_access_points.geojson`
6. `batch_A_unresolved_admitted_crashes.geojson`
7. `batch_A_unresolved_or_conflict_access_points.geojson`

Use `BatchRank`, `StudyAreaID`, and `SignalLabel` to filter one signal at a time.

## What To Review

For each signal, check:

- whether the downstream crash pattern appears on the expected downstream side of the directed approach
- whether downstream access points appear on the relevant road/travelway rather than a frontage road, cross street, connector, or wrong carriageway
- whether the approach-row geometry and study-area polygon fit the signal context
- whether unresolved crashes or unresolved access points are large enough to limit interpretation
- whether the signal is suitable as a descriptive example
- whether the signal is only a possible future model-candidate row after more methodology work

## Manual Decision Fields

Fill these fields in `signal_outlier_map_review_batch_A.csv` during review:

| Field | Suggested values | Meaning |
|---|---|---|
| `ReviewStatus` | `valid`, `questionable`, `unsuitable`, `needs_followup` | Overall map-review decision |
| `CrashPatternLooksValid` | `yes`, `no`, `uncertain` | Downstream crash locations appear plausible |
| `AccessPatternLooksValid` | `yes`, `no`, `uncertain` | Downstream access locations appear plausible |
| `DownstreamSideLooksValid` | `yes`, `no`, `uncertain` | Directional downstream side appears coherent |
| `GeometryConcern` | free text or blank | Study area, approach row, projection, or signal geometry concern |
| `AccessConcern` | free text or blank | Access route, frontage, connector, wrong-carriageway, or unresolved-access concern |
| `CrashClassificationConcern` | free text or blank | Crash attachment, projection, high-confidence status, or downstream classification concern |
| `UnresolvedConcern` | free text or blank | Whether unresolved rows materially limit interpretation |
| `UseInDescriptiveExamples` | `yes`, `no`, `maybe` | Whether this signal is suitable for a descriptive report example |
| `UseInFutureModelingCandidate` | `yes`, `no`, `maybe` | Whether this signal may be suitable later after model-readiness work |
| `ReviewerNotes` | free text | Reviewer explanation |

## Reading The Existing Fields

Important packet fields:

- `BatchRank`: review order within Batch A
- `SignalID`: same as `StudyAreaID`
- `ReviewReason`: descriptive triggers from Package 003
- `DownstreamCrashCount`: high-confidence downstream crash count
- `DownstreamAccessCount`: downstream access count
- `UnresolvedCrashCount`: unresolved crash count for the signal
- `UnresolvedAccessCount`: unresolved access count for the signal
- `AADT`: current weighted AADT summary where available
- `AssignedSpeedMph`: speed used by the current upstream/downstream prototype
- `StrongestBandFamilyPattern`: strongest crash/access band by family
- `CrashAccessOverlapFlags`: whether crash and access counts appear in the same band family bins

These fields are review aids. They are not statistical tests.

## Not Supported By This Review

This packet does not support:

- crash-rate claims
- causal access/crash relationship claims
- regression readiness claims
- Appendix F recommendations
- statewide generalization
- expansion beyond divided roads
- new access recovery decisions
- production logic changes

## Completion Standard For Manual Review

After manual review, each Batch A row should have:

- `ReviewStatus`
- `CrashPatternLooksValid`
- `AccessPatternLooksValid`
- `DownstreamSideLooksValid`
- notes for any geometry, access, crash-classification, or unresolved-case concerns
- a `yes`, `no`, or `maybe` decision for descriptive-example use
- a `yes`, `no`, or `maybe` decision for future model-candidate use

