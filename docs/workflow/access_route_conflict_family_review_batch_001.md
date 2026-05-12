# Access Route-Conflict Family Review Batch 001

## Bounded Question

Which repeated route-conflict access families from the current divided-road, approach-shaped context-enrichment run should be reviewed first for possible explicit same-corridor promotion?

This report is a review aid only. It does not promote any families, does not change production access matching behavior, and does not edit `docs/workflow/context_enrichment_access_same_corridor_seed_families.csv`.

## Source Outputs

- `work/output/context_enrichment/tables/current/access_route_conflict_diagnostics.csv`
- `work/output/context_enrichment/tables/current/access_route_conflict_family_summary.csv`
- `work/output/context_enrichment/review/geojson/current/access_route_conflict_candidates.geojson`
- `work/output/context_enrichment/review/current/context_enrichment_validation_summary.md`

Current route-conflict validation counts:

- route-conflict diagnostic rows: `233`
- route-conflict family rows: `85`
- reviewed-family status counts: `{"approved_study_route_not_present": 11, "family_excluded": 83, "no_reviewed_family": 139}`
- review-bucket counts: `{"candidate_same_corridor_alias": 39, "insufficient_evidence": 51, "likely_cross_street_or_local_access": 48, "likely_wrong_carriageway_or_parallel_facility": 95}`
- route conflicts within `5` feet of nearest study row: `57`
- route conflicts within `60` feet of nearest study row: `227`

## Ranking Method

Families are ranked for review using:

- `ReviewBucket == candidate_same_corridor_alias`
- higher `ConflictPointCount`
- higher `DistinctSignalCount`
- higher `Within5FtCount` and `NearZeroCount`
- stable nearest study route behavior
- no opposite-direction warning
- no existing reviewed-family exclusion

The ranking is not an approval decision. Mapped review in `access_route_conflict_candidates.geojson` is still required before any seed-family promotion.

## Ranked Candidate Families

| Rank | Access route | Candidate study route | Points | Signals | Median ft | Near-zero | Within 5 ft | Existing review | Initial read |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `S-VA095PR PORTERFIELD HWY` | `R-VA US00019SB` | 9 | 2 | 0.000134 | 9 | 9 | none | Strong repeated near-zero candidate; not in the named target list but ranks highest by count. |
| 2 | `S-VA082PR SPOTSWOOD TRL` | `R-VA US00033EB` | 8 | 3 | 0.000137 | 8 | 8 | none | Strong named target; stable study-route behavior and no warning flags. |
| 3 | `S-VA080NP FRANKLIN RD` | `R-VA US00220NB` | 7 | 4 | 0.000104 | 6 | 6 | none | Strong named target, but one point is about `30.35` ft from the nearest row; mapped review should verify that outlier before promotion. |
| 4 | `S-VA097PR ORBY CANTRELL HWY` | `R-VA US00023NB` | 4 | 2 | 0.000109 | 4 | 4 | none | Strong repeated near-zero candidate; not named but clean in diagnostics. |
| 5 | `S-VA122NP HAMPTON BLVD` | `R-VA SR00337WB` | 3 | 3 | 0.000016 | 3 | 3 | none | Named target and strong for this explicit pair; do not generalize to all Hampton Boulevard route variants. |
| 6 | `S-VA043NP S AIRPORT DR` | `R-VA SR00156NB` | 3 | 3 | 0.000098 | 3 | 3 | none | Clean repeated near-zero candidate; needs mapped review for side-street or connector risk. |
| 7 | `S-VA053PR HARRY BYRD HWY` | `R-VA SR00007EB` | 3 | 1 | 0.000143 | 3 | 3 | none | Named target; repeated near-zero points, but all occur at one signal, so it is less robust than multi-signal candidates. |
| 8 | `S-VA114PR EATON ST` | `R-VA US00060EB` | 2 | 2 | 0.000146 | 2 | 2 | none | Small repeated candidate; one row has a very close second-nearest row gap, so mapped review should check ambiguity. |

## Named Target Families

`S-VA122NP HAMPTON BLVD` against `R-VA SR00337WB` is a strong explicit-pair candidate: `3` points, `3` signals, all near zero, no opposite-direction warning, and no existing exclusion. However, the same access route also appears against `R-VA SR00337EB` with `2` points around `53.3` ft and `insufficient_evidence`. Any future promotion should be only for the explicit `S-VA122NP HAMPTON BLVD` to `R-VA SR00337WB` pair unless mapped review supports more.

