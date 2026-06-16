# IntersectionCrashAnalysis

`IntersectionCrashAnalysis` supports context-aware crash analysis for Virginia signalized intersections, with the long-term goal of downstream functional-area guidance.

The repository is now organized around a canonical roadway graph cache and products derived from it. Ordinary analysis should start from the current cache and should not stitch together old branch outputs.

## Current State

- The canonical core cache is built at `work/roadway_graph/analysis/final_dataset_cache/`.
- Lightweight summary and QA products are built at `work/roadway_graph/analysis/final_summaries/`.
- The first development MVP analytical product is built at `work/roadway_graph/analysis/mvp_dataset/`.
- Source-layer preservation has been repaired under `artifacts/normalized/source_layers/`, with documented residuals for measured-geometry handling.
- The active Python package is `src/roadway_graph/`.

## Folder Map

- `artifacts/`: protected staging, normalized, and source-preserving artifacts.
- `src/roadway_graph/`: active package, including builders, audits, patches, QA helpers, and utilities.
- `work/roadway_graph/analysis/final_dataset_cache/`: canonical core cache.
- `work/roadway_graph/analysis/final_summaries/`: compact reporting and QA summaries.
- `work/roadway_graph/analysis/mvp_dataset/`: development MVP lookup/rate product.
- `work/roadway_graph/_index/`: current product indexes.
- `work/roadway_graph/review/`: audit, cleanup, repair, and diagnostic logs.
- `legacy_06152026/`: archived legacy repo material, not active workflow input.

## Do Not Use As Current Inputs

- old `final_leg_corrected_analysis_dataset`
- old `mvp_directional_rate_distribution_dataset`
- old `src/active/roadway_graph`
- old root scripts/tests
- old `work/output` paths

## Method Notes

- Crash direction fields are not used to derive upstream/downstream.
- Directionality is derived and documented in the cache.
- Access assignment is combined-source, spatial-only, and exclusive within signal/approach/direction distance bands.
- Crash assignment is spatial-primary, band-exclusive, equal fractional, and total-preserving.
- Exposure is a daily VMT proxy unless later MVP logic defines final crash-period exposure.

## Lightweight Validation

Use the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m py_compile src\roadway_graph\audit\repo_docs_config_metadata_cleanup.py
.\.venv\Scripts\python.exe -c "import src.roadway_graph; print('import ok')"
```

Inspect cache metadata before using data:

```powershell
Get-ChildItem work\roadway_graph\analysis\final_dataset_cache
Get-ChildItem work\roadway_graph\analysis\final_summaries
Get-ChildItem work\roadway_graph\analysis\mvp_dataset
```

## Distribution Note

The repo is close to zip/distribution readiness after remaining source-package cleanup and validation. Heavy external source layers should remain outside the active repo after artifact preservation is accepted.
