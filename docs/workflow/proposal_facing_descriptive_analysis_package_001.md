# Proposal-Facing Descriptive Analysis Package 001

## Bounded Purpose

This package summarizes what the current divided-road, signal-centered workflow can already say using validated current outputs.

It is descriptive and exploratory only. It does not add matching logic, does not perform additional access recovery, does not make regression or crash-rate claims, and does not propose Appendix F guidance language.

Source baseline:

- current Stage 1 and upstream/downstream outputs regenerated and validated on April 28, 2026
- context enrichment run label: `regenerated-raw-artifact-audit-20260428`
- access route-conflict promotion batch 001 is closed for now

Generated package tables:

- `work/output/proposal_descriptive/tables/current/signal_context_analysis.csv`
- `work/output/proposal_descriptive/tables/current/signal_band_context_analysis.csv`
- `work/output/proposal_descriptive/tables/current/crash_band_assignment.csv`
- `work/output/proposal_descriptive/tables/current/access_band_assignment.csv`

Table contracts:

- `docs/workflow/proposal_facing_descriptive_table_contracts_001.md`

## Core Coverage

| Item | Current count |
|---|---:|
| signal-study areas in signal context table | 163 |
| approach-context rows | 178 |
| approach-context study areas | 164 |
| classified-crash context rows | 2,571 |
| candidate access-point rows in study areas | 362 |
| fixed 50-foot signal-band rows | 2,381 |

One approach-context study area, `signal_1607`, is not present in the signal-level context table. The signal-level proposal package therefore uses the 163-row signal context table as the stable signal baseline.

## Crash Classification

Approach-shaped crash records:

| Classification | Count |
|---|---:|
| `upstream` | 742 |
| `downstream` | 426 |
| `unresolved` | 1,403 |
| total | 2,571 |

Classification status:

| Status | Count |
|---|---:|
| `classified` | 1,168 |
| `unresolved` | 1,403 |

High-confidence descriptive subset:

| Item | Count |
|---|---:|
| high-confidence classified crashes | 1,062 |
| high-confidence upstream crashes | 673 |
| high-confidence downstream crashes | 389 |
| high-confidence signals represented | 132 |

Unresolved crashes remain in `crash_band_assignment.csv`; they are not dropped from the package.

## Access Context

Candidate access points inside current approach-shaped study areas:

| Assignment status | Count |
|---|---:|
| `matched` | 129 |
| `near_signal` | 20 |
| `measure_conflict` | 3 |
| `route_conflict` | 210 |
| total | 362 |

Signal-relative access position:

| Position | Count |
|---|---:|
| `downstream` | 70 |
| `upstream` | 59 |
| `near_signal` | 20 |
| `unresolved` | 213 |

Access route-conflict recovery batch 001 recovered 23 access assignments and is treated as sufficient for this package. The remaining `210` route conflicts stay unresolved unless a later analysis exposes a specific review need.

Signal-level access status:

| Status | Signal count |
|---|---:|
| `no_candidate_points` | 81 |
| `partial` | 69 |
| `matched` | 13 |

Signal-level nonzero access-density summary:

| Statistic | Value |
|---|---:|
| signals with nonzero density | 82 |
| minimum nonzero density per 1,000 ft | 0.45 |
| median nonzero density per 1,000 ft | 5.45 |
| maximum nonzero density per 1,000 ft | 17.78 |

Approach-row nonzero access-density summary:

| Statistic | Value |
|---|---:|
| approach rows with nonzero density | 38 |
| minimum nonzero density per 1,000 ft | 1.47 |
| median nonzero density per 1,000 ft | 14.81 |
| maximum nonzero density per 1,000 ft | 72.84 |

## AADT And Speed Context

AADT coverage by approach row:

| AADT status | Approach-row count |
|---|---:|
| `matched` | 172 |
| `no_candidate` | 6 |

AADT signal coverage:

| Item | Count |
|---|---:|
| signal-study areas with at least one matched AADT row | 158 |
| signal-study areas in signal context table | 163 |

Selected AADT year:

| Year | Approach-row count |
|---|---:|
| 2024 | 172 |
| unavailable | 6 |

Selected AADT quality codes are reported but not ranked because the workflow does not document a trustworthy quality ordering:

| Quality | Approach-row count |
|---|---:|
| `A` | 6 |
| `F` | 97 |
| `G` | 69 |
| unavailable | 6 |

Signal-level weighted AADT summary:

