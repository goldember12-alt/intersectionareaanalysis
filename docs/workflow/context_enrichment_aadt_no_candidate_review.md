# Context Enrichment AADT No-Candidate Review

## Purpose

This memo reviews the 6 residual `AADT_Status = no_candidate` approach rows from the latest bounded `src.active.context_enrichment` run.

The question here is narrow:

- do these rows legitimately remain unmatched under the current conservative AADT rule
- or does the evidence justify a very small additional rule

This is not a methodology redesign.

## Source run

- latest context-enrichment run summary:
  `work/output/context_enrichment/runs/history/context_enrichment_run_summary_20260423_141928.json`
- latest enriched approach-row table:
  `work/output/context_enrichment/tables/history/approach_row_context_enriched_20260423_141928.csv`

## High-level result

All 6 residual rows fail for the same documented reason:

- `AADT_Reason = no_local_geometry_support_candidate`

Across the 6 rows:

- `0` fail because of no route support
- `0` fail because of invalid or missing AADT values
- `0` are ambiguous
- `6` have exact-route, positive-measure-overlap AADT candidates
- `6` fail because no positive-measure-overlap candidate survives the active local-support threshold of `<= 3.0` feet

The residual set breaks into two shapes:

1. five rows have a same-route AADT line within `<= 3.0` feet, but that nearby line has `0.0` measure overlap with the study-road row
2. one row has positive-measure-overlap AADT support, but the nearest overlapping same-route line is about `60.2` feet away

This means the residuals are not due to missing AADT inventory. They are boundary cases where local geometric support and measure support do not coexist on the same candidate.

## Row-by-row review

### 1. `signal_303`

- identifiers:
  `StudyAreaID = signal_303`, `Signal_RowID = 303`, `StudyRoad_RowID = 8237`
- signal label:
  `Lee Highway / Braddock / Old Centreville Road`
- route:
  `R-VA   US00029NB`
- study-road measure range:
  `228.05` to `228.58`
- geometry summary:
  approach segment length about `710.0` feet; bounds `[179710.70, 317050.51, 179926.35, 317067.37]` in `EPSG:3968`
- exact-route AADT records exist nearby:
  yes; `1467` route-supported records overall
- failure breakdown:
  - route support: present
  - positive measure overlap: present on `7` candidates
  - local geometry `<= 3.0` feet: none
  - invalid/missing AADT: none; all `7` measure-supported candidates have positive AADT
- nearest plausible candidate:
  `LINKID 090080`, `AADT 29690`, `AADT_YR 2024`, quality `G`
- rejection reason:
  the nearest measure-supported candidate is about `122.84` feet away, so it fails the active local-support cap
- nearby exact-route note:
  the nearest same-route candidate overall is only about `2.84` feet away, but its measure overlap is `0.0`; the measure gap is about `0.12` miles
- recommendation:
  keep unmatched

### 2. `signal_1088`

- identifiers:
  `StudyAreaID = signal_1088`, `Signal_RowID = 1088`, `StudyRoad_RowID = 7110`
- signal label:
  `Richmond Highway / Opitz / Reddy Drive`
- route:
  `R-VA   US00001NB`
- study-road measure range:
  `171.65` to `173.57`
- geometry summary:
  approach segment length about `1008.64` feet; bounds `[193884.80, 294484.19, 194036.91, 294751.36]`
- exact-route AADT records exist nearby:
  yes; `2455` route-supported records overall
- failure breakdown:
  - route support: present
  - positive measure overlap: present on `21` candidates
  - local geometry `<= 3.0` feet: none
  - invalid/missing AADT: none
- nearest plausible candidate:
  `LINKID 190104`, `AADT 41358`, `AADT_YR 2024`, quality `G`
- rejection reason:
  nearest measure-supported candidate is about `709.05` feet away
- nearby exact-route note:
  a same-route candidate is about `2.01` feet away, but it has `0.0` measure overlap; the measure gap is about `0.103` miles
- recommendation:
  keep unmatched

### 3. `signal_1384`

- identifiers:
  `StudyAreaID = signal_1384`, `Signal_RowID = 1384`, `StudyRoad_RowID = 13645`
- signal label:
  `Warrenton Rd / Banks Ford Pkwy./Ent. To Car Dealership`
- route:
  `R-VA   US00017NB`
- study-road measure range:
  `181.59` to `183.54`
- geometry summary:
  approach segment length about `1620.0` feet; bounds `[173300.02, 263307.00, 173715.91, 263573.13]`
- exact-route AADT records exist nearby:
  yes; `1464` route-supported records overall
- failure breakdown:
  - route support: present
  - positive measure overlap: present on `14` candidates
  - local geometry `<= 3.0` feet: none
  - invalid/missing AADT: none
- nearest plausible candidate:
  `LINKID 060118`, `AADT 63349`, `AADT_YR 2024`, quality `F`
- rejection reason:
  nearest measure-supported candidate is about `655.57` feet away
