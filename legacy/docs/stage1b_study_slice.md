# Stage 1B First Study Slice

This document defines the first bounded Stage 1B runtime slice. It consumes the Stage 1A normalized tier and replaces the earliest legacy runtime steps that produce `Study_Roads_Divided` and `Study_Signals`.

## Command

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m stage1_portable build-study-slice
.\.venv\Scripts\python.exe -m stage1_portable enrich-study-signals-nearest-road
.\.venv\Scripts\python.exe -m stage1_portable enrich-study-signals-speed-context
.\.venv\Scripts\python.exe -m stage1_portable derive-study-signals-functional-distance
.\.venv\Scripts\python.exe -m stage1_portable build-study-signals-buffers
.\.venv\Scripts\python.exe -m stage1_portable build-study-signals-functional-donut
.\.venv\Scripts\python.exe -m stage1_portable build-study-signals-multizone
.\.venv\Scripts\python.exe -m stage1_portable build-road-zone-intersection-raw
.\.venv\Scripts\python.exe -m stage1_portable build-road-zone-preclaim
.\.venv\Scripts\python.exe -m stage1_portable build-road-zone-ownership
.\.venv\Scripts\python.exe -m stage1_portable build-functional-segments-raw
.\.venv\Scripts\python.exe -m stage1_portable build-functional-segments-support
.\.venv\Scripts\python.exe -m stage1_portable build-functional-segments-identity-qc-support
.\.venv\Scripts\python.exe -m stage1_portable build-functional-segments-canonical-road-identity
.\.venv\Scripts\python.exe -m stage1_portable build-functional-segments-link-identity-support
.\.venv\Scripts\python.exe -m stage1_portable build-functional-segments-directionality-support
.\.venv\Scripts\python.exe -m stage1_portable build-functional-segments-oracle-direction-prep
```

## Authoritative Inputs

- `artifacts/normalized/roads.parquet`
- `artifacts/normalized/signals.parquet`

The normalized Stage 1A tier is the authoritative boundary for this slice.

## Outputs

- `artifacts/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `artifacts/output/stage1b_study_slice/Study_Signals.parquet`
- `artifacts/parity/stage1b_study_slice_qc.json`
- `artifacts/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`
- `artifacts/parity/stage1b_signal_nearest_road_qc.json`
- `artifacts/output/stage1b_study_slice/Study_Signals_SpeedContext.parquet`
- `artifacts/parity/stage1b_signal_speed_context_qc.json`
- `artifacts/output/stage1b_study_slice/Study_Signals_FunctionalDistance.parquet`
- `artifacts/parity/stage1b_signal_functional_distance_qc.json`
- `artifacts/output/stage1b_study_slice/Study_Signals_Zone1CriticalBuffer.parquet`
- `artifacts/output/stage1b_study_slice/Study_Signals_Zone2DesiredFullBuffer.parquet`
- `artifacts/parity/stage1b_signal_buffer_qc.json`
- `artifacts/output/stage1b_study_slice/Study_Signals_Zone2FunctionalDonut.parquet`
- `artifacts/parity/stage1b_signal_donut_qc.json`
- `artifacts/output/stage1b_study_slice/Study_Signals_StagedMultiZone.parquet`
- `artifacts/parity/stage1b_signal_multizone_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Road_Segments_Raw.parquet`
- `artifacts/parity/stage1b_road_zone_intersection_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Road_Segments_PreClaim.parquet`
- `artifacts/parity/stage1b_road_zone_cleanup_qc.json`
- `artifacts/output/stage1b_study_slice/Zone_Road_Claims_Owned.parquet`
- `artifacts/parity/stage1b_road_claim_ownership_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Segments_Raw.parquet`
- `artifacts/parity/stage1b_segmented_road_pieces_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support.parquet`
- `artifacts/parity/stage1b_segment_support_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support_IdentityQC.parquet`
- `artifacts/parity/stage1b_segment_identity_qc_support_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad.parquet`
- `artifacts/parity/stage1b_segment_canonical_road_identity_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit.parquet`
- `artifacts/parity/stage1b_segment_link_identity_support_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport.parquet`
- `artifacts/parity/stage1b_segment_directionality_support_qc.json`
- `artifacts/output/stage1b_study_slice/Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport_OraclePrep.parquet`
- `artifacts/parity/stage1b_segment_oracle_direction_prep_qc.json`

## Slice Scope

This bounded slice only does the following:

- filters normalized roads to divided study roads
- loads the canonical normalized signals layer
- filters signals to the divided-road study area using a 20-foot tolerance
- writes open-format outputs
- records a small QC/parity summary

