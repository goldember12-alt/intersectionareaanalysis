# Context Enrichment Implementation Contract

## Bounded question

How should the current divided-road, signal-centered upstream/downstream outputs be enriched with AADT, access-point, crash-context rural/urban information, and descriptive signal-relative distance outputs without broadening into statewide segment enrichment, Oracle revival, Stage 1C packaging, or legacy crash/access ladders?

This document is the active implementation contract for that bounded slice.
It replaces a conceptual plan with a conservative, implementation-grade specification.

## Scope and posture

- Scope is fixed to the current `approach_shaped` upstream/downstream prototype outputs.
- The enrichment step is post-prototype and post-study-slice. It does not expand the standard Stage 1A CLI slice.
- The first implementation remains direct-entry only.
- The enrichment outputs are signal-centered context products, not a statewide road-segment inventory.
- Exploratory downstream distance bins remain descriptive outputs inside the current approach-shaped study area only. They do not define a limiting value, desirable value, next-signal boundary, or policy distance.
- Crash-rate denominator claims remain out of scope until AADT coverage and ambiguity are reviewed.

## Implementation location and invocation

### Reserved module location

- `src/active/context_enrichment.py`

Keep the first implementation in one active direct-entry module.
Do not add a new package family or Stage 1C-style helper ladder unless the first implementation proves that it is necessary.

### Reserved direct-entry command

```powershell
<bootstrap-reported-python> -m src.active.context_enrichment
```

### Expected arguments for the first implementation

No positional arguments are required for the bounded default run.
The first implementation should support only these optional overrides:

- `--prototype-root`
  Default: `work/output/upstream_downstream_prototype`
- `--study-slice-root`
  Default: `work/output/stage1b_study_slice`
- `--normalized-root`
  Default: `artifacts/normalized`
- `--output-root`
  Default: `work/output/context_enrichment`
- `--run-label`
  Optional label copied into run metadata only

Do not add generalized dataset-selection flags in the first pass.
The implementation question is fixed to:

- study-area type `approach_shaped`
- classified crash source `crash_signal_classification__approach_shaped.csv`
- AADT source `artifacts/normalized/aadt.parquet`
- access source `artifacts/normalized/access.parquet`
- rural/urban source `artifacts/normalized/crashes.parquet`

## Exact source files and exact fields

### Prototype and study-slice sources used

| Source file | Role | Exact fields used |
| --- | --- | --- |
| `work/output/upstream_downstream_prototype/review/geojson/current/approach_rows.geojson` | base approach-row geometry and core row identifiers | `StudyAreaID`, `Signal_RowID`, `REG_SIGNAL_ID`, `SIGNAL_NO`, `SignalLabel`, `SignalRouteName`, `StudyAreaType`, `StudyRoad_RowID`, `ApproachLengthMeters`, `AssignedSpeedMph`, `SpeedAssignmentSource`, geometry |
| `work/output/upstream_downstream_prototype/review/geojson/current/study_areas__approach_shaped.geojson` | signal-study-area geometry and signal-level flow assignment | `StudyAreaID`, `FlowDirection`, `FlowProvenance`, `StudyAreaBufferMeters`, `AssignedSpeedMph`, `ApproachLengthMeters`, `SpeedAssignmentSource`, `ApproachRowCount`, geometry |
| `work/output/upstream_downstream_prototype/review/geojson/current/classified_all.geojson` | mapped crash review geometry for all classified crashes | `Crash_RowID`, `StudyAreaID`, `Signal_RowID`, `StudyRoad_RowID`, `AttachedRoadGeometry`, `SignalGeometry`, `SignalRelativeClassification`, geometry |
| `work/output/upstream_downstream_prototype/review/geojson/current/classified_high_confidence.geojson` | mapped crash review geometry for the highest-confidence subset | same fields as `classified_all.geojson` |
| `work/output/upstream_downstream_prototype/review/geojson/current/signals.geojson` | review-only confirmation of signal-level flow and speed fields | `Signal_RowID`, `StudyAreaID`, `FlowDirection`, `FlowProvenance`, `FlowDirectionUsed`, `FlowProvenanceUsed`, `AssignedSpeedMph`, `ApproachLengthMeters`, geometry |
| `work/output/upstream_downstream_prototype/tables/current/crash_signal_classification__approach_shaped.csv` | authoritative crash-context tabular source | `Crash_RowID`, `DOCUMENT_NBR`, `CRASH_YEAR`, `CrashRouteName`, `CrashRouteMeasure`, `StudyAreaID`, `StudyAreaType`, `Signal_RowID`, `REG_SIGNAL_ID`, `SIGNAL_NO`, `SignalLabel`, `SignalRouteName`, `AssignedSpeedMph`, `ApproachLengthMeters`, `SpeedAssignmentSource`, `StudyRoad_RowID`, `AttachedRoad_RTE_NM`, `AttachedRoad_RTE_COMMON`, `AttachedRoad_FROM_MEASURE`, `AttachedRoad_TO_MEASURE`, `FlowDirection`, `FlowProvenance`, `AttachmentStatus`, `AttachmentMethod`, `AttachmentConfidence`, `CrashToAttachedRowDistanceMeters`, `FlowStatus`, `FlowDirectionUsed`, `FlowProvenanceUsed`, `SignalProjectionMeters`, `CrashProjectionMeters`, `AttachedRowLengthMeters`, `SignalRelativeClassification`, `ClassificationMethod`, `ClassificationReason`, `HasUsableClassification`, `IsUnresolved`, `ClassificationStatus`, `SignalRelativeClass`, `UnresolvedReason` |
| `work/output/upstream_downstream_prototype/tables/current/signal_study_area_summary__approach_shaped.csv` | signal-level prototype counts for validation carry-through; guaranteed one row per `StudyAreaID` after the upstream paired-row collapse fix | `StudyAreaID`, `Signal_RowID`, `REG_SIGNAL_ID`, `SIGNAL_NO`, `SignalLabel`, `SignalRouteName`, `FlowDirectionUsed`, `FlowProvenanceUsed`, `StudyAreaCrashCount`, `UpstreamCrashCount`, `DownstreamCrashCount`, `UnresolvedCrashCount`, `HighAttachmentCount`, `MediumAttachmentCount`, `AmbiguousSignalCount` |
| `work/output/stage1b_study_slice/Study_Roads_Divided.parquet` | authoritative per-row route measure range for AADT and access matching | `RTE_NM`, `FROM_MEASURE`, `TO_MEASURE`, `RTE_ID`, `RTE_COMMON`, `RIM_FACILI`, `RIM_MEDIAN`, geometry |

