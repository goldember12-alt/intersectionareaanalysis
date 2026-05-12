# Context Enrichment Upstream/Downstream Integration Memo

## Bounded Question

Close the current context-enrichment pass and identify the stable post-promotion baseline for the next proposal-facing descriptive analysis phase.

This memo does not add access recovery logic, route normalization, upstream/downstream classification changes, or seed-family promotions. It validates that the existing upstream/downstream workflow can consume the post-promotion enrichment baseline produced from explicit reviewed-family include decisions.

## Closure Run

Commands run on April 28, 2026:

```powershell
.\scripts\bootstrap.cmd
.\.venv\Scripts\python.exe -m src.active.directionality_experiment
.\.venv\Scripts\python.exe -m src.active.upstream_downstream_prototype
.\.venv\Scripts\python.exe -m src.active.high_confidence_upstream_downstream_analysis
.\.venv\Scripts\python.exe -m src.active.context_enrichment --run-label enrichment-integration-closed-post-promotion-001
```

The direct active analytical chain completed successfully using current staged and normalized artifacts.

The standard raw-input package workflow could not be fully rerun from source during this closure pass because `stage-inputs` failed on the missing raw geodatabase path `data/raw/Intersection Crash Analysis Layers/Travelway.gdb`, and `check-parity` failed because `artifacts/staging/stage1_input_manifest.json` is absent. This is an environment/input availability limit, not a context-enrichment logic failure.

## Post-Promotion Baseline Status

Current context-enrichment run label:

- `enrichment-integration-closed-post-promotion-001`

Current access assignment counts:

| Status | Before batch 001 | After closure baseline | Change |
|---|---:|---:|---:|
| `matched` | 110 | 129 | +19 |
| `near_signal` | 16 | 20 | +4 |
| `measure_conflict` | 3 | 3 | 0 |
| `route_conflict` | 233 | 210 | -23 |

Promotion batch 001 changed 23 access-point assignment statuses:

- 19 changed from `route_conflict` to `matched`.
- 4 changed from `route_conflict` to `near_signal`.
- No other access-status class changed.

Promotion batch 001 changed access summaries for 9 signals:

| StudyAreaID | Access total | Upstream before | Upstream after | Downstream before | Downstream after | Near-signal before | Near-signal after | Unresolved before | Unresolved after | Status before | Status after |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `signal_1289` | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | `partial` | `matched` |
| `signal_1299` | 3 | 0 | 0 | 0 | 2 | 0 | 1 | 3 | 0 | `partial` | `matched` |
| `signal_1302` | 2 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 1 | `partial` | `partial` |
| `signal_1305` | 4 | 0 | 1 | 0 | 0 | 0 | 0 | 4 | 3 | `partial` | `partial` |
| `signal_1314` | 4 | 0 | 2 | 0 | 1 | 0 | 0 | 4 | 1 | `partial` | `partial` |
| `signal_1315` | 5 | 0 | 1 | 0 | 3 | 0 | 0 | 5 | 1 | `partial` | `partial` |
| `signal_1316` | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 2 | 1 | `partial` | `partial` |
| `signal_1399` | 6 | 0 | 3 | 0 | 1 | 0 | 1 | 6 | 1 | `partial` | `partial` |
| `signal_1400` | 8 | 0 | 2 | 0 | 2 | 0 | 0 | 8 | 4 | `partial` | `partial` |

Promotion batch 001 did not change signal-level upstream/downstream crash summaries:

- `Prototype_StudyAreaCrashCount`: 0 signals changed.
- `Prototype_UpstreamCrashCount`: 0 signals changed.
- `Prototype_DownstreamCrashCount`: 0 signals changed.
- `Prototype_UnresolvedCrashCount`: 0 signals changed.

This is the expected result because batch 001 only added explicit same-corridor access-route include pairs consumed by existing access matching logic. It did not change flow inference, crash admission, crash attachment, or upstream/downstream crash classification.

## Stable Baseline Outputs

Use these current outputs as the stable baseline for the next proposal-facing descriptive analysis phase:

| Output role | Stable current artifact |
|---|---|
| Approach-shaped signal crash summary | `work/output/upstream_downstream_prototype/tables/current/signal_study_area_summary__approach_shaped.csv` |
| Crash-level upstream/downstream classification | `work/output/upstream_downstream_prototype/tables/current/crash_signal_classification__approach_shaped.csv` |
| High-confidence descriptive crash subset | `work/output/upstream_downstream_prototype/high_confidence_descriptive_analysis/tables/current/high_confidence_by_signal.csv` |
| Enriched signal-level context | `work/output/context_enrichment/tables/current/signal_study_area_context_enriched.csv` |
| Enriched approach-row context | `work/output/context_enrichment/tables/current/approach_row_context_enriched.csv` |
| Enriched classified-crash context | `work/output/context_enrichment/tables/current/classified_crash_context_enriched.csv` |
| Access-point assignment detail | `work/output/context_enrichment/tables/current/access_assignment_points.csv` |
| Descriptive downstream 50-foot bands | `work/output/context_enrichment/tables/current/signal_downstream_distance_band_summary.csv` |
| Enrichment validation summary | `work/output/context_enrichment/review/current/context_enrichment_validation_summary.md` |
| Enrichment run metadata | `work/output/context_enrichment/runs/current/context_enrichment_run_summary.json` |

Use the review GeoJSON layers under `work/output/context_enrichment/review/geojson/current/` for mapped spot checks and presentation support, especially `signal_study_area_context_enriched.geojson`, `approach_row_context_enriched.geojson`, `classified_crash_context_high_confidence.geojson`, and `access_assignment_points.geojson`.

## Interpretation For Next Phase

The closed baseline is suitable for descriptive, proposal-facing summaries within the current divided-road, approach-shaped slice. It supports signal-level and approach-row summaries of upstream/downstream crashes, AADT, access points, crash-context rural/urban evidence, and fixed downstream distance bands.

The baseline is not modeling-ready by itself. Remaining limits include unresolved access route conflicts, crash-context rural/urban classification that is not roadway-level geographic truth, lack of a fully rerun raw-input staging chain in the current environment, and distance bands that are descriptive 50-foot bins rather than final limiting-value or next-signal boundaries.