This slice does not assign speed, build zones, segment roads, assign crashes, or continue into later pipeline stages.

The nearest-road enrichment step is the next bounded Stage I step after the initial study-slice filter. It joins each `Study_Signals` feature to the nearest `Study_Roads_Divided` feature, records nearest-road distance, and flags tied nearest-road cases explicitly in QC.

The posted-speed context step is the next bounded Stage I step after nearest-road enrichment. It assigns speed context from the normalized speed layer using the closest speed segment within 150 feet, uses nearest-road route context to break exact nearest ties, and records both the raw matched speed and the cleaned `Assigned_Speed` field without computing functional distances.

The functional-distance step is the next bounded Stage I step after speed-context enrichment. It derives only the signal-level `Dist_Lim` and `Dist_Des` fields from `Assigned_Speed` using the legacy speed-to-distance lookup logic, but does not create any buffers or zones.

The first geometry step is the next bounded Stage I step after functional-distance derivation. It creates only the raw signal-centered buffer products:

- Zone 1 critical buffers from `Dist_Lim`
- Zone 2 full desired-distance buffers from `Dist_Des`

These are pre-dissolve, one-feature-per-signal outputs. They may overlap. This step does not yet create the zone-2-minus-zone-1 donut geometry.

The next bounded geometry step creates the per-signal functional donut geometry as:

- `Study_Signals_Zone2DesiredFullBuffer` minus `Study_Signals_Zone1CriticalBuffer`

This output is also pre-dissolve, one-feature-per-signal, and overlapping is allowed. It is derived strictly from the two prior buffer products and does not interact with roads.

The next bounded geometry step creates the first explicit staged multi-zone geometry set by combining:

- `Study_Signals_Zone1CriticalBuffer`
- `Study_Signals_Zone2FunctionalDonut`

The preferred staged form is a single combined layer with explicit zone labeling. It remains pre-dissolve, overlapping is allowed, and each source signal contributes one feature for each zone class.

The next bounded road-interaction step creates the first raw road-zone intersection output by intersecting:

- `Study_Roads_Divided`
- `Study_Signals_StagedMultiZone`

This output is explicitly raw, pre-cleanup, pre-claim, and pre-segmentation. Multiple rows per road are expected where roads intersect multiple signal-zone geometries.

The next bounded post-intersection step creates a minimally cleaned pre-claim road-zone geometry layer from:

- `Functional_Road_Segments_Raw`

This cleanup step is intentionally narrow. It only performs geometry-usability cleanup needed for a usable pre-claim geometry set:

- repair invalid geometry if needed
- remove null geometry if needed
- remove empty geometry if needed
- remove non-line artifacts if geometry repair produces them
- remove zero-length line artifacts if they exist

This output remains pre-claim and pre-segmentation. It still allows multiple rows per road and overlapping road-zone pieces.

The next bounded ownership step creates a claimed road-zone output from:

- `Functional_Road_Segments_PreClaim`

This slice only assigns one owner to each exact claim piece:

- uncontested pieces keep their single signal owner
- exact duplicate rows for the same signal are deduplicated without being treated as multi-signal contests
- contested multi-signal pieces are assigned with an explicit deterministic ownership rule

This output remains pre-segmentation. It is an ownership result, not a stable segment design.

The next bounded segmentation step creates the first segmented road-piece output from:

- `Zone_Road_Claims_Owned`

In this bounded slice, segmented means:

- each ownership-resolved claim geometry is converted into explicit singlepart line pieces
- `MultiLineString` ownership rows are split into one output row per line part
- `LineString` ownership rows carry forward unchanged

This output is still raw in the sense that no stable segment IDs, crash/access assignments, or downstream aggregation are introduced yet.

The next bounded support-field step creates a minimal enriched segment output from:

- `Functional_Segments_Raw`

This slice adds only the minimum downstream-support geometry attributes that are clearly used later:

- `Seg_Len_Ft`
- `Mid_X`
- `Mid_Y`

The geometry row set remains the same as `Functional_Segments_Raw`.

The next bounded identity/QC-support step creates a minimal post-support audit output from:

- `Functional_Segments_Raw_Support`

This slice adds only the minimum immediate post-support segment audit fields:

- `Segment_RowID_Temp`
- `QC_ShortSegment`

Rules:

- `Segment_RowID_Temp` is an explicit temporary non-stable row helper only for immediate bounded audit/join work
- `Segment_RowID_Temp` must not be treated as stable across reruns, upstream ordering changes, or later cleanup stages
- `QC_ShortSegment` is `1` when `Seg_Len_Ft < 50` and `0` otherwise
- short pieces are flagged, not deleted, in this bounded slice
- the geometry is not modified
- no stable segment-ID design, crash/access assignment, or downstream aggregation is introduced

