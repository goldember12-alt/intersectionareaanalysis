# Proposal-Facing Descriptive Analysis Package 002

**Status: LEGACY SIGNAL-CENTERED PACKAGE.** This prior package remains in place as historical descriptive evidence. It is not the current roadway_graph method.

## Bounded Purpose

Package 002 expands downstream distance-band summaries from the frozen Package 001 descriptive baseline.

It does not modify matching, enrichment, crash classification, access recovery, production logic, or Package 001 outputs. It re-bins existing downstream crash and access distances into additional descriptive band families.

Band-family design:

- `docs/workflow/proposal_facing_distance_band_family_design_002.md`

Generated Package 002 tables:

- `work/output/proposal_descriptive/package_002/tables/current/signal_band_context_analysis_expanded.csv`
- `work/output/proposal_descriptive/package_002/tables/current/crash_band_assignment_expanded.csv`
- `work/output/proposal_descriptive/package_002/tables/current/access_band_assignment_expanded.csv`

Run metadata:

- `work/output/proposal_descriptive/package_002/runs/current/proposal_descriptive_package_002_summary.json`

## What Package 002 Adds

Package 001 provided fixed 50-foot downstream bins only.

Package 002 preserves that family and adds:

- coarse fixed bands: `0-250`, `250-500`, `500-1000`, and `1000plus_within_study_area`
- assigned-speed travel-time bands: `0-3sec`, `3-6sec`, `6-10sec`, and `10secplus_within_study_area`
- explicit placeholder design for future limiting/desirable/policy bands without generating unsupported rows

All three implemented families preserve the same downstream event universe:

| Band family | Downstream crashes | Downstream access points |
|---|---:|---:|
| `fixed_50ft_from_signal_within_study_area` | 426 | 70 |
| `fixed_coarse_0_250_500_1000ft_with_overflow` | 426 | 70 |
| `speed_time_3_6_10sec_at_assigned_speed_with_overflow` | 426 | 70 |

## Output Row Counts

| Table | Rows | Meaning |
|---|---:|---|
| `signal_band_context_analysis_expanded.csv` | 3,685 | one row per signal and band for each implemented band family |
| `crash_band_assignment_expanded.csv` | 7,713 | one row per crash per implemented band family |
| `access_band_assignment_expanded.csv` | 1,086 | one row per access-point candidate per implemented band family |

The crash and access expanded tables intentionally repeat rows by band family so unresolved and non-downstream records remain explicit for each family.

## Coarse Fixed Band Summary

| Coarse band | Downstream crashes | Downstream access points |
|---|---:|---:|
| `0-250` | 278 | 17 |
| `250-500` | 77 | 22 |
| `500-1000` | 69 | 29 |
| `1000plus_within_study_area` | 2 | 2 |

Interpretation:

- the coarse fixed family makes Package 001's detailed 50-foot pattern easier to compare across signals
- the overflow band prevents downstream points beyond 1,000 feet from disappearing
- these are descriptive bins, not proposed design thresholds

## Assigned-Speed Travel-Time Band Summary

| Speed-time band | Downstream crashes | Downstream access points |
|---|---:|---:|
| `0-3sec` | 258 | 11 |
| `3-6sec` | 62 | 17 |
| `6-10sec` | 73 | 30 |
| `10secplus_within_study_area` | 33 | 12 |

Interpretation:

- this family expresses downstream position using approximate travel time at the assigned speed
- assigned speed comes from the existing upstream/downstream prototype speed context
- this is not stopping-sight distance, decision-sight distance, acceleration distance, or policy guidance

## Unresolved Cases Remain Explicit

Crash expanded assignment statuses by family:

| Family | Band assigned | Not downstream | Unresolved/conflict |
|---|---:|---:|---:|
| fixed 50-ft | 426 | 742 | 1,403 |
| coarse fixed | 426 | 742 | 1,403 |
| speed-time | 426 | 742 | 1,403 |

Access expanded assignment statuses by family:

| Family | Band assigned | Not downstream | Unresolved/conflict | No assigned speed |
|---|---:|---:|---:|---:|
| fixed 50-ft | 70 | 79 | 213 | 0 |
| coarse fixed | 70 | 79 | 213 | 0 |
| speed-time | 70 | 78 | 212 | 2 |

The two `no_assigned_speed` access rows are preserved as explicit non-assigned speed-band rows rather than receiving invented speed-based bands.

## Comparison To Package 001

Package 001 remains the frozen descriptive baseline.

Package 002 adds proposal-relevant band comparison structure:

- fixed 50-foot bins remain available for fine-grained review
- coarse fixed bands provide easier descriptive comparison across signals
- assigned-speed travel-time bands add an operational lens without invoking policy values
- future limiting/desirable/policy bands are documented but not implemented

Package 002 does not change:

- crash classification counts
- access assignment status counts
- same-corridor access recovery decisions
- AADT matching
- rural/urban crash-context logic
- signal eligibility

## Table Readiness

Stable descriptive baseline:

- Package 001 current outputs

Package 002 comparison-ready descriptive tables:

- `signal_band_context_analysis_expanded.csv`
- `crash_band_assignment_expanded.csv`
- `access_band_assignment_expanded.csv`

Still not model-ready:

- no denominator or exposure model has been defined
- unresolved-case treatment for modeling has not been selected
- speed-time bands are exploratory proxies only
- geographic context remains crash `AREA_TYPE` context, not roadway-level rural/suburban/urban truth
- access type and commercial/trip-generation fields are not validated for model use

## Not Yet

Package 002 does not support:

- regression
- crash-rate claims
- Appendix F recommendation language
- spreadsheet/tool logic
- expansion beyond divided roads
- rural/suburban/urban policy claims from crash `AREA_TYPE`
- additional access recovery

## Recommended Next Step

Use Package 002 to review whether coarse fixed and speed-time bands are useful for descriptive summaries.

The next bounded methodology task should define future limiting/desirable/policy band families from documented proposal, literature, or VDOT policy sources before generating those rows.
