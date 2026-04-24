# Context Enrichment Access Same-Corridor Recommendation

## Scope

This memo investigates whether the current access route gate is too strict for obvious same-corridor cases and whether a bounded alternate evidence chain could replace exact coded-route identity for a small, reviewed subset.

Inputs reviewed:

- `src/active/context_enrichment.py`
- `docs/workflow/context_enrichment_access_review.md`
- `docs/workflow/context_enrichment_access_alias_recommendation.md`
- latest run summary: `work/output/context_enrichment/runs/history/context_enrichment_run_summary_20260423_143606.json`
- latest access outputs under `work/output/context_enrichment/tables/history/` and `review/geojson/history/`

## Current accounting

### What is being counted

- `unique access point`
  - one normalized access feature identified by `Access_PointID`
- `point-study-area record`
  - one access point intersecting one `StudyAreaID` polygon after the spatial join
  - this is the unit written to `access_assignment_points.csv`
- `point-to-approach-row evaluation`
  - the internal comparison of one point-study-area record against every approach row in that study area
  - this is not written as a separate output table
- `final assignment record`
  - the same point-study-area record after internal row evaluation, with one final status and possibly one chosen `StudyRoad_RowID`

### Latest run breakdown

- total point-study-area records examined: `362`
- unique access points involved: `310`
- unique study areas containing candidate access points: `83`
- unique point-study-area pairs: `362`

Why a single access point can appear multiple times:

- the module spatially joins access points to study-area polygons with `predicate="intersects"`
- if one access point falls inside multiple overlapping study areas, it produces one output row for each `StudyAreaID`
- that duplication happens before route matching

Observed duplication in the latest run:

- points appearing once: `270`
- points appearing twice: `31`
- points appearing three times: `6`
- points appearing four times: `3`
- repeated points across more than one study area: `40`
- max study areas for one point: `4`

Representative repeated-route-conflict example:

- three `R-VA029SC00779SB` access points each appear in `4` study areas:
  - `signal_1697`
  - `signal_178`
  - `signal_179`
  - `signal_180`

Representative repeated-non-route-conflict example:

- several `R-VA US00250EB` access points appear in `2` adjacent W Broad study areas and are `matched` in both, for example:
  - `signal_815` and `signal_816`
  - `signal_816` and `signal_832`
  - `signal_815` and `signal_890`

### Non-route-conflict accounting

Candidate records that do not end as `route_conflict`:

- point-study-area rows not ending `route_conflict`: `74`
- unique access points represented by those rows: `64`

Among those `74` non-route-conflict point-study-area rows:

- exact-route support present: `74`
- measure support present: `71`
- local distance support present: `71`
- final `matched`: `63`
- final `near_signal`: `8`
- final `measure_conflict`: `3`
- final `too_far`: `0`
- final `ambiguous`: `0`
- final `unresolved`: `0`

Interpretation:

- the current workflow already has a clean working subset
- once a point-study-area record survives the route gate, almost all of it survives the rest of the chain
- the active bottleneck is therefore route identity, not distance and not row uniqueness

## Same-corridor family findings

### Strong same-corridor appearance, but measure-system mismatch

These families look like the same practical corridor by signal label and local geometry, but they fail because the access and study-road measure systems are not compatible.

#### `S-VA020PR E HUNDRED RD` vs `R-VA SR00010EB`

- rows: `18`
- unique points: `16`
- signals: `3`
- nearest-row distance: essentially zero across the family
- access measures: about `0.13` to `1.45`
- study-road measures: about `19.99` to `21.23`
- failure after ignoring route: `no measure compatibility`

Read:

- corridor identity looks real
- route-name mismatch is likely not the true substantive problem
- the actual blocker is incompatible measure space

#### `S-VA122PR HAMPTON BLVD` vs `R-VA SR00337EB`

- rows: `11`
- unique points: `11`
- signals: `3`
- nearest-row distance: essentially zero
- access measures: about `1.28` to `2.58`
- study-road measures: about `30.32` to `31.96`
- failure after ignoring route: `no measure compatibility`

Read:

- this is one of the clearest same-corridor families geometrically
- but the current contract cannot use it because the measure systems are structurally different

#### `S-VA043NP W BROAD ST` vs `R-VA US00250EB`

- rows: `8`
- unique points: `7`
- signals: `5`
- nearest-row distance: essentially zero
- access measures: about `2.94` to `4.05`
- study-road measures: about `157.93` to `159.78`
- failure after ignoring route: `no measure compatibility`

Read:

- same-corridor evidence is strong
- again, route identity alone is not the real limiting factor once measures are examined

#### `S-VA089PR WARRENTON RD` vs `R-VA US00017NB`