The next bounded canonical-road-identity step creates a minimal post-support road-lineage output from:

- `Functional_Segments_Raw_Support_IdentityQC`

This slice adds only the minimum direct travelway-lineage canonical road identity fields:

- `RouteID_Norm`
- `RouteNm_Norm`
- `DirCode_Norm`

Rules:

- all three fields are derived only from road lineage already present on the current rows
- `RouteID_Norm` is carried from `RTE_ID`
- `RouteNm_Norm` prefers `RTE_COMMON` and falls back to `RTE_NM`
- `DirCode_Norm` is carried from `LOC_COMP_D`
- `Segment_RowID_Temp` remains temporary and non-stable
- no stable segment ID is introduced
- `LinkID_Norm`, `FromNode_Norm`, `ToNode_Norm`, and `AADT` are not added in this bounded slice
- the geometry is not modified
- no crash/access assignment or downstream aggregation is introduced

The next bounded link-identity-support step creates a minimal post-canonical-road audit output from:

- `Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad`

This slice first checks whether direct link identity is actually present on the current row lineage.

Rules:

- if a direct carried-forward link-id field is present on the current rows, only the minimum explicit normalized link-id support should be added
- if no direct link-id field is present, `LinkID_Norm` must not be fabricated
- in this bounded slice the truthful outcome is an explicit audit result rather than a speculative link-id field
- `LinkID_AuditStatus` records `not_directly_available_from_current_lineage`
- `Segment_RowID_Temp` remains temporary and non-stable
- no stable segment ID is introduced
- no external join, AADT backfill, crash/access assignment, or downstream aggregation is introduced
- the geometry is not modified

The next bounded downstream-directionality-support step creates a minimal post-link-audit support output from:

- `Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit`

This slice does two things only:

- audit whether `FromNode_Norm` / `ToNode_Norm` are directly available from current lineage
- derive the first endpoint-based owned-segment to owned-signal support fields needed for later downstream labeling

Rules:

- `FromNode_Norm` / `ToNode_Norm` must not be fabricated when they are not directly present on current lineage
- `NodeID_AuditStatus` records the direct-lineage audit outcome
- owned signal point geometry is looked up from the existing Stage 1B `Study_Signals` output by `Signal_RowID` only because current segment rows do not carry reliable signal point geometry directly
- endpoint support is geometry-derived only: start/end coordinates, endpoint-to-signal distances, nearer-end label, and ambiguity status
- this is not a final downstream directionality system and does not by itself assign downstream/upstream flow role
- `Segment_RowID_Temp` remains temporary and non-stable
- no stable segment ID, crash/access assignment, or downstream aggregation is introduced
- the geometry is not modified

The next bounded Oracle-direction-prep step creates a minimal post-directionality-support output from:

- `Functional_Segments_Raw_Support_IdentityQC_CanonicalRoad_LinkAudit_DirectionalitySupport`

This slice does three things only:

- explicitly confirms that trustworthy downstream directionality remains Oracle-dependent at this boundary
- adds the minimum row-level Oracle join-readiness and missingness fields
- if repo-local Oracle broad lookup exports are already present, adds only bounded route-candidate coverage support from those exports

Rules:

- this slice does not fabricate `LinkID_Norm`, `FromNode_Norm`, `ToNode_Norm`, `Signal_M`, or `SegMid_M`
- route-only Oracle coverage support does not count as final downstream directionality
- `OracleRouteNm_Candidate` uses raw `RTE_NM`, not `RouteNm_Norm`, because Oracle broad lookup uses `RTE_NM`-style route names while `RouteNm_Norm` was derived from `RTE_COMMON`
- `OracleDirection_Ready` must stay false when required GIS-side Oracle keys are still missing
- `OracleDirection_MissingReason` must state the missing prerequisite set explicitly
- `Segment_RowID_Temp` remains temporary and non-stable
- no stable segment ID, crash/access assignment, or downstream aggregation is introduced
- the geometry is not modified

This Oracle-prep boundary is intentionally preparatory rather than final. The expected continuation is to compare any newly added traffic-volume layer against the AADT source already used by the portable path, determine whether that traffic-volume lineage carries the GIS-side bridge key needed to relate current segment lineage to Oracle `rns.eyroadxx` through `tmslinkid`, and then decide the cleanest insertion point for that bridge key before final downstream directionality is attached. Depending on that outcome, the later Oracle step may need configured live Oracle access in the repo-local open-source path rather than relying only on pre-exported CSVs. Until that bridge path is resolved, route-only Oracle preparation must remain an auditable readiness layer rather than being treated as trustworthy final downstream directionality.

