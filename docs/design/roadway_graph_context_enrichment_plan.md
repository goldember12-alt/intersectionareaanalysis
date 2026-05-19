# Roadway Graph Context Enrichment Plan

**Status: DESIGN PLAN.** This is a bounded implementation design for adding access-point and posted-speed context to the stable roadway_graph directional assignment prototype. It does not implement joins, change workflow commands, or create a new output contract yet.

## Bounded Question

How should access-point and posted-speed context be attached to the stable roadway-derived signal/crash/bin universe without changing the roadway scaffold, crash assignment, directional catchments, or upstream/downstream interpretation?

This phase is context enrichment only. It supports descriptive downstream functional area analysis and proposal-facing exploratory summaries. It is not a policy-ready downstream functional area calculator, a crash-rate model, or a recovery path for blocked directional records.

## Source Methodology Alignment

This design follows the active trust hierarchy:

- `docs/methodology/roadway_graph_methodology.md`: roadway scaffold first; access, speed, AADT, median, and crash evidence attach only after the scaffold is clean.
- `docs/methodology/overview_methodology.md`: graph-first Step 5 workflow; crashes and context are delayed until after roadway scaffold QA.
- `docs/methodology/proposal_alignment_growth_plan.md`: controlled growth from roadway scaffold to downstream-zone crash/access/AADT/speed/median summaries before comparison-ready modeling.
- `docs/workflow/roadway_graph_directional_context_milestone.md`: current stable roadway-derived directional-bin context universe and 0-2,500 ft analysis boundary.
- `docs/archive/20260519_cleanup/enrichment_plan.md`: supporting historical access/AADT enrichment guardrails, especially conservative access matching and explicit unresolved-case handling.
- `docs/archive/20260519_cleanup/proposal_facing_distance_band_family_design_002.md`: historical descriptive band design note; descriptive bands are comparison aids, not design-distance claims.

## Current Stable Universe

The stable universe is the roadway_graph directional assignment prototype, not the older signal-centered context enrichment output.

Current stable scaffold and catchment universe:

| Metric | Count |
| --- | ---: |
| prototype usable TRUE reference signals | 976 |
| prototype usable directional records | 4,828 |
| prototype usable directional bins | 208,340 |
| catchments created | 208,340 |
| usable catchments | 200,061 |
| unstable/review catchments | 7,281 |
| blocked catchments | 998 |

Current crash-assignment universe:

| Metric | Count |
| --- | ---: |
| normalized crash points considered | 379,272 |
| unique assigned crashes | 17,634 |
| ambiguous crashes kept separate | 1,055 |
| unresolved crashes kept separate | 360,583 |
| assigned downstream crashes | 8,791 |
| assigned upstream crashes | 8,843 |
| assigned divided physical crashes | 4,967 |
| assigned undivided pseudo-direction crashes | 12,667 |

Current readiness windows:

| Window | Count | Use |
| --- | ---: | --- |
| `core_0_500ft` | 5,767 | safest first descriptive subset |
| `standard_0_1000ft` | 9,170 | high-priority descriptive subset |
| `extended_0_2500ft` | 13,216 | cumulative sensitivity ceiling |
| 1,000-2,500 ft sensitivity increment | 4,046 | sensitivity only |
| over 2,500 ft | 4,418 | review-only or assignment-only |
| over 5,000 ft | 2,513 | long-distance review only |

The enrichment universe includes only:

- TRUE reference signals represented in the prototype usable directional surface;
- usable directional records from `directional_scaffold_prototype_usable_segments.csv`;
- usable directional bins from `directional_scaffold_prototype_usable_bins_50ft.csv`;
- usable catchments from `directional_bin_catchment_index.csv` / `directional_bin_catchment_polygons.geojson`;
- uniquely assigned crashes from the directional catchment assignment prototype;
- readiness-window classifications from `crash_directional_assignment_analysis_readiness`.

The enrichment universe excludes:

- ambiguous crash-to-catchment matches;
- unresolved crashes;
- blocked, unstable, review-only, low-confidence recovery, and unknown-role directional records;
- blocked or unstable catchments;
- crash direction fields;
- crash-derived scaffold, catchment, or assignment repair.

## Analysis Windows

Context outputs should preserve these fixed analysis windows:

| Window | Interpretation |
| --- | --- |
| 0-1,000 ft | high-priority descriptive window |
| 1,000-2,500 ft | sensitivity window |
| >2,500 ft | review-only / assignment-only |

The context phase may also carry 50-foot bin detail and the existing `core_0_500ft` readiness window for continuity. Any output used for proposal-facing descriptive summaries should distinguish 0-1,000 ft from the 1,000-2,500 ft sensitivity increment. Rows beyond 2,500 ft should stay visible for QA and review, but they should not enter high-priority or sensitivity descriptive counts unless a later method explicitly accepts them.

## Context Enrichment Goals

### Signal-Level Context

Create one reference-signal row that summarizes the context available across its usable directional records and windows.

Expected signal-level fields:

- reference signal identifiers and source signal fields;
- represented directional segment count;
- represented directional bin count by window;
- unique assigned crash count by window and `signal_relative_direction`;
- access count and density by window and direction;
- distance to nearest matched access point by direction and window;
- assigned speed summary and speed match status;
- counts of missing, ambiguous, and conflict context records.

### Directional Segment Context

Create context fields inherited by each usable reference directional segment.

Expected segment-level fields:

- `reference_signal_id`;
- `reference_directional_segment_id`;
- `signal_relative_direction`;
- `roadway_representation_type`;
- source roadway route/measure fields where available;
- far anchor type;
- segment length and bin count;
- speed assignment status and selected speed;
- access count and density across the segment and by analysis window.

### Bin-Level Context

Create one row per usable directional bin, with context attached at the 50-foot-bin level.

Expected bin-level fields:

- `reference_directional_bin_id`;
- parent reference signal and directional segment IDs;
- bin start/end from reference signal;
- analysis window classification;
- access count within the bin;
- nearest access distance within the bin/window where applicable;
- inherited speed and speed status;
- assigned crash count by unique crash assignment.

### Crash-Assignment-Level Context

Create one row per uniquely assigned crash with inherited context from its assigned bin and parent segment.

Expected crash-context fields:

- `crash_id`;
- `reference_signal_id`;
- `reference_directional_segment_id`;
- `reference_directional_bin_id`;
- `signal_relative_direction` inherited from the matched catchment;
- distance from reference signal and analysis window;
- inherited speed fields;
- bin-level access count and nearest access distance;
- signal-level access/speed summary fields needed for filtering.

Ambiguous and unresolved crashes should remain in separate QA/readout files, not silently merged into the unique-assignment table.

## Access Point Data Plan

### Expected Source Files

Primary expected source:

- `artifacts/normalized/access.parquet`

Expected source fields based on the historical enrichment contract:

- `id`
- `_rte_nm`
- `_m`
- `NUMBER_OF_APPROACHES`
- `ACCESS_CONTROL`
- `ACCESS_DIRECTION`
- `COMMERCIAL_RETAIL`
- `RESIDENTIAL`
- `INDUSTRIAL`
- `GOV_SCHOOL_INSTITUTIONAL`
- `TURN_LANES_PRIMARY_ROUTE`
- geometry

Stage A must verify actual schema, CRS, row count, null rates, route/measure field usability, duplicate `id` behavior, and whether the access geometry is point-like.

### Join Method

The first graph-first access join should be spatial-first against the stable directional catchment/bin surface, with route/measure support retained as evidence rather than as a scaffold-changing rule.

Recommended candidate generation:

1. Load usable directional catchments in `EPSG:3968` using `directional_bin_catchment_crs_metadata.json`.
2. Load normalized access points and project them to the catchment CRS.
3. Keep access points intersecting exactly one usable directional catchment as direct bin candidates.
4. Preserve access points intersecting multiple usable catchments as `ambiguous`.
5. Preserve access points intersecting no usable catchment but lying within a small review distance from a usable catchment as `near_unmatched_review`.
6. Carry source route and measure support fields for QA, conflict diagnosis, and later review.

Do not use access points to alter catchments, extend segments, choose far anchors, recover blocked records, or decide upstream/downstream.

### Distance-To-Bin And Count Logic

The first implementation should support both point-level and aggregate access context.

Point-level fields:

- `access_point_id`
- `reference_signal_id`
- `reference_directional_segment_id`
- `reference_directional_bin_id`
- `signal_relative_direction`
- `access_distance_from_reference_signal_ft`
- `access_analysis_window`
- `access_assignment_status`
- `access_assignment_reason`
- source route/measure fields