| Statistic | Value |
|---|---:|
| signals with weighted AADT | 158 |
| minimum | 8,990 |
| median | 27,376.5 |
| maximum | 63,349 |

Assigned speed coverage:

| Speed mph | Signal count |
|---|---:|
| 25 | 9 |
| 30 | 5 |
| 35 | 56 |
| 40 | 30 |
| 45 | 46 |
| 50 | 2 |
| 55 | 15 |

Speed source:

| Source | Signal count |
|---|---:|
| `raw_speed_join` | 135 |
| `default_speed` | 28 |

## Median And Facility Context

Current approach-row facility context:

| Facility value | Approach-row count |
|---|---:|
| `4-Two-Way Divided` | 178 |

Current approach-row median context:

| Median value | Approach-row count |
|---|---:|
| `2-Curbed Barrier or mountable curbs with a minimum height of 4 inches (4,7)` | 125 |
| `4-Grass unprotected Median exists with a width of 4 feet or more (2)` | 52 |
| `6-Jersey Barrier or Guard Rail creates a positive barrier(8)` | 1 |

These fields are descriptive roadway context. They have not yet been converted into modeling variables or policy classes.

## Fixed 50-Foot Downstream Bands

Current band family:

- `fixed_50ft_from_signal_within_study_area`

Coverage:

| Item | Count |
|---|---:|
| signal-band rows | 2,381 |
| signals with band rows | 163 |
| downstream access points assigned to bands | 70 |
| downstream crashes assigned to bands | 426 |

Band totals:

| Band | Downstream access count | Downstream crash count |
|---|---:|---:|
| `0-50` | 0 | 113 |
| `50-100` | 0 | 83 |
| `100-150` | 6 | 43 |
| `150-200` | 7 | 28 |
| `200-250` | 4 | 11 |
| `250-300` | 5 | 17 |
| `300-350` | 4 | 22 |
| `350-400` | 2 | 16 |
| `400-450` | 7 | 12 |
| `450-500` | 4 | 10 |
| `500-550` | 8 | 26 |
| `550-600` | 4 | 8 |
| `600-650` | 6 | 9 |
| `650-700` | 3 | 5 |
| `700-750` | 1 | 6 |
| `750-800` | 3 | 4 |
| `800-850` | 2 | 7 |
| `850-900` | 0 | 2 |
| `900-950` | 1 | 2 |
| `950-1000` | 1 | 0 |
| `1000-1050` | 1 | 0 |
| `1050-1100` | 1 | 2 |
| `1100-1150` | 0 | 0 |

These bands are descriptive bins inside the current approach-shaped study area. They do not define limiting values, desirable values, next-signal boundaries, or policy distances.

## Table Readiness

Stable descriptive baselines:

- `work/output/context_enrichment/tables/current/signal_study_area_context_enriched.csv`
- `work/output/context_enrichment/tables/current/approach_row_context_enriched.csv`
- `work/output/context_enrichment/tables/current/classified_crash_context_enriched.csv`
- `work/output/context_enrichment/tables/current/access_assignment_points.csv`
- `work/output/context_enrichment/tables/current/signal_downstream_distance_band_summary.csv`

Proposal-facing package tables generated from those baselines:

- `signal_context_analysis.csv`: stable descriptive signal table
- `signal_band_context_analysis.csv`: stable fixed-band descriptive table
- `crash_band_assignment.csv`: analysis-ready crash assignment table that keeps unresolved rows
- `access_band_assignment.csv`: analysis-ready access assignment table that keeps route conflicts and measure conflicts

Analysis-ready but not model-ready:

- fixed 50-foot band crash/access counts
- signal-level AADT, access, speed, and median/facility context
- crash-level signal-relative classifications with unresolved cases retained
- access-level signal-relative assignments with route conflicts retained

Requires future methodology work:

- proposal-derived limiting/desirable/speed-based band families
- denominator and exposure definitions for any rate work
- roadway-level rural/suburban/urban source
- validated access type and land-use/trip-generation fields
- model-ready dependent and independent variable definitions

## Not Yet

This package does not support:

- regression
- crash-rate claims
- Appendix F guidance language
- spreadsheet calculator development
- expansion beyond divided roads
- rural/suburban/urban policy claims from crash `AREA_TYPE` alone
- additional access recovery beyond promotion batch 001

## Next Bounded Deliverables

Recommended next package after this one:

1. Define expanded distance-band families tied to proposal concepts.
2. Refine the comparison-ready table contracts after those band families exist.
3. Decide on a roadway-level geographic-context source before using rural/suburban/urban as a policy or modeling variable.