- nearby exact-route note:
  a same-route candidate is about `1.89` feet away, but it has `0.0` measure overlap; its measure gap is only about `0.01` miles
- recommendation:
  keep unmatched under the current rule, but this is the single clearest review-only candidate if a future tiny adjacency bridge is ever studied

### 4. `signal_1607`

- identifiers:
  `StudyAreaID = signal_1607`, `Signal_RowID = 1607`, `StudyRoad_RowID = 7439`
- signal label:
  `Richmond Highway / Gordon Boulevard`
- route:
  `R-VA   US00001NB`
- study-road measure range:
  `175.06` to `176.20`
- geometry summary:
  approach segment length about `1100.0` feet; bounds `[195959.93, 297648.87, 196126.52, 297939.82]`
- exact-route AADT records exist nearby:
  yes; `2455` route-supported records overall
- failure breakdown:
  - route support: present
  - positive measure overlap: present on `8` candidates
  - local geometry `<= 3.0` feet: none
  - invalid/missing AADT: none
- nearest plausible candidate:
  `LINKID 190105`, `AADT 39603`, `AADT_YR 2024`, quality `G`
- rejection reason:
  the nearest measure-supported candidate is also the nearest same-route candidate overall, and it is about `60.22` feet away
- nearby exact-route note:
  unlike most of the other residuals, this row does not have a same-route candidate within `3` feet waiting just outside the measure-overlap rule
- recommendation:
  keep unmatched

### 5. `signal_1804`

- identifiers:
  `StudyAreaID = signal_1804`, `Signal_RowID = 1804`, `StudyRoad_RowID = 13631`
- signal label:
  `signal_1804`
- route:
  `R-VA   US00013SB`
- study-road measure range:
  `48.96` to `49.31`
- geometry summary:
  approach segment length about `1100.0` feet; bounds `[293205.88, 102146.57, 293383.29, 102309.40]`
- exact-route AADT records exist nearby:
  yes; `588` route-supported records overall
- failure breakdown:
  - route support: present
  - positive measure overlap: present on `1` candidate
  - local geometry `<= 3.0` feet: none
  - invalid/missing AADT: none
- nearest plausible candidate:
  `LINKID 654198`, `AADT 41966`, `AADT_YR 2024`, quality `F`
- rejection reason:
  the only measure-supported same-route candidate is about `452.79` feet away
- nearby exact-route note:
  that same link is only about `0.74` feet away geometrically, but with `0.0` overlap and about `0.24` miles of measure gap
- recommendation:
  keep unmatched

### 6. `signal_1869`

- identifiers:
  `StudyAreaID = signal_1869`, `Signal_RowID = 1869`, `StudyRoad_RowID = 12530`
- signal label:
  `signal_1869`
- route:
  `R-VA   US00058WB`
- study-road measure range:
  `494.99` to `506.62`
- geometry summary:
  approach segment length about `1100.0` feet; bounds `[290233.24, 99863.11, 290559.34, 99940.46]`
- exact-route AADT records exist nearby:
  yes; `2303` route-supported records overall
- failure breakdown:
  - route support: present
  - positive measure overlap: present on `98` candidates
  - local geometry `<= 3.0` feet: none
  - invalid/missing AADT: none
- nearest plausible candidate:
  `LINKID 654262`, `AADT 26769`, `AADT_YR 2024`, quality `F`
- rejection reason:
  nearest measure-supported candidate is about `2879.80` feet away
- nearby exact-route note:
  a same-route candidate is about `2.75` feet away, but has `0.0` overlap and about `0.786` miles of measure gap
- recommendation:
  keep unmatched

## Decision

The current conservative AADT rule should remain as-is.

Why:

- all 6 residuals are honest conflicts between measure support and local geometric support
- none are missing-AADT or no-route-support cases
- none are ambiguous under the current rule
- four of the five local-but-no-overlap rows have measure gaps that are clearly too large to bridge casually:
  `0.103`, `0.12`, `0.24`, and `0.786` miles
- the remaining outlier, `signal_1607`, is not a boundary-gap case at all; the nearest measure-supported candidate is simply about `60` feet away

## Very narrow extension consideration

No rule change is recommended in this pass.

If a future micro-extension is ever studied, the only case that looks potentially suitable for review is:

- `signal_1384`

Why that row is different:

- same-route candidate is within about `1.89` feet
- measure gap is only about `0.01` miles
- candidate is unique and has populated `AADT`, `AADT_YR`, and route support

Why it still should not be implemented now:

- the current contract explicitly requires positive measure overlap
- this would introduce a new adjacency bridge rule for exactly one recovered row
- even a tiny-gap bridge changes the meaning of the current conservative selection rule
- the residual count is already small enough that forcing this one row does not materially improve coverage

If that idea is revisited later, it should stay review-only and extremely narrow, for example:

- exact-route candidate only
- local distance still `<= 3.0` feet
- no positive-overlap candidate exists within `3.0` feet
- unique smallest local-distance candidate
- measure gap capped at something like `<= 0.01` miles

That would still need explicit acceptance as a rule change before implementation.
