# Context Enrichment Implementation Memo

**Status: SUPPORTING REFERENCE.** This memo supports the older signal-centered context-enrichment path and remains in place for later graph-first crash/access migration review.

## Exact inputs used

- `work/output/upstream_downstream_prototype/review/geojson/current/approach_rows.geojson`
- `work/output/upstream_downstream_prototype/review/geojson/current/study_areas__approach_shaped.geojson`
- `work/output/upstream_downstream_prototype/review/geojson/current/classified_all.geojson`
- `work/output/upstream_downstream_prototype/review/geojson/current/classified_high_confidence.geojson`
- `work/output/upstream_downstream_prototype/review/geojson/current/signals.geojson`
- `work/output/upstream_downstream_prototype/tables/current/crash_signal_classification__approach_shaped.csv`
- `work/output/upstream_downstream_prototype/tables/current/signal_study_area_summary__approach_shaped.csv`
- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `artifacts/normalized/aadt.parquet`
- `artifacts/normalized/access.parquet`
- `artifacts/normalized/crashes.parquet`

## Exact fields mapped

- `Signal_RowID` and `StudyAreaID` are the authoritative local keys across the bounded slice.
- `StudyRoad_RowID` is the authoritative attached approach-row key.
- `SignalRouteName` is the prototype route name carried from the upstream/downstream outputs.
- `signal_study_area_summary__approach_shaped.csv` is now expected to emit one row per `StudyAreaID` after the upstream paired-row collapse fix.
- `FlowDirection` and `FlowProvenance` come from `study_areas__approach_shaped.geojson`.
- `ApproachLengthMeters` and `AssignedSpeedMph` come from `approach_rows.geojson`.
- `ApproachRoad_FROM_MEASURE` and `ApproachRoad_TO_MEASURE` come from `Study_Roads_Divided.parquet` after joining by `StudyRoad_RowID`.
- classified crashes retain the prototype fields as-is and inherit AADT, access, and rural/urban context from their attached approach row and study area.

## Thresholds chosen

- AADT auto-selection requires exact route support, positive study-road versus AADT measure overlap, local geometry distance `<= 3.0` feet, latest-year preference, and a unique best candidate after support-strength, measure-overlap, and local-distance filtering.
- `AADT_QUALITY` is reported but not ranked because the current repo does not document a trustworthy ordering.
- access route support requires exact normalized match on `ApproachRoad_RTE_NM == _rte_nm`.
- access measure support tolerance is `0.005` miles around the approach-row measure range.
- access point to row distance threshold is `60.0` feet.
- access `near_signal` classification threshold is `65.6` feet.
- exploratory downstream distance bands use fixed `50`-foot bins from the signal within the current approach-shaped study-area length.
- rural/urban dominant class requires at least `3` classified crashes and dominant share `>= 0.67`.

## Additional descriptive outputs

- `access_route_conflict_diagnostics.csv` now provides one row per remaining `route_conflict` row with nearest study-row support, reviewed-family status, and advisory review bucket.
- `access_route_conflict_family_summary.csv` now groups repeated access-route versus study-route conflicts for review prioritization.
- `access_route_conflict_candidates.geojson` now maps the remaining route conflicts and carries the nearest study-row geometry as review evidence.
- `access_assignment_points.csv` now carries signal-relative distance fields and downstream band labels for downstream matched points.
- `classified_crash_context_enriched.csv` now carries signal-relative distance fields and downstream band labels for downstream classified crashes.
- `signal_downstream_distance_band_summary.csv` provides one row per signal and fixed `50`-foot band within the current approach-shaped study area.
- these distance outputs are descriptive only and do not define a final downstream boundary, limiting value, desirable value, or next-signal rule.
- the first manual route-conflict family review batch is documented in `docs/workflow/access_route_conflict_family_review_batch_001.md`.
- the first explicit same-corridor promotion comparison is documented in `docs/workflow/access_route_conflict_promotion_batch_001_comparison.md`.
- the post-promotion closure and upstream/downstream integration check is documented in `docs/workflow/context_enrichment_upstream_downstream_integration_memo.md`.

## Current interpretability guardrails

- access remains exact-route only; semantic aliases such as signed primary-route names versus numbered route keys stay unresolved unless they already match after trim-plus-whitespace normalization
- route-conflict review buckets are diagnostic only; they do not auto-promote unreviewed access-route mismatches
- approach-row access status should report unresolved study-area candidate points as `partial` rather than a generic processing failure when no point can be assigned confidently to that row
- approach rows with no attached classified crashes should carry explicit rural/urban `no_classified_crash_context` output rather than blank fields
- sparse single-class rural/urban evidence below the `3`-crash minimum remains `unresolved`

## Unresolved decisions

- no documented semantic ordering for `AADT_QUALITY`
- no promoted segment-level rural/urban source beyond crash `AREA_TYPE`
- no first-pass use of `EDGE_RTE_KEY`, Oracle linkage, or broader route-family normalization
- no first-pass use of null-heavy descriptive access fields for type interpretation

## Recommended next execution step

Maintain the bounded direct-entry workflow with two active guarantees:

- the upstream prototype summary now emits one row per `StudyAreaID`
- context enrichment uses exact route support plus positive measure overlap and local geometry distance `<= 3.0` feet for conservative AADT matching

Any future AADT expansion should remain within this bounded route-plus-measure-plus-local-support design unless the active workflow docs are revised explicitly.
