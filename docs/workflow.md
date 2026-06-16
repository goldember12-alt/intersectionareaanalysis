# Workflow Summary

Use the cleaned products in this order:

1. Start ordinary analysis from `work/roadway_graph/analysis/final_dataset_cache/`.
2. Use `work/roadway_graph/analysis/final_summaries/` for compact human-readable QA and summaries.
3. Use `work/roadway_graph/analysis/mvp_dataset/` only as the current development MVP product.
4. Use `artifacts/normalized/source_layers/` for source-layer preservation and lineage checks.
5. Use `work/roadway_graph/review/` only for diagnostics, audit evidence, and cleanup logs.

Do not use old branch outputs or old root scripts/tests. The active source package is `src/roadway_graph/`.
