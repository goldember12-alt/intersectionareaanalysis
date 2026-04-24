# Same-Corridor Access Map Review Completed

Date: 2026-04-24

Review basis:

- frozen guardrail fixture: `tests/fixtures/access_same_corridor_pre_promotion_guardrails/`
- recovered layer: `recovered_same_corridor_assignments.geojson`
- refused layer: `refused_same_corridor_candidates.geojson`
- supporting impact tables: `signal_approach_impact_summary.csv`, `approach_row_impact_summary.csv`

This review covers the approved reviewed-family overlay that is now promoted into `src.active.context_enrichment`. It does not authorize any unreviewed route aliases, opposite-direction pairs, offset frontage/parallel-risk families, or broad all-route-conflict recovery.

## Recovered Feature Review

All recovered features are within the existing approved family set and retain unique local-geometry support. No recovered feature uses an excluded or unreviewed family.

| Family | Rows | Unique points | Signals | Max distance ft | Position mix |
| --- | ---: | ---: | ---: | ---: | --- |
| `e_hundred_rd__sr00010eb` | 18 | 16 | 3 | 0.001632 | downstream 9, upstream 6, near_signal 3 |
| `hampton_blvd__sr00337eb` | 11 | 11 | 3 | 0.000417 | downstream 5, upstream 4, near_signal 2 |
| `jefferson_davis_hwy_np__us00001nb` | 9 | 9 | 4 | 0.185423 | downstream 3, upstream 3, near_signal 3 |
| `warrenton_rd__us00017nb` | 9 | 9 | 3 | 0.001192 | downstream 5, upstream 4 |
| `w_broad_st_np__us00250eb` | 8 | 7 | 5 | 0.000902 | downstream 6, upstream 2 |

Largest reviewed signal/study-area changes remain the previously accepted impact guardrails:

| Study area | Recovered rows | Family | Position mix | Max distance ft |
| --- | ---: | --- | --- | ---: |
| `signal_83` | 9 | `e_hundred_rd__sr00010eb` | downstream 4, upstream 4, near_signal 1 | 0.000756 |
| `signal_82` | 6 | `e_hundred_rd__sr00010eb` | downstream 4, upstream 1, near_signal 1 | 0.000403 |
| `signal_1606` | 5 | `jefferson_davis_hwy_np__us00001nb` | downstream 2, upstream 2, near_signal 1 | 0.000174 |
| `signal_1874` | 5 | `hampton_blvd__sr00337eb` | upstream 3, downstream 1, near_signal 1 | 0.000417 |
| `signal_1905` | 4 | `hampton_blvd__sr00337eb` | downstream 2, upstream 1, near_signal 1 | 0.000080 |
| `signal_1369` | 4 | `warrenton_rd__us00017nb` | downstream 2, upstream 2 | 0.000082 |

Decision: recovered features pass this bounded review. The geometry-support evidence remains extremely tight, the family set is explicit, and the signal/approach-row impacts match the accepted guardrails.

## Refused Feature Review

The refused layer contains 11 rows, all in `hampton_blvd__sr00337eb`, across four study areas:

- `signal_1790`
- `signal_1791`
- `signal_1875`
- `signal_1906`

Every refused feature has:

- `Prototype_AssignmentStatus = approved_study_route_not_present`
- `Prototype_AssignmentReason = approved_family_route_absent_in_study_area`
- `Prototype_EffectiveAssignmentStatus = route_conflict`

Decision: refused features pass this bounded review as appropriate refusals. The rule did not infer a match from corridor name alone when the approved study route was absent.

## Final Boundary

The reviewed-family overlay is acceptable as current production behavior only under this boundary:

1. exact-route matching runs first
2. same-corridor recovery runs only for `ReviewDecision = include` pairs
3. approved study route must be present in the study area
4. exactly one approved row must be locally supported and must be the unique nearest row
5. projection and signal-relative orientation must succeed
6. excluded and unreviewed aliases remain unmatched
7. broad all-route-conflict diagnostics remain non-production

No new reviewed families should be added without a new fixture update, map-review note, and regression-test update.
