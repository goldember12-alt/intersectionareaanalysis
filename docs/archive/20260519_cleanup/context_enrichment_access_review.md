# Context Enrichment Access Review

**Status: SUPPORTING REFERENCE.** This context-enrichment result remains in place for later graph-first crash/access migration review.

## Scope

This memo reviews the bounded access-enrichment behavior in `src/active/context_enrichment.py` for the latest rerun of `python -m src.active.context_enrichment`.

Latest rerun summary:

- `work/output/context_enrichment/runs/history/context_enrichment_run_summary_20260423_143606.json`

Latest rerun table paths used in this review:

- `work/output/context_enrichment/tables/history/access_assignment_points_20260423_143556.csv`
- `work/output/context_enrichment/tables/history/approach_row_context_enriched_20260423_143551.csv`
- `work/output/context_enrichment/tables/history/signal_study_area_context_enriched_20260423_143553.csv`

## Current behavior

Candidate generation remains bounded and conservative:

1. clip access points to study-area polygons
2. compare only against approach rows in the same `StudyAreaID`
3. require exact normalized route support on `ApproachRoad_RTE_NM == _rte_nm`
4. require `_m` within the row measure range plus/minus `0.005` miles
5. require point-to-row distance `<= 60.0` feet
6. after a unique row match, classify `near_signal` within `65.6` feet of the signal projection, otherwise use row flow to classify `upstream` or `downstream`

## Latest output counts

- candidate access points in study areas: `362`
- route-supported candidate points: `74`
- measure-supported candidate points: `71`
- distance-supported candidate points: `71`
- `matched`: `63`
- `near_signal`: `8`
- `route_conflict`: `288`
- `measure_conflict`: `3`
- `ambiguous`: `0`
- `too_far`: `0`
- `unresolved`: `0`
- approach rows with nonzero access density: `14`
- approach-row access status counts: `matched=14`, `partial=75`, `no_candidate_points=89`
- signal access status counts: `matched=2`, `partial=80`, `no_candidate_points=81`

## Diagnostic read

- The dominant filter is exact route support, not distance. Only `74` of `362` clipped access points have any exact-route-supported candidate row.
- Measure support removes only `3` more points after route support. The `60` foot distance gate removes none in the latest rerun.
- Current route matching is conservative but not merely whitespace-brittle. The large `route_conflict` bucket is driven mainly by semantic aliases or different route identities inside the study area, not by trim/spacing failures.
- Representative high-frequency route conflicts include:
  - `S-VA029PR RICHMOND HWY` against study-area route `R-VA US00001NB` (`27`)
  - `S-VA020PR E HUNDRED RD` against `R-VA SR00010EB` (`18`)
  - `S-VA043PR W BROAD ST` against `R-VA US00250EB` (`16`)
  - `R-VA US00058WBALT001` against `R-VA US00058EBALT001` (`13`)
  - `S-VA122PR HAMPTON BLVD` against `R-VA SR00337EB` or `R-VA SR00337WB` (`22` combined)
- Those are plausible same-corridor aliases in some cases, but resolving them would require broader route-family logic that is outside this bounded slice. On that basis, the current exact-route rule is appropriately conservative.

## Representative cases

Matched examples:

- `signal_281` / row `7461`: `R-VA US00029NB`, distance about `0.00018` feet, classified `downstream`
- `signal_247` / row `5824`: `R-VA SR00007EB`, distance about `0.00001` feet, classified `downstream`
- `signal_1718` / row `8237`: `R-VA US00029NB`, distance about `0.00010` feet, classified `downstream`

Rejected examples:

- `signal_1804`: `S-VA122PR NORTHAMPTON BLVD` or `S-VA122NP N MILITARY HWY` inside a study area whose approach route is `R-VA US00013SB`; both stay `route_conflict`
- `signal_1905`: multiple `S-VA122PR HAMPTON BLVD` points sit essentially on the row geometry but still remain `route_conflict` because the study-area route is `R-VA SR00337EB`
- `signal_1088`: `R-VA US00001NB` route support passes and point-to-row distance is near zero, but measure `173.8258` is outside the tolerated row range upper bound `173.575`, so it remains `measure_conflict`

Near-signal examples:

- `signal_247` / row `5824`: projection difference about `8.39` feet
- `signal_817` / row `7929`: projection difference about `19.11` feet

## Minimal corrections made

- row-level `Access_Status` no longer labels study areas with candidate access points as generic `other_access_processing_failure` when the real issue is unresolved study-area evidence; those rows now report `partial` plus `contains_ambiguous_or_unresolved_points`
- validation/reporting now exposes route-supported, measure-supported, and distance-supported candidate counts so the active filters are auditable without ad hoc inspection
- validation/reporting now exposes row-level and signal-level access status counts and matched-distance distributions

## Conclusion

The current access logic is appropriately conservative for the bounded slice. The main source of low coverage is exact route support, not measure tolerance or distance. The smallest justified improvement was reporting polish, not match-rule relaxation.
