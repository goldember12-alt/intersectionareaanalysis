# AGENTS.md

## Purpose

This file is the operating contract for Codex and other agents working in this repository.

`IntersectionCrashAnalysis` supports Virginia downstream functional-area analysis at signalized intersections. The project preserves roadway, signal, access, crash, speed, AADT, exposure, median, and directionality context in a canonical cache, then builds summaries, MVP products, figures, and tools from that cache.

## Current Canonical Paths

- `work/roadway_graph/analysis/final_dataset_cache/`: canonical core cache.
- `work/roadway_graph/analysis/final_summaries/`: lightweight reporting and QA summaries.
- `work/roadway_graph/analysis/mvp_dataset/`: current development MVP product, not final guidance.
- `artifacts/normalized/source_layers/`: source-preserving parquet artifacts.
- `src/roadway_graph/`: active source package.
- `work/roadway_graph/_index/`: current product indexes.
- `work/roadway_graph/review/`: review, audit, repair, and cleanup logs.
- `legacy_06152026/`: archive only.

## Data Preservation Doctrine

Data preservation is the first rule. Do not delete, move, overwrite, or rewrite data unless the user explicitly authorizes that action. Prefer archive or temp-output workflows for mutations. Preserve unresolved, ambiguous, source-limited, and review-only cases with flags instead of hiding them.

## Canonical-First Rule

For ordinary analysis, figures, tables, lookup work, and tools, start from `final_dataset_cache`. Use `final_summaries` for compact reporting and QA. Use `mvp_dataset` for the current development MVP product.

Review outputs are diagnostics, not data parents. Do not promote review outputs into ordinary analysis unless a task explicitly performs and validates that promotion.

## Prohibited Current Paths

Do not use old final-cache, MVP, source, or output paths as current parents. Do not write to old output folders. Do not recreate staging folders unless explicitly requested by the user.

## Directionality And Crash Doctrine

Crash direction fields must not be used to derive upstream/downstream. Directionality is cache-derived. Crash assignment is spatial-primary, band-exclusive, equal fractional, and total-preserving. Access assignment is combined-source, spatial-only, and exclusive within signal/approach/direction distance bands. Exposure is currently a daily VMT proxy unless later MVP logic defines final crash-period exposure.

## Source And Artifact Doctrine

Raw/source/staging data and `artifacts/` are protected source evidence. Read them only for source audit, lineage, missingness investigation, or refresh design. `artifacts/normalized/source_layers/` is the source-preserving parquet layer.

## Runtime Guidance

Use gated workflows for mutation tasks. Write progress logs for long jobs. Inspect existing logs and manifests before rerunning. Avoid broad reruns when a narrow audit or validation will answer the question.

Use the repository virtual environment for validation:

```powershell
.\.venv\Scripts\python.exe -m py_compile <script>
.\.venv\Scripts\python.exe -m <module>
```

Do not run heavy cache or MVP builders unless the user explicitly asks for that work.

## Final Report Format

Final reports should state files changed, source docs/products read, validation commands run, stale path fragments remaining when relevant, key doctrine changes, unresolved assumptions, and focused `git status --short`.