Bin-level fields:

- `access_count_total`
- `access_count_by_type_fields_available`
- `access_nearest_distance_from_bin_center_ft`
- `access_nearest_distance_from_reference_signal_ft`
- `access_status`
- `access_reason`

Window-level and signal-level counts:

- count access points in 0-1,000 ft;
- count access points in 1,000-2,500 ft;
- keep >2,500 ft access points review-only;
- compute access density per 1,000 ft only where denominator length is explicit and nonzero.

Access points near bin boundaries should not be duplicated into multiple bins unless a later design explicitly chooses a repeated-band representation. The default should require a unique bin assignment for counts and keep multi-bin overlaps as ambiguous.

### Side And Direction Considerations

Divided physical records and undivided pseudo-direction records need different interpretation safeguards:

- Divided physical catchments: access points inside a divided physical catchment can be counted against that directional physical record, but route/measure and side evidence should be reported because frontage roads, ramps, or wrong-carriageway points may be nearby.
- Undivided pseudo-direction catchments: access points may fall on one pseudo-direction side of a shared centerline catchment. This is a spatial side assignment for context only, not proof of traffic movement or access operation.
- Near-signal access points should be explicitly flagged when they are within a defined threshold of the reference signal. The threshold should be chosen during Stage A/B after reviewing bin geometry and prior `65.6 ft` near-signal behavior from the historical enrichment workflow.
- `ACCESS_DIRECTION`, if populated, may be carried as context and QA evidence. It must not decide signal-relative direction in the first implementation.

### Access QA Outputs

Minimum QA readouts:

- source access row count, geometry-valid count, CRS, and duplicate `id` count;
- access points intersecting usable catchments;
- access points with unique, ambiguous, no-match, and near-unmatched-review status;
- counts by analysis window and `signal_relative_direction`;
- counts by roadway representation type;
- source route/measure completeness;
- route/measure agreement diagnostics where roadway/source segment IDs or route fields are available;
- top repeated route-conflict or geometry-conflict families for manual review;
- mapped review layer of ambiguous, near-unmatched, and high-impact access points.

## Speed Data Plan

### Expected Source Files

Primary expected source:

- `artifacts/normalized/speed.parquet`

Historical speed context also used:

- raw `postedspeedlimits.gdb`, layer `SDE_VDOT_SPEED_LIMIT_MSTR_RTE`
- standard slice output `work/output/stage1b_study_slice/Study_Signals_SpeedContext.parquet`

Expected normalized speed fields from existing code references:

- `EVENT_SOURCE_ID`
- `ROUTE_COMMON_NAME`
- `LOC_COMP_DIRECTIONALITY_NAME`
- `ROUTE_FROM_MEASURE`
- `ROUTE_TO_MEASURE`
- `CAR_SPEED_LIMIT`
- `TRUCK_SPEED_LIMIT`
- source GDB/layer fields where preserved
- geometry

Stage A must verify actual schema, CRS, row count, null rates, geometry type, and whether route/measure systems align with the roadway graph segment fields.
If `speed.parquet` is not present in the working tree, Stage A should trace whether posted-speed data must be restaged from `postedspeedlimits.gdb` or whether an existing signal-level speed context artifact is available only as historical support.

### Join Method

The first speed join should attach posted-speed context to usable directional segments and bins without changing bin geometry or directional assignment.

Recommended candidate generation:

1. Use usable directional segment geometry as the primary join unit.
2. Generate speed candidates by spatial proximity/intersection between speed segments and directional segment geometry.
3. Use route/common-name and measure overlap as supporting filters when available.
4. Select a speed only when a unique best candidate is supported by geometry plus route/measure evidence or by a documented fallback rule.
5. Mark ties, missing values, low/invalid speeds, and conflicting speeds as explicit statuses.

The historical signal-nearest speed output may be used as comparison or fallback evidence only after Stage A confirms that its signal-level semantics fit the graph-first directional segment universe. It should not override segment/bin-level evidence silently.

### Segment/Bin Inheritance

Preferred inheritance:

