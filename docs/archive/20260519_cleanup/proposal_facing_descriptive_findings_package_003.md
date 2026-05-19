# Proposal-Facing Descriptive Findings Package 003

**Status: LEGACY SIGNAL-CENTERED PACKAGE.** This prior findings package remains in place as historical descriptive evidence. It is not the current roadway_graph method.

## Bounded Purpose

Package 003 is the first descriptive findings/readout from the current divided-road, signal-centered analysis tables.

It uses Package 001 and Package 002 outputs only. It does not change production matching, crash classification, enrichment, access recovery, or band-generation logic.

This readout is exploratory and descriptive only. It does not make regression, crash-rate, causal, policy, Appendix F, statewide, or guidance claims.

Generated QA tables:

- `work/output/proposal_descriptive/package_003/tables/current/signal_descriptive_findings_summary.csv`
- `work/output/proposal_descriptive/package_003/tables/current/band_family_crash_access_summary.csv`
- `work/output/proposal_descriptive/package_003/tables/current/signal_outlier_review_queue.csv`
- `work/output/proposal_descriptive/package_003/tables/current/unresolved_case_summary.csv`

Run metadata:

- `work/output/proposal_descriptive/package_003/runs/current/proposal_descriptive_package_003_summary.json`

## Analysis Universe

| Item | Count |
|---|---:|
| total signal-study areas | 163 |
| signals with high-confidence downstream crashes | 112 |
| signals with downstream access points | 28 |
| signals with both downstream crashes and downstream access points | 21 |
| signals with no downstream access points | 135 |
| signals with concentrated downstream access review trigger | 19 |
| unresolved crashes | 1,403 |
| unresolved access positions | 213 |
| remaining access `route_conflict` rows | 210 |
| signals with matched AADT | 158 |
| signals with assigned speed | 163 |

Concentrated downstream access is a review trigger only. In this package it means at least `2` downstream access points, based on the current-slice review threshold.

## Downstream Crash Bands

### Fixed 50-Foot Bands

| Band | Downstream crashes | Share of downstream crashes |
|---|---:|---:|
| `0-50` | 113 | 26.5% |
| `50-100` | 83 | 19.5% |
| `100-150` | 43 | 10.1% |
| `150-200` | 28 | 6.6% |
| `200-250` | 11 | 2.6% |
| `250-300` | 17 | 4.0% |
| `300-350` | 22 | 5.2% |
| `350-400` | 16 | 3.8% |
| `400-450` | 12 | 2.8% |
| `450-500` | 10 | 2.3% |
| `500-550` | 26 | 6.1% |
| `550-600` | 8 | 1.9% |
| `600-650` | 9 | 2.1% |
| `650-700` | 5 | 1.2% |
| `700-750` | 6 | 1.4% |
| `750-800` | 4 | 0.9% |
| `800-850` | 7 | 1.6% |
| `850-900` | 2 | 0.5% |
| `900-950` | 2 | 0.5% |
| `950-1000` | 0 | 0.0% |
| `1000-1050` | 0 | 0.0% |
| `1050-1100` | 2 | 0.5% |
| `1100-1150` | 0 | 0.0% |

### Coarse Fixed Bands

| Band | Downstream crashes | Share of downstream crashes |
|---|---:|---:|
| `0-250` | 278 | 65.3% |
| `250-500` | 77 | 18.1% |
| `500-1000` | 69 | 16.2% |
| `1000plus_within_study_area` | 2 | 0.5% |

### Speed-Time Bands

| Band | Downstream crashes | Share of downstream crashes |
|---|---:|---:|
| `0-3sec` | 258 | 60.6% |
| `3-6sec` | 62 | 14.6% |
| `6-10sec` | 73 | 17.1% |
| `10secplus_within_study_area` | 33 | 7.7% |

These percentages describe the current classified downstream crash universe only. They are not crash rates and do not imply causation.

## Downstream Access Bands

### Coarse Fixed Bands

| Band | Downstream access points | Share of downstream access points |
|---|---:|---:|
| `0-250` | 17 | 24.3% |
| `250-500` | 22 | 31.4% |
| `500-1000` | 29 | 41.4% |
| `1000plus_within_study_area` | 2 | 2.9% |

### Speed-Time Bands

| Band | Downstream access points | Share of downstream access points |
|---|---:|---:|
| `0-3sec` | 11 | 15.7% |
| `3-6sec` | 17 | 24.3% |
| `6-10sec` | 30 | 42.9% |
| `10secplus_within_study_area` | 12 | 17.1% |

Access density is already available at the signal level in `signal_descriptive_findings_summary.csv`.

Current signal-level access-density review context:

- 82 signals have nonzero total access density.
- 28 signals have at least one downstream access point.
- 135 signals have no downstream access point.
- 19 signals meet the concentrated downstream access review trigger of at least `2` downstream access points.

## Signals Worth Future Review

The review queue uses transparent descriptive triggers, not statistical outlier claims.

Review triggers used:

- high downstream crash count: at least `6` high-confidence downstream crashes
- high downstream access count: at least `2` downstream access points
- large unresolved crash count: approximately `20` or more unresolved crashes
- large unresolved access count: approximately `5` or more unresolved access points
- speed-time band spread differs from coarse fixed band spread

### High Downstream Crash Counts