## Speed-To-Distance Rule

The mapping used in this slice is explicit:

- `25` -> `Dist_Lim=155`, `Dist_Des=355`
- `30` -> `Dist_Lim=200`, `Dist_Des=450`
- `35` -> `Dist_Lim=250`, `Dist_Des=550`
- `40` -> `Dist_Lim=305`, `Dist_Des=680`
- `45` -> `Dist_Lim=360`, `Dist_Des=810`
- `50` -> `Dist_Lim=425`, `Dist_Des=950`
- `55` -> `Dist_Lim=495`, `Dist_Des=1100`

Assignment rule:

- round `Assigned_Speed` to the nearest 5 mph
- if that rounded bin is present in the mapping table, use that pair
- if not, fall back to the `35 mph` pair

This preserves the bounded legacy intent for `Dist_Lim` / `Dist_Des` without pulling in any zone-building logic.

## Buffering Rule

The buffering rule used in this slice is explicit:

- each output polygon is centered on the source signal point
- `Dist_Lim` and `Dist_Des` are interpreted as feet
- because the working CRS is `EPSG:3968`, those distances are converted to meters before buffering
- no dissolve is applied
- each output contains one polygon feature per source signal

Outputs:

- `Study_Signals_Zone1CriticalBuffer` uses `Dist_Lim`
- `Study_Signals_Zone2DesiredFullBuffer` uses `Dist_Des`

Donut rule:

- `Study_Signals_Zone2FunctionalDonut` is created by a geometry difference operation
- for each signal, donut geometry = zone 2 full desired-distance buffer minus zone 1 critical buffer
- no dissolve is applied
- the output remains one-feature-per-signal and may overlap across signals

Staged multi-zone rule:

- `Study_Signals_StagedMultiZone` is a single combined layer
- `Zone_Type` carries the zone label:
  - `Zone 1: Critical`
  - `Zone 2: Functional`
- `Zone_Class`, `Zone_SourceOutput`, `Zone_GeometryMethod`, and the zone distance-field metadata preserve traceability
- no dissolve is applied
- the output remains overlapping and effectively one-feature-per-signal-per-zone

Raw road-zone intersection rule:

- `Functional_Road_Segments_Raw` is created with a geometry intersection operation
- roads inherit `Zone_Type`, `Zone_Class`, `Signal_RowID`, and staged zone traceability fields from the multi-zone geometry input
- no cleanup, dissolve, claim logic, or overlap resolution is applied
- multiple rows per road and road-zone overlaps are expected

Minimal pre-claim cleanup rule:

- `Functional_Road_Segments_PreClaim` is created directly from `Functional_Road_Segments_Raw`
- only minimum geometry-usability cleanup is applied
- invalid geometry is repaired before any drops are considered
- null, empty, zero-length, or repaired non-line artifacts are removed only if present
- no claim logic, ownership resolution, overlap resolution, segmentation, or segment-ID stabilization is applied
- the output remains overlapping, pre-claim, and pre-segmentation

Ownership assignment rule:

- `Zone_Road_Claims_Owned` is created directly from `Functional_Road_Segments_PreClaim`
- a claim piece is defined by the same `EVENT_SOUR`, `RTE_ID`, `Zone_Class`, `Zone_Type`, and exact normalized geometry hash
- a piece is contested only when more than one distinct `Signal_RowID` appears in the same claim-piece group
- contested groups are ranked by:
- `EVENT_SOUR == NearestRoad_EVENT_SOUR` first
- `RTE_ID == NearestRoad_RTE_ID` second
- claim-piece-centroid to signal-point distance third
- lowest `Signal_RowID` as the deterministic final tie-break
- dropped candidates are surfaced in QC samples rather than silently dissolved away
- no stable segment IDs or downstream assignment logic are introduced

First segmented road-piece rule:

- `Functional_Segments_Raw` is created directly from `Zone_Road_Claims_Owned`
- the geometry operation is GeoPandas singlepart expansion via `explode`
- the intent is to convert ownership-resolved claim geometries into explicit singlepart downstream road pieces
- multipart splitting is reported explicitly in QC
- null, empty, non-line, or zero-length post-explode artifacts are removed only if they appear
- no stable segment-ID design is introduced in this slice

Minimal segment-support-field rule:

