# Repo Input And Artifact Recovery Audit - 2026-04-28

## Bounded Question

Recover the repo-local raw input layout from the OneDrive layer folder, regenerate the standard staging manifest, and identify remaining active workflow files that are missing or need regeneration.

No production matching, recovery, upstream/downstream, or enrichment logic was changed.

## Raw Layer Recovery

Source folder:

- `C:/Users/Jameson.Clements/OneDrive - Commonwealth of Virginia/Intersection Crash Analysis Layers`

Repo-local raw folder expected by `config/stage1_portable.toml`:

- `Intersection Crash Analysis Layers`

The OneDrive folder was copied into the repo-local raw folder with `robocopy /E /XO`, so missing files were pulled in without deleting existing repo-local files and without replacing newer local files.

Copy result:

- 305 files copied.
- 134 files skipped because they already existed locally.
- 0 failed copies.

## Raw Layer Audit

| Source | Layer | Feature count | CRS | Status |
|---|---|---:|---|---|
| `Travelway.gdb` | `Travelway` | 141,152 | `EPSG:3857` | present/readable |
| `HMMS_Traffic_Signals.gdb` | `HMMS_TrafficSignals_Flat` | 3,153 | `EPSG:4326` | present/readable |
| `Traffic_Signals_-_City_of_Norfolk.gdb` | `Norfolk_Signals` | 592 | `EPSG:2284` | present/readable |
| `Hampton_Analysis.gdb` | `Hampton_Signals` | 188 | `EPSG:2284` | present/readable |
| `crashdata.gdb` | `CrashData_Basic` | 1,076,099 | `EPSG:4326` | present/readable |
| `crashdata.gdb` | `CrashData_Details` | 1,076,099 | none/table | present/readable |
| `postedspeedlimits.gdb` | `SDE_VDOT_SPEED_LIMIT_MSTR_RTE` | 38,723 | `EPSG:3857` | present/readable |
| `New_AADT.gdb` | `New_AADT` | 677,597 | `EPSG:3857` | present/readable |
| `accesspoints.gdb` | `layer_lrspoint` | 70,595 | `EPSG:4326` | present/readable |

The configured optional supplemental file `Intersection Crash Analysis Layers/VDOT_Bidirectional_Traffic_Volume_2024.geojson` is still absent. The configured supplemental shapefile directory `Intersection Crash Analysis Layers/VDOT_Bidirectional_Traffic_Volume_2024 (1)` exists. The current active workflow does not depend on the missing GeoJSON.

## Regenerated Standard Artifacts

The standard package workflow was rerun successfully:

```powershell
.\.venv\Scripts\python.exe -m src bootstrap
.\.venv\Scripts\python.exe -m src stage-inputs
.\.venv\Scripts\python.exe -m src normalize-stage
.\.venv\Scripts\python.exe -m src build-study-slice
.\.venv\Scripts\python.exe -m src enrich-study-signals-nearest-road
.\.venv\Scripts\python.exe -m src check-parity
```

Regenerated standard files:

| Artifact | Status |
|---|---|
| `artifacts/staging/stage1_input_manifest.json` | regenerated |
| `artifacts/staging/roads.parquet` | regenerated |
| `artifacts/staging/signals.parquet` | regenerated |
| `artifacts/staging/crashes.parquet` | regenerated |
| `artifacts/normalized/stage1_normalized_manifest.json` | regenerated |
| `artifacts/normalized/roads.parquet` | regenerated |
| `artifacts/normalized/signals.parquet` | regenerated |
| `artifacts/normalized/crashes.parquet` | regenerated |
| `work/output/stage1b_study_slice/Study_Roads_Divided.parquet` | regenerated |
| `work/output/stage1b_study_slice/Study_Signals.parquet` | regenerated |
| `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet` | regenerated |
| `work/parity/stage1_parity_manifest.json` | regenerated |

`check-parity` passed for the current standard slice. Raw-to-staged row counts, geometry types, CRS, and key fields matched for roads, signals, and crashes. Staged-to-normalized differences were expected reprojection, null-geometry removal, and the 2022-2024 crash-year filter.

## Active Analytical Outputs Refreshed

After regenerating Stage 1, the direct active analytical chain was rerun:

```powershell
.\.venv\Scripts\python.exe -m src.active.directionality_experiment
.\.venv\Scripts\python.exe -m src.active.upstream_downstream_prototype
.\.venv\Scripts\python.exe -m src.active.high_confidence_upstream_downstream_analysis
.\.venv\Scripts\python.exe -m src.active.context_enrichment --run-label regenerated-raw-artifact-audit-20260428
```

Current active outputs exist for:

| Output family | Current run artifact |
|---|---|
| Directionality | `work/output/directionality_experiment/runs/current/run_summary.json` |
| Upstream/downstream prototype | `work/output/upstream_downstream_prototype/runs/current/run_summary.json` |
| High-confidence descriptive slice | `work/output/upstream_downstream_prototype/high_confidence_descriptive_analysis/runs/current/high_confidence_analysis_metadata.json` |
| Context enrichment | `work/output/context_enrichment/runs/current/context_enrichment_run_summary.json` |

The rerun preserved the current post-promotion access baseline:

- `matched`: 129
- `near_signal`: 20
- `measure_conflict`: 3
- `route_conflict`: 210

## Remaining Artifact Notes

No checked active workflow artifact is currently missing.

Two support artifacts are present but were not regenerated by the standard Stage 1 commands:

- `artifacts/normalized/aadt.parquet`
- `artifacts/normalized/access.parquet`

Reason: the current standard staging config marks AADT as optional diagnostic and does not define access as a standard staged input. Context enrichment consumes these two normalized parquet files directly, and they currently match the raw source row counts used by the latest enrichment run:

- AADT rows: 677,597
- Access rows: 70,595

If those two files need to be reproducible from raw inputs rather than preserved as support artifacts, the next bounded implementation should add an explicit support-normalization command or extend the staging contract to include optional support layers without changing production matching logic.