### Support-layer sources used

| Source file | Role | Exact fields used |
| --- | --- | --- |
| `artifacts/normalized/aadt.parquet` | AADT candidate source | `RTE_NM`, `MASTER_RTE_NM`, `LINKID`, `AADT`, `AADT_YR`, `AADT_QUALITY`, `AAWDT`, `AAWDT_QUALITY`, `DIRECTION_FACTOR`, `DIRECTIONALITY`, `TRANSPORT_EDGE_FROM_MSR`, `TRANSPORT_EDGE_TO_MSR`, `EDGE_RTE_KEY`, `MPO_DSC`, geometry |
| `artifacts/normalized/access.parquet` | access-point candidate source | `id`, `_rte_nm`, `_m`, `NUMBER_OF_APPROACHES`, `ACCESS_CONTROL`, `ACCESS_DIRECTION`, `COMMERCIAL_RETAIL`, `RESIDENTIAL`, `INDUSTRIAL`, `GOV_SCHOOL_INSTITUTIONAL`, `TURN_LANES_PRIMARY_ROUTE`, geometry |
| `artifacts/normalized/crashes.parquet` | crash-context rural/urban source | `DOCUMENT_NBR`, `AREA_TYPE` |

### Exact source fields for the core identifiers requested in this slice

| Needed meaning | Exact source file | Exact source field |
| --- | --- | --- |
| signal row ID | `approach_rows.geojson`, `study_areas__approach_shaped.geojson`, `crash_signal_classification__approach_shaped.csv`, `signal_study_area_summary__approach_shaped.csv` | `Signal_RowID` |
| stable signal/study-area ID | same prototype sources above | `StudyAreaID` |
| route name used by the prototype | `approach_rows.geojson`, `study_areas__approach_shaped.geojson`, `crash_signal_classification__approach_shaped.csv`, `signal_study_area_summary__approach_shaped.csv` | `SignalRouteName` |
| study-area type | `approach_rows.geojson`, `study_areas__approach_shaped.geojson`, `crash_signal_classification__approach_shaped.csv` | `StudyAreaType` |
| attached row ID | `approach_rows.geojson`, `crash_signal_classification__approach_shaped.csv` | `StudyRoad_RowID` |
| flow provenance | `study_areas__approach_shaped.geojson` | `FlowProvenance` |
| assigned direction | `study_areas__approach_shaped.geojson` | `FlowDirection` |
| approach length | `approach_rows.geojson`, `study_areas__approach_shaped.geojson`, `crash_signal_classification__approach_shaped.csv` | `ApproachLengthMeters` |
| assigned speed | `approach_rows.geojson`, `study_areas__approach_shaped.geojson`, `crash_signal_classification__approach_shaped.csv` | `AssignedSpeedMph` |
| geometry references | `approach_rows.geojson`, `study_areas__approach_shaped.geojson`, `classified_all.geojson`, `classified_high_confidence.geojson` | geometry column keyed by `StudyAreaID` and `StudyRoad_RowID` for approach rows, by `StudyAreaID` for study areas, and by `Crash_RowID` for classified crashes; `classified_all.geojson` and `classified_high_confidence.geojson` also preserve `AttachedRoadGeometry` and `SignalGeometry` |

