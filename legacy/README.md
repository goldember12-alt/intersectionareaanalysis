# Legacy Preservation Root

This directory is the consolidated preservation area for material that is useful for historical traceability but is not part of the active workflow.

Active docs live under `docs/`. Active code lives under `src/`. Active local staged and normalized intermediates live under `artifacts/`, which is intentionally preserved as an active local artifact area rather than folded into legacy.

## Layout

- `docs/` - archived documentation and recovery audits outside the active docs set.
- `arcpy/` - retired ArcPy-era code and package material.
- `outputs/` - old output snapshots and archive products, kept local-only unless a small manifest is intentionally added later.
- `portability_branch/` - historical portability-branch material.
- `reference/` - historical reference exports and source-discovery material.

Do not import active code from this tree unless a task explicitly re-evaluates and promotes a specific component back into the active workflow.

## 2026-05-12 Consolidation Notes

The active audit kept `artifacts/` in place because current config, workflow docs, and active modules use `artifacts/staging/` and `artifacts/normalized/` as active local staging and normalized-input areas.

The former `docs/legacy/` recovery memos were moved to `legacy/docs/recovery_audits/2026-04-16/` so historical documentation has one preservation root.

The empty residual `Intersection Crash Analysis Layers/layer_summaries/` folder was moved out of the protected raw-input tree after confirming no files were present there and the preserved reference location already existed under `legacy/reference/`.
