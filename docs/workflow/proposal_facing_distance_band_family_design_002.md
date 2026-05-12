# Proposal-Facing Distance Band Family Design 002

## Bounded Purpose

Package 002 expands downstream distance-band summaries from the frozen Package 001 descriptive baseline.

This design does not change matching, enrichment, access recovery, crash classification, or upstream/downstream logic. It only re-bins existing downstream crash and access distances into additional descriptive band families.

## Band Family 1: Fixed 50-Foot Bins

Family key:

- `fixed_50ft_from_signal_within_study_area`

Definition:

- 50-foot intervals from the signal along the current approach-shaped study area
- examples: `0-50`, `50-100`, `100-150`

Provenance:

- copied forward from Package 001 and current context-enrichment outputs
- based on existing signal-relative projection distances

Intended use:

- fine-grained descriptive scan of downstream crash and access concentration
- visual review and early pattern detection

Not intended for:

- defining downstream functional area limits
- regression-ready final bands
- Appendix F guidance language

## Band Family 2: Coarse Fixed Bands

Family key:

- `fixed_coarse_0_250_500_1000ft_with_overflow`

Definition:

- `0-250`
- `250-500`
- `500-1000`
- `1000plus_within_study_area`

Provenance:

- derived from Package 001 crash/access downstream distances
- re-bins the fixed 50-foot detail into proposal-facing distance ranges
- overflow band preserves downstream points beyond 1,000 feet that are still inside the current approach-shaped study area

Intended use:

- first comparison-ready descriptive table for broad downstream zones
- early proposal-facing summaries where 50-foot bins are too granular
- identifying whether downstream crashes/access concentrate near the signal or farther downstream

Not intended for:

- claiming that `250`, `500`, or `1,000` feet are design thresholds
- replacing future limiting/desirable or policy-derived bands

## Band Family 3: Assigned-Speed Travel-Time Bands

Family key:

- `speed_time_3_6_10sec_at_assigned_speed_with_overflow`

Definition:

- `0-3sec`
- `3-6sec`
- `6-10sec`
- `10secplus_within_study_area`

Distance conversion:

- `distance_ft = AssignedSpeedMph * 5280 / 3600 * seconds`

Provenance:

- uses the existing assigned speed carried from the upstream/downstream prototype
- assigned speed may come from `raw_speed_join` or `default_speed`
- uses current downstream crash/access distance fields from Package 001

Intended use:

- exploratory operational proxy that expresses downstream position in approximate travel-time units
- comparison against fixed-foot bands to see whether speed changes interpretation
- descriptive analysis only

Not intended for:

- stopping-sight distance
- decision-sight distance
- acceleration-distance guidance
- policy or design values

Rows without usable assigned speed stay explicit with a non-assigned band status rather than receiving invented distances.

## Placeholder Family: Limiting/Desirable Bands

Future family key placeholder:

- `future_limiting_desirable_policy_bands`

Possible future definition:

- physical intersection area to limiting value
- limiting value to desirable value
- beyond desirable value within study area

Provenance needed before implementation:

- documented literature or VDOT policy source
- applicability by speed, roadway type, access type, or intersection context
- explicit handling of divided-road carriageways and study-area boundaries

Current status:

- placeholder only
- no Package 002 rows generated

## Placeholder Family: Policy/Corner-Clearance Bands

Future family key placeholder:

- `future_corner_clearance_or_access_policy_bands`

Possible future definition:

- downstream physical intersection area
- downstream corner-clearance policy distance
- downstream access-management comparison zone

Provenance needed before implementation:

- documented policy source
- clear distinction between access-management guidance and crash evidence
- explicit treatment of near-signal access points

Current status:

- placeholder only
- no Package 002 rows generated

## Package 002 Output Tables

Generated tables:

- `work/output/proposal_descriptive/package_002/tables/current/signal_band_context_analysis_expanded.csv`
- `work/output/proposal_descriptive/package_002/tables/current/crash_band_assignment_expanded.csv`
- `work/output/proposal_descriptive/package_002/tables/current/access_band_assignment_expanded.csv`

Rows are also copied to:

- `work/output/proposal_descriptive/package_002/tables/history/`

## Unresolved-Case Rule

Unresolved crashes and unresolved access assignments remain explicit.

The expanded crash/access assignment tables repeat source rows once per implemented band family and use `ExpandedBandAssignmentStatus` to distinguish:

- `band_assigned`
- `not_downstream_not_band_assigned`
- `unresolved_or_conflict_not_band_assigned`
- `no_assigned_speed`

This keeps downstream-only band counts usable without hiding upstream, near-signal, unresolved, route-conflict, or measure-conflict records.