## Output units, keys, and field mappings

### `approach_row_context_base`

Primary key:

- `StudyAreaID`
- `StudyRoad_RowID`

Required output fields and mappings:

| Output field | Source file | Source field | Notes |
| --- | --- | --- | --- |
| `StudyAreaID` | `approach_rows.geojson` | `StudyAreaID` | authoritative local study-area key |
| `Signal_RowID` | `approach_rows.geojson` | `Signal_RowID` | authoritative signal row key |
| `REG_SIGNAL_ID` | `approach_rows.geojson` | `REG_SIGNAL_ID` | preserved external signal identifier |
| `SIGNAL_NO` | `approach_rows.geojson` | `SIGNAL_NO` | preserved when present |
| `SignalLabel` | `approach_rows.geojson` | `SignalLabel` | review label |
| `SignalRouteName` | `approach_rows.geojson` | `SignalRouteName` | prototype route key |
| `StudyAreaType` | `approach_rows.geojson` | `StudyAreaType` | fixed to `approach_shaped` in this slice |
| `StudyRoad_RowID` | `approach_rows.geojson` | `StudyRoad_RowID` | per-approach row key |
| `ApproachLengthMeters` | `approach_rows.geojson` | `ApproachLengthMeters` | speed-informed clipped length |
| `AssignedSpeedMph` | `approach_rows.geojson` | `AssignedSpeedMph` | speed carried from prototype |
| `SpeedAssignmentSource` | `approach_rows.geojson` | `SpeedAssignmentSource` | preserved as-is |
| `FlowDirection` | `study_areas__approach_shaped.geojson` | `FlowDirection` | joined on `StudyAreaID` |
| `FlowProvenance` | `study_areas__approach_shaped.geojson` | `FlowProvenance` | joined on `StudyAreaID` |
| `StudyAreaBufferMeters` | `study_areas__approach_shaped.geojson` | `StudyAreaBufferMeters` | joined on `StudyAreaID` |
| `ApproachRoad_RTE_NM` | `Study_Roads_Divided.parquet` | `RTE_NM` | joined on `StudyRoad_RowID` after resetting row index to `StudyRoad_RowID` |
| `ApproachRoad_RTE_COMMON` | `Study_Roads_Divided.parquet` | `RTE_COMMON` | optional audit field |
| `ApproachRoad_FROM_MEASURE` | `Study_Roads_Divided.parquet` | `FROM_MEASURE` | required for access and AADT measure support |
| `ApproachRoad_TO_MEASURE` | `Study_Roads_Divided.parquet` | `TO_MEASURE` | required for access and AADT measure support |
| `ApproachRoad_RTE_ID` | `Study_Roads_Divided.parquet` | `RTE_ID` | retained for later audit only |
| `ApproachRoad_Facility` | `Study_Roads_Divided.parquet` | `RIM_FACILI` | retained for context-only reference |
| `ApproachRoad_Median` | `Study_Roads_Divided.parquet` | `RIM_MEDIAN` | retained for context-only reference |
| `BaseJoinStatus` | derived | n/a | controlled vocabulary below |
| `BaseJoinReason` | derived | n/a | controlled vocabulary below |

The tabular base file stays non-geometric.
Mapped geometry remains in the review GeoJSON outputs keyed by the fields above.

### `signal_study_area_context_base`

Primary key:

- `StudyAreaID`

Required output fields and mappings:

| Output field | Source file | Source field |
| --- | --- | --- |
| `StudyAreaID` | `signal_study_area_summary__approach_shaped.csv` | `StudyAreaID` |
| `Signal_RowID` | `signal_study_area_summary__approach_shaped.csv` | `Signal_RowID` |
| `REG_SIGNAL_ID` | `signal_study_area_summary__approach_shaped.csv` | `REG_SIGNAL_ID` |
| `SIGNAL_NO` | `signal_study_area_summary__approach_shaped.csv` | `SIGNAL_NO` |
| `SignalLabel` | `signal_study_area_summary__approach_shaped.csv` | `SignalLabel` |
| `SignalRouteName` | `signal_study_area_summary__approach_shaped.csv` | `SignalRouteName` |
| `StudyAreaType` | `study_areas__approach_shaped.geojson` | `StudyAreaType` |
| `FlowDirection` | `study_areas__approach_shaped.geojson` | `FlowDirection` |
| `FlowProvenance` | `study_areas__approach_shaped.geojson` | `FlowProvenance` |
| `FlowDirectionUsed` | `signal_study_area_summary__approach_shaped.csv` | `FlowDirectionUsed` |
| `FlowProvenanceUsed` | `signal_study_area_summary__approach_shaped.csv` | `FlowProvenanceUsed` |
| `StudyAreaBufferMeters` | `study_areas__approach_shaped.geojson` | `StudyAreaBufferMeters` |
| `ApproachLengthMeters` | `study_areas__approach_shaped.geojson` | `ApproachLengthMeters` |
| `AssignedSpeedMph` | `study_areas__approach_shaped.geojson` | `AssignedSpeedMph` |
| `SpeedAssignmentSource` | `study_areas__approach_shaped.geojson` | `SpeedAssignmentSource` |
| `ApproachRowCount` | `study_areas__approach_shaped.geojson` | `ApproachRowCount` |
| `Prototype_StudyAreaCrashCount` | `signal_study_area_summary__approach_shaped.csv` | `StudyAreaCrashCount` |
| `Prototype_UpstreamCrashCount` | `signal_study_area_summary__approach_shaped.csv` | `UpstreamCrashCount` |
| `Prototype_DownstreamCrashCount` | `signal_study_area_summary__approach_shaped.csv` | `DownstreamCrashCount` |
| `Prototype_UnresolvedCrashCount` | `signal_study_area_summary__approach_shaped.csv` | `UnresolvedCrashCount` |
| `Prototype_HighAttachmentCount` | `signal_study_area_summary__approach_shaped.csv` | `HighAttachmentCount` |
| `Prototype_MediumAttachmentCount` | `signal_study_area_summary__approach_shaped.csv` | `MediumAttachmentCount` |
| `Prototype_AmbiguousSignalCount` | `signal_study_area_summary__approach_shaped.csv` | `AmbiguousSignalCount` |

### `classified_crash_context_enriched`

Primary key:

- `Crash_RowID`

Required carried-through source fields:

- all exact fields listed above from `crash_signal_classification__approach_shaped.csv`

Required additional inherited fields:

| Output field | Source file | Source field | Join |
| --- | --- | --- | --- |
| `ApproachRoad_RTE_NM` | `approach_row_context_base` | `ApproachRoad_RTE_NM` | `StudyAreaID` + `StudyRoad_RowID` |
| `ApproachRoad_RTE_COMMON` | `approach_row_context_base` | `ApproachRoad_RTE_COMMON` | `StudyAreaID` + `StudyRoad_RowID` |
| `ApproachRoad_FROM_MEASURE` | `approach_row_context_base` | `ApproachRoad_FROM_MEASURE` | `StudyAreaID` + `StudyRoad_RowID` |
| `ApproachRoad_TO_MEASURE` | `approach_row_context_base` | `ApproachRoad_TO_MEASURE` | `StudyAreaID` + `StudyRoad_RowID` |
| `AADT_*` fields | `approach_row_context_enriched.csv` | selected AADT fields | `StudyAreaID` + `StudyRoad_RowID` |
| `Access_*` aggregate fields | `approach_row_context_enriched.csv` | selected access fields | `StudyAreaID` + `StudyRoad_RowID` |
| `RU_*` signal fields | `signal_study_area_context_enriched.csv` | selected rural/urban summary fields | `StudyAreaID` |

Crash records keep the prototype classification fields unchanged.
The enrichment step appends context.
It does not rewrite upstream/downstream logic.

## AADT selection contract

### Candidate generation

For each `approach_row_context_base` row:

1. Read the non-geometric row from `approach_row_context_base.csv`.
2. Read the geometry for the same `StudyAreaID` + `StudyRoad_RowID` from `review/geojson/current/approach_rows.geojson`.
3. Keep only exact supported-route AADT candidates from `artifacts/normalized/aadt.parquet`.
4. Compute positive measure overlap between:
   `ApproachRoad_FROM_MEASURE` / `ApproachRoad_TO_MEASURE`
   and
   `TRANSPORT_EDGE_FROM_MSR` / `TRANSPORT_EDGE_TO_MSR`.
5. Compute local geometry distance in feet between the approach-row geometry and each same-route, measure-supported AADT geometry.
6. Keep only candidates with local geometry distance `<= 3.0` feet.

### Route-support tiers

Use exact route support only.
Normalize route strings only by trimming ends and collapsing repeated internal spaces.
Do not add broader route-family ladders, direction-flipping rules, Oracle lookups, or legacy bridge logic.

Candidate tiers:

1. `rte_nm_exact`
   `SignalRouteName == RTE_NM`
2. `master_rte_exact`
   `SignalRouteName == MASTER_RTE_NM`
3. `unsupported`
   neither exact route match holds

Only route-supported candidates are eligible for automatic selection in the first pass.
Geometry-only candidates remain review evidence only.

### Selection precedence

Use this exact order:

1. keep only route-supported candidates
2. keep only candidates with positive measure overlap
3. keep only candidates with local geometry distance `<= 3.0` feet
4. keep only candidates with positive numeric `AADT`
5. keep the latest non-null `AADT_YR`
6. prefer the strongest exact route-support tier
7. require a unique largest measure overlap
8. require a unique smallest local geometry distance
9. if step 8 is not unique, mark the row `ambiguous`

### Exact fallback behavior when quality ordering is undocumented

- `AADT_QUALITY` is reported but not used to break ties
- if multiple rule-supported positive-AADT candidates remain after the latest-year, support-tier, measure-overlap, and local-distance filters, do not guess; set `AADT_Status = ambiguous`
- if only exact-route candidates exist but none has positive measure overlap, set `AADT_Status = no_candidate`
- if measure-supported same-route candidates exist but none survives the `<= 3.0` foot local-support threshold, set `AADT_Status = no_candidate`
- if only unsupported candidates exist, do not auto-select from geometry, measure ranges, or proximity alone; set `AADT_Status = no_route_supported_candidate`

### Required AADT output fields on `approach_row_context_enriched.csv`

- `AADT_Value`
- `AADT_Year`
- `AADT_Quality`
- `AADT_SourceRoute`
- `AADT_MasterRoute`
- `AADT_LinkID`
- `AADT_Directionality`
- `AADT_DirectionFactor`
- `AADT_OverlapLengthFt`
- `AADT_OverlapShare`
- `AADT_CandidateCount`
- `AADT_RouteSupportTier`
- `AADT_RouteSupportEvidence`
- `AADT_MeasureOverlapMiles`
- `AADT_LocalGeometryDistanceFt`
- `AADT_SelectionRule`
- `AADT_Status`
- `AADT_Reason`

`AADT_OverlapLengthFt` and `AADT_OverlapShare` remain in the output as legacy-compatible placeholders, but they are not used by the active bounded fallback rule.

### Required signal-level aggregation

- `AADT_MatchedApproachRowCount`
- `AADT_AmbiguousApproachRowCount`
- `AADT_UnresolvedApproachRowCount`
- `AADT_WeightedMean`
- `AADT_Min`
- `AADT_Max`
- `AADT_LatestYear`
- `AADT_MatchShare`

Use `AADT_MeasureOverlapMiles` as the weight for `AADT_WeightedMean`.
Do not compute crash rates in this step.

## Access assignment contract

### Candidate universe

1. read signal-study-area polygons from `study_areas__approach_shaped.geojson`
2. keep only access points whose geometry intersects a study-area polygon
3. attempt assignment only against approach rows from the same `StudyAreaID`

### Exact thresholds

- `ACCESS_MAX_TO_ROW_DISTANCE_FT = 60.0`
  Reason: matches the current prototype's 18-meter approach buffer closely enough to stay within the bounded signal-centered geometry
- `ACCESS_MEASURE_TOLERANCE_MI = 0.005`
  Reason: conservative tolerance around the study-road row measure range without introducing a corridor ladder
- `ACCESS_NEAR_SIGNAL_THRESHOLD_FT = 65.6`
  Reason: matches the current 20-meter signal hub buffer and keeps intersection-adjacent access points out of the upstream/downstream count buckets

### Route-support requirement

Use only exact route support after trim-plus-whitespace normalization:

- `ApproachRoad_RTE_NM == _rte_nm`

There is no first-pass fallback to broader route-name families, Oracle identities, or direction-stripped keys.

### Point assignment rule

An access point may be `matched` to an approach row only when all of the following are true:

- exact route support passes
- projected measure `_m` falls within `ApproachRoad_FROM_MEASURE - 0.005` through `ApproachRoad_TO_MEASURE + 0.005`
- perpendicular distance from the point to the approach-row geometry is `<= 60.0` feet
- a unique best candidate row exists within the study area

If multiple rows satisfy those rules, the point is `ambiguous`.
If exact route support fails, the point is `route_conflict`.
If route support passes but the measure test fails, the point is `measure_conflict`.
If route and measure support pass but the point is farther than `60.0` feet from every candidate row, the point is `too_far`.

### Signal-relative classification rule

After a point is matched to a row:

1. project the signal and the access point onto the same row geometry
2. compute the along-row distance between those projections in feet
3. if the absolute difference is `<= 65.6` feet, assign `near_signal`
4. otherwise use the row `FlowDirection` to classify `upstream` or `downstream`
5. if projection fails or flow is unresolved, assign `unresolved`

### Required point-level output fields

- `Access_PointID`
  Mapped from `artifacts/normalized/access.parquet.id`
- `StudyAreaID`
- `Signal_RowID`
- `StudyRoad_RowID`
- `Access_Route`
  Mapped from `_rte_nm`
- `Access_Measure`
  Mapped from `_m`
