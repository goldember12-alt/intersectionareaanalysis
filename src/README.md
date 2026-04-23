`src/` is now bucketed for readability.

Layout:
- `src/active/` = current runnable workflow
- `src/transitional/` = short-term diagnostics still under inspection

Important filesystem note:
- existing root-level files in `src/` are OneDrive reparse-point leftovers
- where possible, the active entrypoint now routes into `src/active/`
- the authoritative sorted copies are the files under `src/active/` and `src/transitional/`

Repo environment bootstrap lives in `scripts/`, not in this package.
Use `.\scripts\bootstrap.cmd` first. `scripts/bootstrap.ps1` remains the implementation, but the wrapper is the default entrypoint because direct `.ps1` execution may be blocked by PowerShell execution policy.

Use the interpreter path reported by bootstrap for `-m src ...` commands.
Do not assume `.\.venv\Scripts\python.exe`.
If external venv mode is already in use, do not create a conflicting repo-local `.venv` unless explicitly instructed.

The `bootstrap` command listed below is the package runtime/input readiness check, not the repo bootstrap wrapper.

Active CLI surface:
- `bootstrap`
- `stage-inputs`
- `normalize-stage`
- `build-study-slice`
- `enrich-study-signals-nearest-road`
- `check-parity`

Restored direct-entry analytical modules:
- `python -m src.active.directionality_experiment`
- `python -m src.active.upstream_downstream_prototype`
- `python -m src.active.high_confidence_upstream_downstream_analysis`

Transitional diagnostics:
- `inspect-aadt-traffic-volume-bridge`
- `inspect-aadt-traffic-volume-geojson-bridge`

Required staged inputs for the minimal slice:
- `roads`
- merged `signals`
- `crashes`

Optional diagnostic-only inputs:
- `aadt`
- supplemental traffic-volume exports

Context inputs available for planned enrichment:
- `aadt` is configured as diagnostic-only and has staged/normalized artifacts from an earlier wider run
- `access` and `speed` staged/normalized artifacts may exist from the earlier wider run, but they are not current required standard CLI inputs

Sorted files:
- active: `active/__main__.py`, `active/config.py`, `active/study_slice.py`, `active/directionality_experiment.py`, `active/upstream_downstream_prototype.py`, `active/high_confidence_upstream_downstream_analysis.py`
- transitional: `transitional/bridge_key_audit.py`, `transitional/bridge_key_geojson_audit.py`
- legacy reference: Oracle, restoration, packaging, and Stage 1C modules under `legacy/`

Legacy Oracle, bridge-propagation, restoration, inheritance, downstream-safe packaging, and Stage 1C modules were preserved under:
- `legacy/portability_branch/stage1_portable/`

If legacy-looking files still appear at the root of `src/`, treat them as residual redirect stubs or deletion candidates only.
Use `docs/active_workflow.md` for the current active story.