`S-VA080NP FRANKLIN RD` against `R-VA US00220NB` is a strong candidate: `7` points across `4` signals, `6` near-zero/within-5-ft points, no exclusion, and no opposite-direction warning. The one `30.35` ft row should be checked on the map before promotion.

`S-VA082PR SPOTSWOOD TRL` against `R-VA US00033EB` is one of the strongest candidates: `8` points across `3` signals, all near zero, no exclusion, and no opposite-direction warning.

`S-VA053PR HARRY BYRD HWY` against `R-VA SR00007EB` is a plausible candidate: `3` near-zero points, no exclusion, and no opposite-direction warning. Its weakness is that all evidence is from one signal, so it should be reviewed after the stronger multi-signal candidates unless map review clearly resolves it.

## Recommended First Promotion Candidates

These are advisory pending mapped review. They are not yet approved for seed-family promotion.

1. `S-VA082PR SPOTSWOOD TRL` -> `R-VA US00033EB`
2. `S-VA080NP FRANKLIN RD` -> `R-VA US00220NB`
3. `S-VA095PR PORTERFIELD HWY` -> `R-VA US00019SB`

Rationale: these have the best combination of repeated points, multiple signals, near-zero local support, stable nearest study route behavior, no opposite-direction warning, and no current exclusion.

Secondary mapped-review candidates:

- `S-VA122NP HAMPTON BLVD` -> `R-VA SR00337WB`
- `S-VA097PR ORBY CANTRELL HWY` -> `R-VA US00023NB`
- `S-VA043NP S AIRPORT DR` -> `R-VA SR00156NB`
- `S-VA053PR HARRY BYRD HWY` -> `R-VA SR00007EB`
- `S-VA114PR EATON ST` -> `R-VA US00060EB`

## Hampton PR Coverage Warning

The current run has `11` `approved_study_route_not_present` rows for:

- access route: `S-VA122PR HAMPTON BLVD`
- nearest study route: `R-VA SR00337WB`
- affected study areas: `signal_1790`, `signal_1791`, `signal_1875`, `signal_1906`
- distance range: `46.55` to `54.04` ft
- median distance: `49.40` ft
- current exact-pair review decision: `exclude`
- current refusal risk: `wrong_carriageway_risk`

This group should remain refused unless mapped review explicitly overturns the current exclusion. It is not the same case as the near-zero `S-VA122NP HAMPTON BLVD` to `R-VA SR00337WB` candidate.

## Families To Keep Refused Or Unresolved For Now

These examples should not be promoted in the first pass:

| Access route | Study route | Points | Median ft | Current review | Reason |
| --- | --- | ---: | ---: | --- | --- |
| `S-VA122PR HAMPTON BLVD` | `R-VA SR00337WB` | 11 | 49.40 | `exclude` | Explicit `wrong_carriageway_risk`; keep refused pending mapped reversal. |
| `S-VA029PR RICHMOND HWY` | `R-VA US00001NB` | 27 | 56.51 | `exclude` | Offset/frontage risk. |
| `S-VA043PR W BROAD ST` | `R-VA US00250EB` | 16 | 54.15 | `exclude` | Offset/parallel risk. |
| `R-VA US00058WBALT001` | `R-VA US00058EBALT001` | 13 | 0.000041 | `exclude` | Opposite-direction risk despite near-zero geometry. |
| `R-VA029SC00779SB` | `R-VA US00001NB` | 12 | 48.40 | `exclude` | Secondary connector/local-route risk. |
| `S-VA076PR JEFFERSON DAVIS HWY` | `R-VA US00001NB` | 11 | 28.06 | `exclude` | Offset/parallel risk. |

## Next Manual Review Steps

1. Open `access_route_conflict_candidates.geojson` with the ranked families filtered by `AccessRouteNorm` and `StudyRouteNorm`.
2. For each candidate, confirm whether the point lies on the same corridor and correct carriageway rather than a frontage road, connector, crossing street, or parallel facility.
3. Check second-nearest row behavior where present, especially for `S-VA114PR EATON ST`.
4. Promote only explicit access-route to study-route pairs in `context_enrichment_access_same_corridor_seed_families.csv`.
5. After any promotion batch, rerun `src.active.context_enrichment` and compare route-conflict counts, matched counts, near-signal counts, and signal-level downstream access counts.