- `Functional_Segments_Raw_Support` is created directly from `Functional_Segments_Raw`
- the geometry is not modified
- `Seg_Len_Ft` stores segment length in feet
- `Mid_X` and `Mid_Y` store the segment midpoint coordinate in working-CRS units
- no stable segment-ID design, crash/access assignment, or downstream aggregation is introduced

## Legacy Reference

The road filter preserves the legacy Stage I analytical intent:

- include divided facilities coded as `2` or `4`
- exclude roads whose median code begins with `1`

The signal study-area filter preserves the legacy intent of keeping signals that intersect the divided-road network within a small tolerance.

## QC Boundary

The QC summary records:

- input and output row counts
- CRS
- geometry types
- null geometry counts
- key field completeness
- signal retention after study-area filtering
- source breakdown for the canonical signal layer
- explicit legacy ArcPy comparison availability status
- nearest-road distance distribution for study signals
- counts and sample cases for tied or ambiguous nearest-road matches
- assigned-speed coverage, null/default counts, and assigned-speed distribution
- counts and sample cases for ambiguous speed-context matches
- non-null coverage and distributions for `Dist_Lim` and `Dist_Des`
- the compact `Assigned_Speed -> Dist_Lim / Dist_Des` mapping table used for the run
- count of rows whose matched speed candidate was beyond 20 feet but still within the 150-foot search radius
- buffer feature counts, geometry type, null geometry count, and source-distance field used
- explicit note that the first geometry outputs are pre-dissolve and may overlap
- carry-forward counts for defaulted speed rows, fallback-to-35-bin rows, and >20ft-but-<=150ft speed matches
- donut feature count, empty-geometry count, and explicit confirmation that it is derived strictly from the two prior buffer outputs
- explicit validation that EPSG:3968 meter units and the feet-to-meter conversion remain correct for all buffer-derived outputs
- staged multi-zone feature counts, counts by zone class, and explicit confirmation of source-signal traceability
- explicit note that the staged layer remains pre-dissolve and overlapping
- raw road-zone intersection feature count, geometry types, unique roads represented, unique signals represented, and zone-class counts
- explicit note that the road-intersection output is pre-cleanup, pre-claim, and may contain multiple rows per road
- exact before/after counts for the minimal pre-claim cleanup step
- rows removed by each cleanup rule
- post-cleanup geometry types and post-cleanup null/empty counts
- explicit note that the cleaned output still remains pre-claim, pre-segmentation, overlapping, and potentially multiple rows per road
- owned-piece count after bounded ownership assignment
- uncontested vs contested piece counts
- contested assignment success count and unresolved count
- contested-case sample rows showing kept and dropped candidate signals
- exact before/after counts for the first segmented road-piece output
- explicit multipart-to-singlepart split accounting
- post-segmentation geometry types and geometry health
- exact before/after counts for the minimal segment-support-field enrichment step
- explicit list of support fields added and their units
- explicit note that the geometry row set remained unchanged
- exact before/after counts for the segment identity/QC-support enrichment step
- explicit note that `Segment_RowID_Temp` is temporary and non-stable
- explicit accounting of short-segment flagged rows using the legacy 50-foot threshold
- explicit note that short pieces are flagged only and not deleted in this slice
- exact before/after counts for the canonical-road-identity enrichment step
- explicit list of canonical road identity fields added and the existing source fields used
- explicit confirmation that `Segment_RowID_Temp` remains temporary/non-stable and that no stable segment ID was introduced
- explicit note that the geometry row set remained unchanged and that direct legacy parity for this exact boundary may be unavailable
- exact before/after counts for the link-identity-support audit step
- explicit statement of whether `LinkID_Norm` was truthfully added or not
- exact evidence for why direct link identity was not available from current lineage when no `LinkID_Norm` is added
- exact before/after counts for the first downstream-directionality-support step
- explicit statement of whether `FromNode_Norm` / `ToNode_Norm` were truthfully added or not
- exact evidence for why node identity was not directly available from current lineage when those fields are not added
- explicit list of endpoint-based directionality-support fields added and what each field means
- summary counts for which endpoint is nearer the owned signal and any ambiguous cases
- explicit note that this layer is only first geometry-derived downstream-directionality support, not the final directionality system
- exact before/after counts for the Oracle-direction-prep step
- explicit statement on whether trustworthy downstream directionality is available at this boundary without Oracle support
- explicit statement on whether bounded Oracle-backed enrichment was actually performed in the slice and what it did
- exact evidence for why final Oracle direction enrichment is still not ready when readiness remains false
- explicit note that route-only Oracle preparation remains transitional when a stronger GIS-side bridge key is still being established
