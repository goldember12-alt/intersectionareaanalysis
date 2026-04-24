# Context Enrichment AADT and StudyAreaID Diagnostic Memo

## Scope

This memo diagnoses two issues from the current bounded `src.active.context_enrichment` run without broadening the workflow:

1. AADT produced zero candidates and zero selected rows.
2. `signal_study_area_summary__approach_shaped.csv` was not unique on `StudyAreaID`.

The diagnosis is based on the current code, current documented inputs, and the current run outputs.

## AADT diagnosis

### What the module is currently doing

`_build_aadt_candidates()` currently does the following:

1. reads `StudyAreaID`, `StudyRoad_RowID`, `Signal_RowID`, `SignalRouteName`, `ApproachLengthMeters`, and approach-row geometry from `approach_rows.geojson`
2. trims and whitespace-normalizes `SignalRouteName`, `RTE_NM`, and `MASTER_RTE_NM`
3. runs `gpd.sjoin(... predicate="intersects")` between approach-row geometry and AADT geometry
4. computes `AADT_OverlapLengthFt` from the exact line-line intersection geometry
5. drops all candidate pairs with `AADT_OverlapLengthFt <= 0`
6. applies exact route support only:
   - `rte_nm_exact` if normalized `SignalRouteName == RTE_NM`
   - `master_rte_exact` if normalized `SignalRouteName == MASTER_RTE_NM` and `RTE_NM` did not already match
   - otherwise `unsupported`
7. for route-supported candidates with positive numeric `AADT`, keeps the latest non-null `AADT_YR`
8. requires a unique largest `AADT_OverlapLengthFt`
9. if no selected row exists after the join path, fills the row as `AADT_Status = no_candidate` and `AADT_Reason = no_aadt_intersection`

Tie-breaking is therefore:

- exact route support first
- positive numeric `AADT`
- latest non-null `AADT_YR`
- unique best `AADT_OverlapLengthFt`
- no `AADT_QUALITY` ranking

### Current source diagnostics

- approach rows: `178`
- AADT rows: `677,597`
- approach-row CRS: `EPSG:3968`
- AADT CRS after load: `EPSG:3968` equivalent Virginia Lambert definition
- approach geometry valid/non-empty: `178 / 178`
- AADT geometry valid/non-empty: `677,597 / 677,597`
- approach geometry type: `LineString`
- AADT geometry type: `MultiLineString`

### Where candidates drop to zero

The failure is not at CRS, schema, or route normalization.

Candidate path counts:

- approach rows with any AADT bounding-box hit before route filtering: `178`
- bounding-box candidate pairs before route filtering: `2,052`
- approach rows with route-supported bounding-box hits: `177`
- route-supported bounding-box candidate pairs: `613`
- approach rows with exact geometry `intersects` hits before route filtering: `127`
- exact geometry `intersects` candidate pairs before route filtering: `341`
- approach rows with route-supported exact geometry `intersects` hits: `12`
- route-supported exact geometry `intersects` candidate pairs: `15`
- route-supported candidate pairs with positive overlap length: `0`

Exact line-line intersection geometry types:

- all exact intersections: `337 Point`, `4 MultiPoint`
- route-supported exact intersections: `11 Point`, `4 MultiPoint`

That means the drop to zero occurs at the exact overlap step. The current implementation only gets point or multipoint touches/crossings, never shared line overlap.

### What did not cause the failure

- not a CRS mismatch
- not empty or invalid AADT geometry
- not empty or invalid approach-row geometry
- not broad route-name mismatch

Representative route checks:

- prototype route names are present in AADT `RTE_NM` and `MASTER_RTE_NM`
- example route names present on both sides include:
  - `R-VA SR00006WB`
  - `R-VA SR00156NB`
  - `R-VA SR00234NBBUS001`
  - `R-VA SR00337EB`
- no example prototype route names were missing from both AADT route fields in the checked sample

Representative failed route-supported pairs:

- `signal_1009` / `StudyRoad_RowID 4224`: nearest route-supported AADT geometry about `1.2057 ft` away
- `signal_1014` / `StudyRoad_RowID 14729`: nearest route-supported AADT geometry about `1.2989 ft` away
- `signal_1088` / `StudyRoad_RowID 7110`: nearest route-supported AADT geometry about `2.0105 ft` away
- `signal_1112` / `StudyRoad_RowID 13696`: nearest route-supported AADT geometry about `0.8541 ft` away
- `signal_1155` / `StudyRoad_RowID 2943`: nearest route-supported AADT geometry about `0.0044 ft` away
- `signal_1115` / `StudyRoad_RowID 13696`: nearest route-supported AADT geometry distance `0.0 ft`, but the exact intersection geometry is still point-only rather than shared line overlap

### Root cause

The zero-candidate result is caused by geometry non-overlap under the documented exact-overlap rule.

In practice, the current approach-row geometry and the normalized AADT linework are near each other and sometimes intersect at points, but they do not share measurable line overlap. The implementation therefore produces no candidates even when route support exists.

### Contract comparison

The implementation matches the current documented contract in practice. It is not looser than the contract, and the main failure is not an implementation bug.

The real issue is that the documented exact overlap rule is too strict for the current source geometry combination if the goal is to obtain usable AADT matches.

### Smallest justified correction

Do not relax the AADT selection behavior in this module without a contract change.

The minimally justified correction is:

- keep the current AADT selection behavior unchanged
- add explicit diagnostics so the zero-candidate result is explained as exact geometry non-overlap rather than an unspecified “no intersection” outcome
- leave broader AADT matching changes unresolved until the docs explicitly authorize a different spatial support rule

## StudyAreaID diagnosis

### Source behavior

`work/output/upstream_downstream_prototype/tables/current/signal_study_area_summary__approach_shaped.csv` currently has:

- total rows: `303`
- unique `StudyAreaID`: `163`
- duplicated rows: `280`
- duplicated `StudyAreaID` values: `140`
- duplicate group size distribution: every duplicated `StudyAreaID` appears exactly twice

Duplicated `StudyAreaID` cases:

```text
signal_1007, signal_1009, signal_1010, signal_1011, signal_1014, signal_1088, signal_1089, signal_1115, signal_1155, signal_1156, signal_1161, signal_1244, signal_1289, signal_1299, signal_1302, signal_1305, signal_1347, signal_1348, signal_1369, signal_1373, signal_1379, signal_1384, signal_1399, signal_1400, signal_1401, signal_1403, signal_1404, signal_1407, signal_1408, signal_1455, signal_1460, signal_1485, signal_1523, signal_1526, signal_1538, signal_1549, signal_1569, signal_1572, signal_1587, signal_1592, signal_1600, signal_1606, signal_1626, signal_1657, signal_1677, signal_1691, signal_1694, signal_1697, signal_1726, signal_175, signal_1756, signal_177, signal_178, signal_1782, signal_1784, signal_1785, signal_1789, signal_179, signal_1790, signal_1791, signal_1795, signal_180, signal_1804, signal_1831, signal_1832, signal_1833, signal_1846, signal_1869, signal_1872, signal_1874, signal_1905, signal_1906, signal_1914, signal_1932, signal_1976, signal_1977, signal_1980, signal_1993, signal_209, signal_210, signal_211, signal_212, signal_218, signal_226, signal_227, signal_228, signal_245, signal_247, signal_256, signal_281, signal_282, signal_286, signal_303, signal_417, signal_418, signal_419, signal_422, signal_451, signal_452, signal_453, signal_460, signal_494, signal_497, signal_504, signal_505, signal_511, signal_512, signal_520, signal_521, signal_532, signal_577, signal_578, signal_643, signal_698, signal_699, signal_749, signal_815, signal_816, signal_817, signal_82, signal_83, signal_830, signal_831, signal_832, signal_833, signal_835, signal_84, signal_865, signal_871, signal_886, signal_890, signal_894, signal_916, signal_917, signal_919, signal_923, signal_939, signal_940, signal_958, signal_962
```

### Field agreement and disagreement

Fields that agree across all duplicate groups:

- `Signal_RowID`
- `REG_SIGNAL_ID`
- `SIGNAL_NO`
- `SignalLabel`
- `SignalRouteName`

Fields that differ across many duplicate groups:

- `FlowDirectionUsed`: `140` groups
- `FlowProvenanceUsed`: `140` groups
- `StudyAreaCrashCount`: `131` groups
- `UpstreamCrashCount`: `114` groups
- `DownstreamCrashCount`: `108` groups
- `UnresolvedCrashCount`: `122` groups
- `HighAttachmentCount`: `132` groups
- `MediumAttachmentCount`: `5` groups
- `AmbiguousSignalCount`: `9` groups

There were no conflicting identifier groups. The duplication is therefore not a key conflict.

### What the current module is doing

`_build_signal_study_area_context_base()` currently:

1. detects duplicate `StudyAreaID`
2. verifies that the identifier fields above do not conflict
3. collapses each duplicated `StudyAreaID` to one row by:
   - keeping the first non-null `FlowDirectionUsed`
   - keeping the first non-null `FlowProvenanceUsed`
   - summing all prototype count fields

### What the duplicates appear to be

The duplicates behave like an upstream additive partition artifact rather than exact duplicates.

Evidence:

- every duplicate group is a 2-row pair
- identifier fields are stable
- summed `StudyAreaCrashCount` matches the crash-classification row count for `140 / 140` duplicated `StudyAreaID` values
- summed `UnresolvedCrashCount` matches unresolved crash rows for `140 / 140`
- summed `HighAttachmentCount` matches high-attachment crash rows for `140 / 140`
- summed `MediumAttachmentCount` matches medium-attachment crash rows for `140 / 140`
- summed `AmbiguousSignalCount` matches crash-classification ambiguous-signal rows for only `131 / 140`, so that field is not fully explained by the available evidence

This means the source CSV is not truly a one-row-per-study-area summary. It is a partially partitioned summary that the downstream module must collapse if it needs one row per `StudyAreaID`.

### Assessment of the current collapse

The current collapse is acceptable for this bounded module, but it should be treated as an explicit repair of an upstream source artifact, not as proof that the source summary is well-formed.

The current count summation is justified by the crash-row reconciliation above. The earlier “conservative collapse” language was incomplete because the additive pattern is now evidenced.

### Smallest justified correction

Keep the one-row-per-`StudyAreaID` collapse in the module, but tighten and surface it:

- require duplicate groups to remain exactly paired
- keep failing if identifier fields conflict
- keep summing prototype count fields
- keep preferring the non-null `FlowDirectionUsed` and `FlowProvenanceUsed`
- report the duplicate structure explicitly in validation and run metadata

Do not invent a hidden partition semantics beyond what the evidence supports, and do not rewrite the upstream prototype summary in this task.

## Final disposition

### AADT

- root cause: exact geometry non-overlap under the documented rule
- issue location: contract plus current source geometry combination, not CRS and not a route-name bug
- correction in this task: diagnostics/reporting only
- unresolved unless stronger evidence exists: any relaxed or alternative AADT spatial support rule

### StudyAreaID duplication

- root cause: upstream summary artifact with additive paired rows per `StudyAreaID`
- issue location: source artifact, not an identifier-key conflict in this module
- correction in this task: tighter validation/reporting while keeping the bounded collapse
- unresolved unless stronger evidence exists: exact upstream semantics for the paired rows, especially `AmbiguousSignalCount`