- rows: `9`
- unique points: `9`
- signals: `3`
- nearest-row distance: essentially zero
- access measures: about `2.69` to `4.07`
- study-road measures: about `181.59` to `183.54`
- failure after ignoring route: `no measure compatibility`

### Same-corridor naming with stronger spatial-offset risk

These families may still name the same corridor, but the local geometry is offset enough to raise frontage-road, side-lane, or parallel-facility risk.

#### `S-VA029PR RICHMOND HWY` vs `R-VA US00001NB`

- rows: `27`
- unique points: `20`
- signals: `8`
- nearest-row distances: about `44` to `59` feet
- access measures: about `2.45` to `4.10`
- study-road measures: about `187.05` to `189.59`
- failure after ignoring route: `no measure compatibility`

Read:

- same-corridor label evidence exists
- but the consistent `44` to `59` foot offset is materially different from the zero-distance families
- this does not look safe for an automatic replacement chain in the active slice

#### `S-VA043PR W BROAD ST` vs `R-VA US00250EB`

- rows: `16`
- unique points: `14`
- signals: `6`
- nearest-row distances: about `45` to `62` feet
- access measures: about `2.58` to `7.97`
- study-road measures: about `154.93` to `159.78`
- failure after ignoring route: `no measure compatibility`

Read:

- same-corridor naming is plausible
- the geometry is offset enough to make a naive same-corridor relaxation risky

### Same named corridor, but directionally different behavior within the family

#### `S-VA122PR HAMPTON BLVD` vs `R-VA SR00337WB`

- rows: `11`
- unique points: `10`
- signals: `4`
- nearest-row distances: about `46` to `54` feet
- failure after ignoring route: `no measure compatibility`

Read:

- the EB family is a zero-distance same-corridor case
- the WB family is offset by roughly fifty feet
- that split strongly suggests the same corridor family does not behave uniformly by carriageway
- any alternative evidence chain would need explicit direction-by-family review

### Same-corridor families that cluster repeatedly

The following families cluster across multiple nearby signals and therefore look like real repeated corridor relationships rather than random coincidence:

- `RICHMOND HWY` / `JEFFERSON DAVIS HWY` with `US00001NB`
- `W BROAD ST` with `US00250EB`
- `HAMPTON BLVD` with `SR00337EB/WB`
- `E HUNDRED RD` with `SR00010EB`
- `WARRENTON RD` with `US00017NB`

That is useful evidence for a future reviewed-family concept, but not enough by itself for active matching.

## Bounded alternate evidence chain

### Smallest plausible replacement for exact coded-route identity

If same-corridor cases are pursued later, the smallest conservative alternative is:

1. an explicit reviewed same-corridor family table
2. family-specific approval of which access route may link to which study route
3. very strong local geometry support to exactly one row in the study area
4. a projection-based local support check on that row
5. explicit ambiguity refusal when more than one row remains plausible

In practical terms, a bounded prototype could require all of:

- reviewed family membership from a hand-built table
- point-study-area record is within a very small local threshold of exactly one approach row
  - the zero-distance families suggest a threshold in the single-digit feet range, not `60` feet
- the nearest competing row is materially farther away
- point projection onto the chosen row succeeds
- the access point stays inside the bounded approach extent or another explicit local support window
- otherwise leave the point unresolved

### What this would recover

Potentially recoverable only in a prototype:

- zero-distance same-corridor families such as:
  - `E HUNDRED RD` / `SR00010EB`
  - `HAMPTON BLVD` / `SR00337EB`
  - `W BROAD ST` / `US00250EB` for the `NP` subset
  - `WARRENTON RD` / `US00017NB`
  - `JEFFERSON DAVIS HWY` / `US00001NB` for the `NP` subset

### New risks introduced

- a reviewed family table is still a methodological expansion beyond the current contract
- without compatible measure systems, the chain would no longer have the current route-plus-measure backbone
- some corridor families split by carriageway behavior, so a family approved at too broad a level could create false positives
- offset families like `RICHMOND HWY` / `US00001NB` and `W BROAD ST PR` / `US00250EB` could pull frontage or parallel facilities into the wrong row

### Acceptability for the active slice

This is not strong enough for production matching now.

It is strong enough to justify a bounded prototype outside production matching, because:

- several same-corridor families are clearly real by label and local geometry
- the current exact route gate is too strict for those families in a practical sense
- but the current contract does not contain a trustworthy replacement for the missing measure compatibility

## Recommendation

### 1. How strict is the current route gate?

Very strict.

It currently excludes all same-corridor cases whose coded route strings differ, even when the point sits essentially on top of the study row.

### 2. How many access candidates already work cleanly without route-conflict?

- `74` point-study-area rows
- `64` unique access points

Within that subset, the rest of the chain is already clean:

- `71` pass measure
- `71` pass distance
- `63` end `matched`
- `8` end `near_signal`
- `3` end `measure_conflict`

### 3. Why do some access points appear multiple times?

Because the output unit is a point-study-area record, and study-area polygons overlap.

One access point can therefore intersect multiple signal-centered study areas and generate multiple final rows before any route or row filtering happens.

### 4. Are any same-corridor families strong enough for a bounded alternate evidence chain?

Yes, but only for a prototype outside production matching.

The strongest candidates are the near-zero-distance, repeated same-corridor families:

- `E HUNDRED RD` / `SR00010EB`
- `HAMPTON BLVD` / `SR00337EB`
- `W BROAD ST NP` / `US00250EB`
- `WARRENTON RD` / `US00017NB`
- `JEFFERSON DAVIS HWY NP` / `US00001NB`

These are not safe for production yet because the current methodology has no trusted bridge between the access measure system and the study-road measure system.

### 5. Recommended next step

Bounded prototype outside production matching.

Not a production implementation, and not "no change" in the methodological sense.

The evidence supports a small manual-review-table prototype for same-corridor families with:

- explicit reviewed family membership
- very small local geometry threshold
- unique nearest-row requirement
- projection success
- explicit ambiguity refusal

That is the smallest credible next step if the goal is to move beyond exact coded-route identity without silently weakening conservatism.

## Current Prototype Impact Validation

The reviewed-family prototype now writes a signal/approach-row impact review under:

- `work/output/context_enrichment_access_same_corridor_prototype/review/current/signal_approach_impact_summary.csv`
- `work/output/context_enrichment_access_same_corridor_prototype/review/current/approach_row_impact_summary.csv`
- `work/output/context_enrichment_access_same_corridor_prototype/review/current/signal_approach_impact_summary.json`
- `work/output/context_enrichment_access_same_corridor_prototype/review/current/signal_approach_impact_summary.md`

Latest confirmed prototype accounting:

- production route-conflict point-study-area rows: `288`
- reviewed-family rows evaluated: `66`
- recovered rows: `55`
- recovered unique access points: `52`
- effective status after prototype overlay:
  - `matched = 110`
  - `near_signal = 16`
  - `route_conflict = 233`
  - `measure_conflict = 3`
- recovered signal-relative positions:
  - `downstream = 28`
  - `upstream = 19`
  - `near_signal = 8`
- recovered row-distance support remains extremely tight:
  - average row distance about `0.0036 ft`
  - maximum row distance about `0.185 ft`

Impact summary:

- signal/study areas with access-count changes: `18`
- total signal-level access-count delta: `55`
- maximum signal-level access-count delta: `9`
- approach rows with access-count changes: `18`
- total approach-row access-count delta: `55`
- maximum approach-row access-count delta: `9`
- refused reviewed-family candidates: `11` rows across `4` signal/study areas

Largest signal/study-area count changes in the current run:

- `signal_83`: `+9`
- `signal_82`: `+6`
- `signal_1606`: `+5`
- `signal_1874`: `+5`
- `signal_1369`: `+4`
- `signal_1905`: `+4`

The refused reviewed-family candidates do not change counts. They remain manual-review flags because the approved study route was absent in the study area. This is the intended conservative refusal mode.

## Current Production Decision Boundary

The reviewed-family overlay has been promoted into `src.active.context_enrichment` as a bounded production rule.

The production rule is:

1. run the existing exact-route rule first
2. then apply a reviewed-family local-geometry rule only for approved route-family pairs
3. explicitly refuse assignment if the approved study route is absent or if assignment is not uniquely supported
4. do not use fuzzy matching
5. do not use unreviewed route aliases

The promoted production run matches the prototype-effective guardrails:

- `matched = 110`
- `near_signal = 16`
- `route_conflict = 233`
- `measure_conflict = 3`
- reviewed-family recovered rows: `55`
- reviewed-family recovered unique access points: `52`

Production expansion remains blocked for:

- unreviewed route aliases
- opposite-direction route pairs
- offset frontage/parallel-risk families
- local/secondary-to-parent substitutions
- broad all-route-conflict recovery diagnostics

Do not expand the seed-family table to unreviewed aliases without a new review artifact and regression update.

The completed review note is `docs/workflow/context_enrichment_access_same_corridor_map_review_completed.md`.

The pre-promotion prototype guardrails are frozen under `tests/fixtures/access_same_corridor_pre_promotion_guardrails/` and protected by fixture hash tests. Future reviewed-family additions must update that fixture strategy deliberately rather than relying on mutable `work/output/.../current/` prototype outputs.

Mapped review should still use `docs/workflow/context_enrichment_access_same_corridor_map_review_checklist.md` before expanding the reviewed family table.
