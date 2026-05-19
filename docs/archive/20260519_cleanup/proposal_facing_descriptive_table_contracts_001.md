# Proposal-Facing Descriptive Table Contracts 001

**Status: CURRENT SUPPORT.** This design/table-contract note remains in place as planning support, not as a current roadway_graph output contract.

## Bounded Purpose

These contracts define the first proposal-facing descriptive table package for the current divided-road, signal-centered workflow.

The tables are designed for exploratory summaries and comparison preparation. They are not regression-ready by themselves, do not support crash-rate claims, and do not define Appendix F guidance.

Generated current tables:

- `work/output/proposal_descriptive/tables/current/signal_context_analysis.csv`
- `work/output/proposal_descriptive/tables/current/signal_band_context_analysis.csv`
- `work/output/proposal_descriptive/tables/current/crash_band_assignment.csv`
- `work/output/proposal_descriptive/tables/current/access_band_assignment.csv`

History copies are written under:

- `work/output/proposal_descriptive/tables/history/`

## `signal_context_analysis.csv`

Unit:

- one row per signal-study-area in `signal_study_area_context_enriched.csv`

Primary key:

- `StudyAreaID`

Current row count:

- `163`

Stable field groups:

- signal identifiers: `StudyAreaID`, `Signal_RowID`, `REG_SIGNAL_ID`, `SIGNAL_NO`, `SignalLabel`
- route and flow context: `SignalRouteName`, `FlowDirectionUsed`, `FlowProvenanceUsed`, `FlowDirection`, `FlowProvenance`
- study-area context: `StudyAreaType`, `StudyAreaBufferMeters`, `ApproachLengthMeters`, `ApproachRowCount`
- speed context: `AssignedSpeedMph`, `SpeedAssignmentSource`
- crash counts: `Prototype_StudyAreaCrashCount`, `Prototype_UpstreamCrashCount`, `Prototype_DownstreamCrashCount`, `Prototype_UnresolvedCrashCount`
- high-confidence crash counts: `HighConfidence_TotalCrashes`, `HighConfidence_UpstreamCrashCount`, `HighConfidence_DownstreamCrashCount`
- AADT context: `AADT_MatchedApproachRowCount`, `AADT_WeightedMean`, `AADT_Min`, `AADT_Max`, `AADT_LatestYear`, `AADT_MatchShare`
- access context: `Access_Count_Total`, `Access_Count_Upstream`, `Access_Count_Downstream`, `Access_Count_NearSignal`, `Access_Count_Unresolved`, `Access_Density_Per1000Ft`, `Access_Status`
- median/facility context: `ApproachRoad_Facility_Values`, `ApproachRoad_Median_Values`, `ApproachRoad_RTE_NM_Values`
- crash-context rural/urban fields: `RU_*`
- readiness flags: `PackageScope`, `AnalysisReadiness`, `GeographicContextCaveat`

Deferred or caveated fields:

- roadway-level rural/suburban/urban truth is not available
- access type, commercial intensity, and trip-generation context are not yet validated for use
- crash rates are not computed

## `signal_band_context_analysis.csv`

Unit:

- one row per signal-study-area and fixed downstream distance band

Primary key:

- `StudyAreaID`
- `DistanceBandFamily`
- `DistanceBandStartFt`
- `DistanceBandEndFt`

Current row count:

- `2,381`

Stable field groups:

- signal identifiers and route context
- fixed 50-foot band fields: `DistanceBandFamily`, `DistanceBandStartFt`, `DistanceBandEndFt`, `DistanceBandLabel`
- downstream counts: `DownstreamAccessCount`, `DownstreamCrashCount`
- signal-level context carried in for filtering: speed, flow provenance, AADT summary, access density, crash-context rural/urban
- readiness flags: `BandReadiness`, `AnalysisReadiness`

Deferred or caveated fields:

- limiting-value and desirable-value bands are not implemented
- speed-based stopping-sight or decision-sight bands are not implemented
- next-signal or operational boundary bands are not implemented

## `crash_band_assignment.csv`

Unit:

- one row per approach-shaped crash record from `classified_crash_context_enriched.csv`

Primary key:

- `Crash_RowID`

Current row count:

- `2,571`

Stable field groups:

- crash and signal identifiers
- signal-relative classification: `SignalRelativeClassification`, `ClassificationStatus`, `SignalRelativeClass`, `UnresolvedReason`
- attachment and flow provenance: `AttachmentStatus`, `AttachmentConfidence`, `FlowDirectionUsed`, `FlowProvenanceUsed`
- distance and band fields: `Crash_DistanceFromSignalFt`, `Crash_SignalOffsetFt`, `Crash_DownstreamDistanceFt`, `Crash_DistanceBand*`
- crash-context rural/urban fields from crash `AREA_TYPE`
- inherited AADT and access aggregate fields
- readiness flags: `PackageScope`, `AnalysisReadiness`

Required unresolved-case behavior:

- unresolved crashes remain in the table
- downstream band fields populate only where downstream classification and projection support exist

## `access_band_assignment.csv`

Unit:

- one row per candidate access point clipped to the current approach-shaped study areas

Primary key:

- `Access_PointID`
- `StudyAreaID`

Current row count:

- `362`

Stable field groups:

- access and signal identifiers
- assignment status: `Access_AssignmentStatus`, `Access_AssignmentReason`, `Access_AssignmentRule`
- signal-relative position: `Access_SignalRelativePosition`
- distance and band fields: `Access_DistanceFromSignalFt`, `Access_SignalOffsetFt`, `Access_DownstreamDistanceFt`, `Access_DistanceBand*`
- reviewed same-corridor evidence fields
- unresolved support fields: `RouteSupportedStudyRoadRowIDs`, `MeasureSupportedStudyRoadRowIDs`, `DistancePassedStudyRoadRowIDs`, `AmbiguousStudyRoadRowIDs`, `SameCorridorSupportedStudyRoadRowIDs`
- readiness flags: `PackageScope`, `AnalysisReadiness`

Required unresolved-case behavior:

- `route_conflict` and `measure_conflict` rows remain in the table
- downstream band fields populate only for downstream assigned access points
- no additional access recovery is implied by this package

## Readiness Classification

Stable descriptive baselines:

- `signal_context_analysis.csv`
- `signal_band_context_analysis.csv`
- `crash_band_assignment.csv`
- `access_band_assignment.csv`

Analysis-ready but not model-ready:

- fixed 50-foot band counts
- signal-level AADT/access/speed summaries
- crash-level and access-level signal-relative assignment fields

Requires future methodology work:

- model-ready dependent and independent variable definitions
- denominator and exposure choices for rates
- rural/suburban/urban roadway-level source
- expanded band families tied to proposal concepts
- validated access type and land-use intensity fields