| Study area | Signal label | High-confidence downstream crashes | Downstream access | Unresolved crashes |
|---|---|---:|---:|---:|
| `signal_890` | W. Broad St / Willard Rd. | 13 | 4 | 19 |
| `signal_831` | W. Broad St / Emerywood Pkwy. | 11 | 1 | 24 |
| `signal_833` | W. Broad St / Fountain Square Shopping Center /Westland Shopping Center | 10 | 5 | 21 |
| `signal_83` | E. Hundred Rd / Bermuda Orchard Rd. | 10 | 4 | 10 |
| `signal_1784` | signal_1784 | 10 | 0 | 19 |
| `signal_1009` | Old Ox Road / Ariane Way / Wilder Court | 9 | 0 | 10 |
| `signal_923` | Harry Byrd Highway / Lakeland | 8 | 0 | 20 |
| `signal_1347` | Courthouse Rd / Leavells Rd. | 8 | 0 | 6 |
| `signal_177` | Richmond Highway / Arlington Drive | 7 | 0 | 14 |
| `signal_247` | Leesburg Pike / Baron Cameron / Springvale | 7 | 1 | 10 |

### High Downstream Access Counts

| Study area | Signal label | Downstream access | High-confidence downstream crashes | Unresolved access |
|---|---|---:|---:|---:|
| `signal_832` | W. Broad St / Hungary Spring Rd. | 6 | 7 | 1 |
| `signal_816` | W. Broad St / Wistar Rd. | 5 | 6 | 0 |
| `signal_833` | W. Broad St / Fountain Square Shopping Center /Westland Shopping Center | 5 | 10 | 0 |
| `signal_817` | W. Broad St / Skipwith Rd. | 5 | 4 | 5 |
| `signal_83` | E. Hundred Rd / Bermuda Orchard Rd. | 4 | 10 | 0 |
| `signal_890` | W. Broad St / Willard Rd. | 4 | 13 | 0 |
| `signal_82` | E. Hundred Rd / Rivers Bend Blvd./Ent. to Shopping Center | 4 | 7 | 1 |
| `signal_815` | W. Broad St / Sunnybrook Rd. | 3 | 2 | 0 |
| `signal_281` | Lee Highway / West Street | 3 | 0 | 2 |
| `signal_1315` | Spotswood Trl / Mt. Olivet Church Rd/Resort Rd | 3 | 0 | 1 |

### Both Downstream Crashes And Downstream Access

Highest-priority descriptive review examples:

| Study area | Signal label | Downstream crashes | Downstream access | Unresolved crashes | Unresolved access |
|---|---|---:|---:|---:|---:|
| `signal_833` | W. Broad St / Fountain Square Shopping Center /Westland Shopping Center | 10 | 5 | 21 | 0 |
| `signal_832` | W. Broad St / Hungary Spring Rd. | 7 | 6 | 32 | 1 |
| `signal_831` | W. Broad St / Emerywood Pkwy. | 11 | 1 | 24 | 4 |
| `signal_835` | W. Broad St / Tuckernuck Dr./Ent. to Tuckernuck Plaza | 6 | 3 | 25 | 1 |
| `signal_890` | W. Broad St / Willard Rd. | 13 | 4 | 19 | 0 |
| `signal_83` | E. Hundred Rd / Bermuda Orchard Rd. | 10 | 4 | 10 | 0 |
| `signal_82` | E. Hundred Rd / Rivers Bend Blvd./Ent. to Shopping Center | 7 | 4 | 2 | 1 |
| `signal_816` | W. Broad St / Wistar Rd. | 6 | 5 | 19 | 0 |
| `signal_894` | W. Broad St / Copper Mill Trace /Ent. to Sam's Club | 5 | 2 | 30 | 2 |
| `signal_817` | W. Broad St / Skipwith Rd. | 4 | 5 | 11 | 5 |

These rows identify map-review and table-review priorities. They do not show that access points caused crashes.

## Speed-Time Versus Fixed-Distance Review

Package 003 flags signals where the spread of nonzero bins differs between coarse fixed bands and speed-time bands.

This is useful because speed-time bands can shift a point's descriptive bin when assigned speeds differ. It is not a finding about operational adequacy, stopping sight distance, decision sight distance, or policy distance.

Signals with this flag are included in:

- `work/output/proposal_descriptive/package_003/tables/current/signal_outlier_review_queue.csv`

## Unresolved-Case Limits

Key unresolved buckets:

| Case type | Bucket | Count | Share |
|---|---|---:|---:|
| crash signal-relative classification | `unresolved` | 1,403 of 2,571 | 54.6% |
| access assignment status | `route_conflict` | 210 of 362 | 58.0% |
| access assignment status | `measure_conflict` | 3 of 362 | 0.8% |
| access signal-relative position | `unresolved` | 213 of 362 | 58.8% |

Signals with large unresolved crash counts or unresolved access counts should be treated as interpretation-limited, even if they also have downstream crash or downstream access counts.

Detailed signal-level unresolved review rows are in:

- `work/output/proposal_descriptive/package_003/tables/current/unresolved_case_summary.csv`

## What This Does Not Prove

Package 003 does not support:

- crash-rate claims
- causal access/crash relationship claims
- regression readiness claims
- Appendix F recommendations
- statewide generalization
- expansion beyond divided roads
- rural/suburban/urban policy claims from crash `AREA_TYPE` alone

## Recommended Next Review Step

Use `signal_outlier_review_queue.csv` for manual map and table review of the current divided-road slice.

The most useful next human review is not modeling. It is confirming whether the high-count signals and interpretation-limited signals are geometrically coherent enough to support the next comparison-ready table refinement.
