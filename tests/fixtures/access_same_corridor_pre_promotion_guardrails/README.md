# Access Same-Corridor Pre-Promotion Guardrails

This fixture freezes the validated prototype outputs that existed before the reviewed-family same-corridor overlay was promoted into `src.active.context_enrichment`.

The fixture is intentionally separate from `work/output/.../current/` because the historical prototype consumes production context-enrichment outputs. After production promotion, rerunning the prototype against current production could no longer reproduce the original pre-promotion guardrail state.

Frozen guardrails:

- production route-conflict rows before overlay: `288`
- reviewed-family rows evaluated: `66`
- recovered rows: `55`
- recovered unique access points: `52`
- prototype-effective statuses: `matched=110`, `near_signal=16`, `route_conflict=233`, `measure_conflict=3`
- signal/study areas with access-count changes: `18`
- approach rows with access-count changes: `18`
- max signal/approach-row count delta: `9`

`manifest.json` records byte counts and SHA-256 hashes for the fixture files. The unit tests validate the manifest so accidental fixture replacement is visible.
