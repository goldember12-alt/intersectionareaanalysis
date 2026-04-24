# Same-Corridor Access Map Review Checklist

## Scope

Use this checklist before adding or promoting reviewed-family same-corridor access matching changes.

Current completed review:

- `docs/workflow/context_enrichment_access_same_corridor_map_review_completed.md`
- fixture baseline: `tests/fixtures/access_same_corridor_pre_promotion_guardrails/`

Review layers:

- `work/output/context_enrichment_access_same_corridor_prototype/review/geojson/current/recovered_same_corridor_assignments.geojson`
- `work/output/context_enrichment_access_same_corridor_prototype/review/geojson/current/refused_same_corridor_candidates.geojson`

Impact tables:

- `work/output/context_enrichment_access_same_corridor_prototype/review/current/signal_approach_impact_summary.csv`
- `work/output/context_enrichment_access_same_corridor_prototype/review/current/approach_row_impact_summary.csv`

## Families To Confirm

Recovered approved families:

- `e_hundred_rd__sr00010eb`
- `hampton_blvd__sr00337eb`
- `jefferson_davis_hwy_np__us00001nb`
- `warrenton_rd__us00017nb`
- `w_broad_st_np__us00250eb`

Excluded families that must remain unmatched unless separately re-reviewed:

- `richmond_hwy__us00001nb`
- `w_broad_st_pr__us00250eb`
- `hampton_blvd__sr00337wb`
- `jefferson_davis_hwy_pr__us00001nb`
- `us00058_alt_opposite_direction`
- `us00019_opposite_direction`
- `us00250_opposite_direction`
- `secondary_connector__us00001nb`

## Review Questions

- Does each recovered access point lie on the intended same-corridor carriageway?
- Does each recovered point attach to the intended `StudyRoad_RowID`?
- Are upstream, downstream, and near-signal labels plausible on the map?
- Are refused candidates correctly refused because the approved study route is absent or support is not unique?
- Do any recovered assignments appear to cross to an opposing carriageway, frontage road, side road, or parallel facility?
- Do high-impact signals such as `signal_83`, `signal_82`, `signal_1606`, and `signal_1874` remain plausible after reviewing all recovered points?

## Promotion Boundary

Production promotion is limited to:

1. exact-route matching first
2. reviewed-family local-geometry matching only for approved route-family pairs
3. explicit refusal when the approved study route is absent or assignment is not uniquely supported
4. no fuzzy matching
5. no unreviewed route aliases

Do not use the broad all-route-conflict diagnostic as production behavior.