- choose or summarize speed at the directional segment level;
- inherit selected speed and speed status to all child bins;
- copy inherited speed to unique crash rows through the assigned bin;
- aggregate speed to signal context as a distribution, not just one scalar, when multiple directional records for a signal have different speeds.

Candidate selected fields:

- `assigned_speed_mph`
- `speed_assignment_status`
- `speed_assignment_reason`
- `speed_source_id`
- `speed_source_route_common_name`
- `speed_source_directionality`
- `speed_source_from_measure`
- `speed_source_to_measure`
- `speed_overlap_length_ft`
- `speed_local_geometry_distance_ft`
- `speed_candidate_count`

Do not use speed to redefine the 0-1,000 ft high-priority window or 1,000-2,500 ft sensitivity window. Speed-based bands can be added later as descriptive comparison bands after basic speed context QA is accepted.

### Missing Or Ambiguous Speed Records

Use explicit statuses instead of silent defaults:

- `matched`: one selected speed record with documented support;
- `ambiguous`: multiple candidate speed records remain after the selection rule;
- `missing`: no speed candidate found;
- `invalid_value`: candidate speed exists but speed value is missing, below a documented minimum, or otherwise unusable;
- `fallback_signal_context`: optional later status if the standard slice signal-level speed output is accepted as fallback;
- `unresolved`: processing or schema problem.

If a default speed is needed for a later descriptive band family, it should be a separate derived field with a clear `defaulted` flag. The core context table should preserve the non-defaulted speed status.

### Speed QA Outputs

Minimum QA readouts:

- source speed row count, geometry-valid count, CRS, and key-field completeness;
- directional segments with matched, ambiguous, missing, invalid, fallback, and unresolved speed status;
- speed value distribution for matched records;
- candidate-count distribution;
- selected speed by roadway representation type and signal-relative direction;
- route/measure support rates;
- segment/bin inheritance completeness;
- comparison against `Study_Signals_SpeedContext.parquet` where available, reported as QA only.

## Proposed Output Tables

The first implementation should write grouped current/history outputs under a roadway_graph context enrichment folder, for example:

- `work/output/roadway_graph/analysis/current/context_enrichment/`
- `work/output/roadway_graph/analysis/history/context_enrichment/`
- `work/output/roadway_graph/review/current/context_enrichment/`
- `work/output/roadway_graph/review/history/context_enrichment/`

Proposed current tables:

### `reference_signal_context.csv`

Unit:

- one row per prototype usable TRUE reference signal.

Primary key:

- `reference_signal_id`

Contents:

- signal identifiers;
- directional segment/bin counts;
- unique assigned crash counts by analysis window and direction;
- access counts and densities by analysis window and direction;
- speed summary fields;
- context completeness and QA status fields.

### `directional_bin_context.csv`

Unit:

- one row per usable reference directional bin.

Primary key:

- `reference_directional_bin_id`

Contents:

- parent signal and directional segment IDs;
- bin distance fields and analysis window;
- inherited speed;
- access counts and nearest access fields;
- unique assigned crash count;
- status/reason fields for context completeness.

### `directional_crash_context.csv`

Unit:

- one row per uniquely assigned crash in the stable directional assignment universe.

Primary key:

- `crash_id`

Contents:

- reference signal, segment, and bin IDs;
- inherited roadway-derived direction and readiness window;
- inherited speed;
- bin/signal access context;
- assignment status fields.

Ambiguous and unresolved crash rows should be summarized in QA and may be written as separate review files, but they should not be included as unique rows in this table.

### `context_enrichment_qa.csv`

Unit:

- one row per QA metric or one row per QA group/metric pair.

Primary key:

- `qa_metric_id` or `qa_group` + `qa_metric`

Contents:

- source inventory counts;
- key uniqueness checks;
- join status counts;
- analysis-window counts;
- context completeness rates;
- unresolved/ambiguous/conflict counts;
- explicit statements that scaffold, catchment, assignment, and crash-direction logic were not changed.

Additional useful review files:

- `access_point_context.csv`
- `speed_segment_candidates.csv`
- `access_assignment_candidates.csv`
- `context_enrichment_findings.md`
- `context_enrichment_manifest.json`
- GeoJSON review layers for ambiguous access, near-unmatched access, and speed ambiguity examples.

## Join Key Strategy

Use roadway_graph keys as the primary analytical keys. Source roadway keys are evidence fields, not replacement keys.