- `Access_ToRowDistanceFt`
- `Access_ProjectionFt`
- `Access_SignalProjectionFt`
- `Access_SignalRelativePosition`
- `Access_AssignmentStatus`
- `Access_AssignmentReason`
- `Access_AssignmentRule`

### Required approach-row aggregate fields

- `Access_Count_Total`
- `Access_Count_Upstream`
- `Access_Count_Downstream`
- `Access_Count_NearSignal`
- `Access_Count_Unresolved`
- `Access_Density_Per1000Ft`
- `Access_MatchedRouteShare`
- `Access_AmbiguousCount`
- `Access_Status`
- `Access_Reason`

`Access_Density_Per1000Ft` uses `ApproachLengthMeters * 3.28084 / 1000.0` as the denominator.

## Access route-conflict diagnostics

Route-conflict diagnostics are review outputs only.
They do not change `Access_AssignmentStatus`, same-corridor recovery behavior, or the reviewed family table.

Write:

- `access_route_conflict_diagnostics.csv`
- `access_route_conflict_family_summary.csv`
- `access_route_conflict_candidates.geojson`

Required point-level diagnostic fields:

- `Access_PointID`
- `StudyAreaID`
- `Signal_RowID`
- `Access_Route`
- `NearestStudyRoad_RowID`
- `NearestStudyRoute`
- `NearestStudyRouteCommon`
- `NearestDistanceFt`
- `SignalRouteName`
- `FlowDirection`
- `Access_Measure`
- `NearestRowFromMeasure`
- `NearestRowToMeasure`
- `MeasureCompatibleIfRouteIgnored`
- `ReviewBucket`
- `ReviewPriority`
- `ExistingSameCorridorReviewStatus`
- `ExistingSameCorridorRefusalReason`

Required family-summary fields:

- `AccessRouteNorm`
- `StudyRouteNorm`
- `ConflictPointCount`
- `DistinctSignalCount`
- `MinDistanceFt`
- `MedianDistanceFt`
- `MaxDistanceFt`
- `NearZeroCount`
- `Within5FtCount`
- `Within15FtCount`
- `Within30FtCount`
- `Within60FtCount`
- `HasCurrentReviewedFamily`
- `CurrentReviewDecision`
- `CurrentRefusalRisk`

Diagnostic review buckets:

- `candidate_same_corridor_alias`
- `candidate_direction_variant`
- `candidate_measure_supported_but_unreviewed`
- `likely_cross_street_or_local_access`
- `likely_wrong_carriageway_or_parallel_facility`
- `insufficient_evidence`

No production auto-recovery should happen from these diagnostic buckets alone.
Promotion still requires explicit edits to `docs/workflow/context_enrichment_access_same_corridor_seed_families.csv`.

The first ranked manual review batch is documented in:

- `docs/workflow/access_route_conflict_family_review_batch_001.md`

The first explicit same-corridor promotion comparison is documented in:

- `docs/workflow/access_route_conflict_promotion_batch_001_comparison.md`

The post-promotion enrichment closure and upstream/downstream integration check is documented in:

- `docs/workflow/context_enrichment_upstream_downstream_integration_memo.md`

## Exploratory downstream distance outputs

These outputs are descriptive only.
They use the current approach-shaped study area and the existing signal/point or signal/crash projection fields.
They do not answer the separate proposal question of where the downstream functional area should end.

### Fixed-band family for the current implementation

- `fixed_50ft_from_signal_within_study_area`
- band width: `50` feet
- band extent: from the signal to the current approach-shaped study-area length for that signal
- not used to change AADT matching, access matching, or upstream/downstream classification

### Access distance fields

When an access point has usable row projection support, write:

- `Access_DistanceFromSignalFt`
- `Access_SignalOffsetFt`
- `Access_DownstreamDistanceFt`
- `Access_DistanceBandFamily`
- `Access_DistanceBandStartFt`
- `Access_DistanceBandEndFt`
- `Access_DistanceBandLabel`

Rules:

- `Access_DistanceFromSignalFt` is the absolute along-row projection distance from the signal
- `Access_SignalOffsetFt` is positive for downstream, negative for upstream, and null for `near_signal` or unresolved rows
- downstream band fields populate only when `Access_SignalRelativePosition == "downstream"`
- `near_signal` access points keep their absolute distance field but do not receive a downstream band assignment

### Crash distance fields

When a classified crash has usable signal and crash projections, write:

- `Crash_DistanceFromSignalFt`
- `Crash_SignalOffsetFt`
- `Crash_DownstreamDistanceFt`
- `Crash_DistanceBandFamily`
- `Crash_DistanceBandStartFt`
- `Crash_DistanceBandEndFt`
- `Crash_DistanceBandLabel`

Rules:

- crash distance uses the absolute difference between `SignalProjectionMeters` and `CrashProjectionMeters`
- `Crash_SignalOffsetFt` is positive for downstream and negative for upstream
- downstream band fields populate only when `SignalRelativeClassification == "downstream"`

### Signal-level band summary output

Write one descriptive signal-centered table:

- `signal_downstream_distance_band_summary.csv`

Required fields:

- `StudyAreaID`
- `Signal_RowID`
- `REG_SIGNAL_ID`
- `SIGNAL_NO`
- `SignalLabel`
- `SignalRouteName`
- `StudyAreaApproachLengthFt`
- `DistanceBandFamily`
- `DistanceBandStartFt`
- `DistanceBandEndFt`
- `DistanceBandLabel`
- `DownstreamAccessCount`
- `DownstreamCrashCount`

## Crash-context rural/urban contract

Use crash `AREA_TYPE` only as crash-context evidence.
Do not promote it to a roadway-segment truth field.

### Crash-level mapping

- `Crash_AreaType <- artifacts/normalized/crashes.parquet.AREA_TYPE`
- `Crash_RuralUrbanClass`
  - `rural` when `AREA_TYPE == "Rural"`
  - `urban` when `AREA_TYPE == "Urban"`
  - `unresolved` otherwise
- `Crash_RuralUrbanStatus`
  - `assigned` or `unresolved`

### Approach-row and signal-level aggregation

For a row or signal to receive a dominant class:

- at least `3` classified crashes with non-null mapped rural/urban class must be attached
- one class must have `RU_CrashContext_DominantShare >= 0.67`

Otherwise:

- if both classes are present, set dominant class to `mixed`
- if only one mapped class is present but fewer than `3` classified crashes support it, set dominant class to `unresolved`
- if no classified crashes are attached, set dominant class to `unresolved`

Required signal-level fields:

- `RU_CrashContext_RuralCount`
- `RU_CrashContext_UrbanCount`
- `RU_CrashContext_UnresolvedCount`
- `RU_CrashContext_DominantClass`
- `RU_CrashContext_DominantShare`
- `RU_ContextStatus`
- `RU_ContextReason`

## Status and reason conventions

### Base-table conventions

`BaseJoinStatus`:

- `ready`
- `missing_signal_context`
- `missing_study_road_context`
- `duplicate_key_conflict`
- `unresolved`

`BaseJoinReason`:

- `all_required_joins_present`
- `missing_study_area_join`
- `missing_study_road_join`
- `duplicate_studyarea_row_key`
- `other_join_failure`

### AADT conventions

`AADT_Status`:

- `matched`
- `ambiguous`
- `no_route_supported_candidate`
- `invalid_value`
- `no_candidate`
- `unresolved`

`AADT_Reason`:

- `unique_best_measure_distance_latest_year`
- `tie_after_latest_year_measure_distance_filter`
- `no_exact_route_supported_candidate`
- `all_rule_supported_candidates_invalid_aadt`
- `no_positive_measure_overlap_candidate`
- `no_local_geometry_support_candidate`
- `missing_approach_geometry`

### Access conventions

`Access_AssignmentStatus`:

- `matched`
- `ambiguous`
- `too_far`
- `route_conflict`
- `measure_conflict`
- `near_signal`
- `unresolved`

`Access_AssignmentReason`:

- `unique_route_measure_spatial_match`
- `multiple_rows_passed_thresholds`
- `distance_exceeds_60ft`
- `route_name_not_exact_match`
- `measure_outside_row_range_tolerance`
- `projection_within_65_6ft_of_signal`
- `missing_flow_or_projection`

`Access_Status`:

- `matched`
- `partial`
- `no_candidate_points`
- `unresolved`

`Access_Reason`:

- `all_candidate_points_resolved`
- `contains_ambiguous_or_unresolved_points`
- `no_access_points_in_study_area`
- `other_access_processing_failure`

When a study area contains candidate access points but none can be assigned confidently to a given approach row, prefer `partial` plus `contains_ambiguous_or_unresolved_points` over a generic processing-failure label.

### Rural/urban conventions

`Crash_RuralUrbanStatus`:

- `assigned`
- `unresolved`

`RU_ContextStatus`:

- `assigned`
- `mixed`
- `no_classified_crash_context`
- `unresolved`

`RU_ContextReason`:

- `dominant_share_ge_0_67_with_min3`
- `both_rural_and_urban_present_without_dominance`
- `fewer_than_3_classified_crashes`
- `no_attached_classified_crashes`
- `all_attached_crashes_missing_area_type`

## Output contract

### Grouped output area

- `work/output/context_enrichment/README.md`
- `work/output/context_enrichment/tables/current/`
- `work/output/context_enrichment/tables/history/`
- `work/output/context_enrichment/review/current/`
- `work/output/context_enrichment/review/history/`
- `work/output/context_enrichment/review/geojson/current/`
- `work/output/context_enrichment/review/geojson/history/`
- `work/output/context_enrichment/runs/current/`
- `work/output/context_enrichment/runs/history/`

