# Context Enrichment Implementation Memo

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
- `FlowDirection` and `FlowProvenance` come from `study_areas__approach_shaped.geojson`.
- `ApproachLengthMeters` and `AssignedSpeedMph` come from `approach_rows.geojson`.
- `ApproachRoad_FROM_MEASURE` and `ApproachRoad_TO_MEASURE` come from `Study_Roads_Divided.parquet` after joining by `StudyRoad_RowID`.
- classified crashes retain the prototype fields as-is and inherit AADT, access, and rural/urban context from their attached approach row and study area.

## Thresholds chosen

- AADT auto-selection requires exact route support and a unique best overlap after latest-year filtering.
- `AADT_QUALITY` is reported but not ranked because the current repo does not document a trustworthy ordering.
- access route support requires exact normalized match on `ApproachRoad_RTE_NM == _rte_nm`.
- access measure support tolerance is `0.005` miles around the approach-row measure range.
- access point to row distance threshold is `60.0` feet.
- access `near_signal` classification threshold is `65.6` feet.
- rural/urban dominant class requires at least `3` classified crashes and dominant share `>= 0.67`.

## Unresolved decisions

- no documented semantic ordering for `AADT_QUALITY`
- no promoted segment-level rural/urban source beyond crash `AREA_TYPE`
- no first-pass use of `EDGE_RTE_KEY`, Oracle linkage, or broader route-family normalization
- no first-pass use of null-heavy descriptive access fields for type interpretation

## Recommended next execution step

Implement `src/active/context_enrichment.py` as a direct-entry module that reads the fixed default paths, writes the grouped `work/output/context_enrichment/` contract, and starts with `approach_row_context_base.csv` plus `aadt_match_candidates.csv` before adding access and rural/urban aggregation in the same bounded module.