Primary keys:

- `reference_signal_id`: stable reference signal ID for TRUE reference-signal rows.
- `reference_directional_segment_id`: stable usable directional segment ID.
- `reference_directional_bin_id`: stable usable directional bin ID.
- `crash_id`: stable crash identifier, expected to map from `DOCUMENT_NBR` unless Stage A finds a better normalized key.

Supporting keys:

- source roadway graph edge/component IDs where available;
- Travelway route and measure fields where available;
- access source `id`, `_rte_nm`, and `_m`;
- speed source `EVENT_SOURCE_ID`, route/common-name, and measure fields.

Key rules:

- never replace a roadway_graph key with route/measure matching;
- enforce uniqueness for signal, directional segment, directional bin, and unique crash rows;
- keep access point rows point-level because one access point may be near multiple signals or bins in review contexts;
- preserve source IDs for traceability and diagnostics;
- write duplicate-key and orphan-key QA checks in every run.

## Methodological Boundaries

Context joins must not:

- alter the roadway scaffold;
- alter directional segment or bin IDs;
- alter catchment geometry or catchment status;
- recover blocked, unstable, review-only, low-confidence recovery, or unknown-role directional records;
- use access points as far anchors or graph-repair evidence;
- use speed to decide upstream/downstream;
- use access data to decide upstream/downstream;
- use crash direction fields;
- use crash distributions to repair assignment;
- move ambiguous or unresolved crashes into the unique-assignment universe;
- make crash-rate, regression, causal, or policy-ready claims.

Context joins may:

- append speed and access context to stable signal/segment/bin/crash rows;
- create descriptive counts for 0-1,000 ft and 1,000-2,500 ft windows;
- preserve >2,500 ft context as review-only;
- create QA review queues for access and speed ambiguity;
- prepare later descriptive summaries after source coverage and unresolved-case rates are reviewed.

## Recommended Implementation Stages

### Stage A: Source Inventory And Schema Audit

Inventory `artifacts/normalized/access.parquet`, `artifacts/normalized/speed.parquet`, and any relevant existing speed context outputs. Confirm schemas, CRS, row counts, geometry validity, key uniqueness, route/measure fields, and source null rates. Produce no analytical join outputs.

### Stage B: Speed Context Join

Attach posted-speed context to usable directional segments and inherit it to bins/crashes. Start with speed because it is segment-like, easier to QA before point-to-bin access matching, and needed for later speed-based descriptive bands.

### Stage C: Access Point Context Join

Attach access points to usable directional bins/catchments with explicit unique, ambiguous, unresolved, and near-unmatched-review statuses. Keep route/measure diagnostics and side/direction caveats visible.

### Stage D: Combined Context Table

Produce `reference_signal_context.csv`, `directional_bin_context.csv`, `directional_crash_context.csv`, and `context_enrichment_qa.csv` from the accepted Stage B/C outputs. Verify that context fields attach without changing stable universe counts.

### Stage E: Descriptive Summaries

Create descriptive summaries only after the combined context tables pass QA. Summaries should focus on 0-1,000 ft high-priority and 1,000-2,500 ft sensitivity windows. Do not create regression-ready outputs or policy distance claims in this stage.

## Open Questions And Risks

- Actual normalized access and speed schemas may differ from historical expectations.
- The current working tree may not contain a normalized posted-speed parquet or signal-level speed-context artifact; Stage A must verify source availability before designing the join rule.
- Access route/measure systems may not align cleanly with Travelway or directional segment route fields.
- Access point geometries may fall on frontage roads, ramps, local entrances, or wrong carriageways near usable catchments.
- Undivided pseudo-direction catchment side assignment is useful context, but it can be misread as operational movement if labels are not explicit.
- Near-signal access thresholds need review before being reused from the older `65.6 ft` rule.
- Posted-speed segments may not match the graph directional segment geometry or route identity at interchanges, frontage roads, or divided carriageways.
- Segment-level speed inheritance may hide within-segment speed changes if a long directional record crosses multiple speed segments.
- Default speed behavior from older workflows should not be copied into the core context table without a visible default flag.
- >2,500 ft rows are assignment-valid but not functionally accepted for descriptive conclusions.
- The first output remains descriptive and exploratory; it is not denominator-reviewed, model-ready, or guidance-ready.