### Required `tables/current/` filenames

- `approach_row_context_base.csv`
- `approach_row_context_enriched.csv`
- `signal_study_area_context_base.csv`
- `signal_study_area_context_enriched.csv`
- `classified_crash_context_enriched.csv`
- `aadt_match_candidates.csv`
- `access_assignment_points.csv`
- `access_route_conflict_diagnostics.csv`
- `access_route_conflict_family_summary.csv`
- `rural_urban_crash_context_summary.csv`
- `signal_downstream_distance_band_summary.csv`

### Required `review/current/` filenames

- `context_enrichment_methodology.md`
- `context_enrichment_validation_summary.md`

### Required `review/geojson/current/` filenames

- `approach_row_context_enriched.geojson`
- `signal_study_area_context_enriched.geojson`
- `classified_crash_context_high_confidence.geojson`
- `access_assignment_points.geojson`
- `access_route_conflict_candidates.geojson`
- `aadt_ambiguous_rows.geojson`

### Required `runs/current/` filename

- `context_enrichment_run_summary.json`

### Current vs history naming rule

- each successful run writes the stable `current/` filenames and also writes timestamped copies under the matching `history/` folder
- `current/` is the active handoff lane and may be manually cleared by the analyst after review
- `history/` is append-only run retention and should continue to grow over time
- if a stable `current/` file cannot be replaced because of OneDrive or lock behavior, the run should still retain the timestamped `history/` copy and report that `current/` did not receive that artifact

## Minimum review artifacts and minimum validation outputs

### Required review artifacts

At minimum, the first implementation must write:

- `context_enrichment_methodology.md`
- `context_enrichment_validation_summary.md`
- `approach_row_context_enriched.geojson`
- `signal_study_area_context_enriched.geojson`
- `classified_crash_context_high_confidence.geojson`
- `access_assignment_points.geojson`
- `aadt_ambiguous_rows.geojson`

### Minimum validation outputs

`context_enrichment_validation_summary.md` and `context_enrichment_run_summary.json` must both report:

- source row counts for approach rows, study areas, classified crashes, AADT rows, access points, and crash rural/urban source rows
- base-table row counts and duplicate-key checks
- count of approach rows with successful road-range joins
- count of approach rows with exact route-supported AADT candidates
- count of approach rows with positive measure-overlap AADT candidates
- count of approach rows with local-support AADT candidates after the `<= 3.0` foot filter
- count of approach rows with selected AADT
- count of `AADT_Status` by status and reason
- AADT year distribution for selected rows
- AADT quality-code distribution for selected rows
- AADT measure-overlap distribution for selected rows
- AADT local-geometry-distance distribution for selected rows
- count of study areas with at least one selected AADT row
- count of candidate access points clipped to study areas
- count of point-level access assignments by status and reason
- distribution of `Access_ToRowDistanceFt`
- count of `near_signal` access points
- count of approach rows with nonzero access density
- count of route-conflict diagnostic rows
- route-conflict reviewed-family status counts
- route-conflict review-bucket counts
- count of route conflicts within `5` feet and `60` feet of the nearest study row
- count of downstream access points with band assignments
- count of downstream crashes with band assignments
- count of signal-band rows written for the fixed-distance family
- crash `AREA_TYPE` completeness in the normalized crash source
- crash `AREA_TYPE` completeness in the enriched classified-crash output
- rural/urban dominant-class distribution by signal
- at least three mapped spot-check signals, including one with selected AADT, one with ambiguous or unresolved AADT, and one with nonzero matched access counts

## Documentation and repo guidance

This enrichment step stays outside the Stage 1A standard slice.
Do not update `docs/workflow/staging_and_normalization_contract.md` unless AADT or access becomes a required Stage 1A input.

The first implementation must update:

- `docs/workflow/active_workflow.md`
- this file if the accepted implementation deviates from the contract here
- `work/output/context_enrichment/README.md`
- run-generated review docs under `work/output/context_enrichment/review/current/`

## Explicit unresolved items

These are intentionally left unresolved rather than improvised:

- no documented trustworthy ordering for `AADT_QUALITY`, so quality codes are reported but not ranked
- no segment-level rural/urban source beyond crash `AREA_TYPE`
- no first-pass use of `EDGE_RTE_KEY`, Oracle identities, or statewide segment lineage
- no first-pass use of null-heavy descriptive access fields for land-use or access type interpretation

## Not in scope

- statewide or general segment enrichment
- Oracle revival
- Stage 1C packaging
- legacy access/crash ladders
- suburban classification
- weak-support label expansion
- crash-rate denominator claims before AADT validation
- deletion of legacy documentation or legacy artifacts
