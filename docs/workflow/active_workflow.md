# Current Workflow and Output Contracts

## Current bounded problem

The current bounded problem is:

- a signal-centered workflow that builds bounded near-signal evidence around each signal so nearby crashes can later be interpreted as approaching or leaving the signal, or upstream or downstream relative to it

This repository is still in redesign mode, but the restored workflow is now concrete enough to describe truthfully.

## Workflow surface

The active workflow currently has one standard CLI slice plus three direct-entry analytical modules.

### Standard package CLI slice

The package CLI surface exposed through `-m src` is intentionally small:

1. `bootstrap`
2. `stage-inputs`
3. `normalize-stage`
4. `build-study-slice`
5. `enrich-study-signals-nearest-road`
6. `check-parity`

Optional transitional diagnostics remain available through the same package CLI:

- `inspect-aadt-traffic-volume-bridge`
- `inspect-aadt-traffic-volume-geojson-bridge`

### Restored direct-entry modules

These modules are active and useful again, but they are not currently exposed through `-m src`:

- `python -m src.active.directionality_experiment`
  - supporting directionality experiment
  - restored
  - direct-entry only
- `python -m src.active.upstream_downstream_prototype`
  - first bounded signal-centered crash-classification prototype
  - restored
  - direct-entry only
- `python -m src.active.high_confidence_upstream_downstream_analysis`
  - downstream descriptive-analysis extension built from prototype outputs
  - restored
  - direct-entry only
  - still best described as a provisional downstream step rather than a standard CLI step

## Bootstrap entry story

Repository setup lives in `scripts/`.
Preferred bootstrap commands are:

```powershell
.\scripts\bootstrap.cmd
.\scripts\bootstrap.cmd -CreateVenv -UseExternalVenv
.\scripts\bootstrap.cmd -CreateVenv -UseExternalVenv -InstallDeps
```

`scripts/bootstrap.ps1` remains the implementation, but direct `.\scripts\bootstrap.ps1` execution may be blocked by PowerShell execution policy, so active docs should point to the wrapper.

Bootstrap currently targets Python 3.11.
TEMP/TMP and pip cache may be externalized outside the repo, and the active interpreter may also live outside the repo.

Use the interpreter path reported by bootstrap for `-m src ...` commands.
Do not assume `.\.venv\Scripts\python.exe`.
If external venv mode is already in use, do not create a conflicting repo-local `.venv` unless explicitly instructed.

The `src bootstrap` CLI command is a runtime/input readiness check.
It is not the repository environment bootstrap entrypoint.

## Standard bounded active slice

Use the bootstrap-reported interpreter path and run:

```powershell
<bootstrap-reported-python> -m src stage-inputs
<bootstrap-reported-python> -m src normalize-stage
<bootstrap-reported-python> -m src build-study-slice
<bootstrap-reported-python> -m src enrich-study-signals-nearest-road
<bootstrap-reported-python> -m src check-parity
```

Optional diagnostics only:

```powershell
<bootstrap-reported-python> -m src inspect-aadt-traffic-volume-bridge
<bootstrap-reported-python> -m src inspect-aadt-traffic-volume-geojson-bridge
```

Required staged inputs for the standard slice:

- `roads` from `Travelway.gdb`
- merged `signals` from HMMS, Norfolk, and Hampton signal sources
- `crashes` from `crashdata.gdb`

Optional diagnostic inputs outside the required slice:

- `aadt` from `New_AADT.gdb`
- supplemental traffic-volume GeoJSON and shapefile exports

Context inputs that may exist from earlier wider staging runs:

- `access` from `accesspoints.gdb`
- `speed` from `postedspeedlimits.gdb`

These artifacts are useful for planned enrichment and prototype support, but they are not current required inputs for the standard package CLI slice. The upstream/downstream prototype reads posted-speed context directly for speed-informed approach lengths.

Expected outputs for the standard slice:

- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `work/output/stage1b_study_slice/Study_Signals.parquet`
- `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`
- `work/parity/stage1b_study_slice_qc.json`
- `work/parity/stage1b_signal_nearest_road_qc.json`
- `work/parity/stage1_parity_manifest.json`

Those outputs are currently present in this working tree.

## Directionality experiment

Run:

```powershell
<bootstrap-reported-python> -m src.active.directionality_experiment
```

Role:

- supporting flow-orientation experiment for divided roads near signals
- not the final architecture by itself

Current output contract under `work/output/directionality_experiment/`:

- `README.md`
- `tables/current/`
- `tables/history/`
- `review/current/`
- `review/history/`
- `review/geojson/current/`
- `review/geojson/history/`
- `review/geopackage/current/`
- `review/geopackage/history/`
- `runs/current/`
- `runs/history/`

`history/` is fallback or collision handling, not the main archive lane.

## Upstream/downstream prototype

Run:

```powershell
<bootstrap-reported-python> -m src.active.upstream_downstream_prototype
```

Role:

- first bounded signal-centered upstream/downstream crash-classification prototype
- depends on grouped current outputs from the directionality experiment

Current output contract under `work/output/upstream_downstream_prototype/`:

- `README.md`
- `tables/current/`
- `tables/history/`
- `review/current/`
- `review/history/`
- `review/geojson/current/`
- `review/geojson/history/`
- `runs/current/`
- `runs/history/`

`review/geopackage/current/` is optional and only appears when GeoPackage export succeeds in the current environment.

## High-confidence downstream descriptive step

Run:

```powershell
<bootstrap-reported-python> -m src.active.high_confidence_upstream_downstream_analysis
```

Role:

- downstream descriptive-analysis extension built from the restored grouped prototype outputs
- restored and meaningful again
- still provisional for workflow integration
- direct-entry only for now

Current output contract under `work/output/upstream_downstream_prototype/high_confidence_descriptive_analysis/`:

- `README.md`
- `tables/current/`
- `tables/history/`
- `review/current/`
- `review/history/`
- `review/geojson/current/`
- `review/geojson/history/`
- `runs/current/`
- `runs/history/`

The grouped `current/` lanes are the authoritative contract.
Some legacy flat-layout residue from earlier runs may still remain at that analysis root until a separate cleanup pass removes it.

The GeoJSON files under `review/geojson/current/` are QGIS-support layers written by Python.
Any case-study PNGs remain manual QGIS products and are not expected from the Python run.

## Planned context enrichment

The next planned analytical expansion is context enrichment for the active upstream/downstream outputs.
The implementation contract is documented in:

- `docs/workflow/enrichment_plan.md`
- `docs/workflow/context_enrichment_implementation_memo.md`

It covers:

- AADT enrichment from `New_AADT.gdb`
- access-point counts and densities from `accesspoints.gdb`
- rural/urban crash-context summaries from crash `AREA_TYPE`

This is not yet implemented code.
The reserved first implementation location and invocation are:

```powershell
<bootstrap-reported-python> -m src.active.context_enrichment
```

Reserved module location:

- `src/active/context_enrichment.py`

Expected optional overrides for that first implementation:

- `--prototype-root`
- `--study-slice-root`
- `--normalized-root`
- `--output-root`
- `--run-label`

The intended first implementation should enrich the current approach-row, signal-study-area, and classified-crash outputs rather than creating a universal statewide segment product.
It remains outside the standard Stage 1A CLI slice until the bounded direct-entry step is implemented and validated.

## Integration status

### Standard active slice

- `stage-inputs`, `normalize-stage`, `build-study-slice`, `enrich-study-signals-nearest-road`, and `check-parity` are the standard active workflow.
- They are CLI-exposed and should be treated as the normal bounded entry path.

### Restored but direct-entry steps

- `directionality_experiment` is an active supporting experiment with a grouped output contract.
- `upstream_downstream_prototype` is an active prototype built on the directionality outputs, but it is still direct-entry only.
- `high_confidence_upstream_downstream_analysis` is now a restored downstream extension with a grouped output contract, but it remains best described as a provisional downstream step rather than a standard active CLI command.

## Active repo posture

Treat the active repository as:

- authoritative guidance in `docs/methodology/overview_methodology.md` and `AGENTS.md`
- current workflow/status guidance in this file and `docs/workflow/enrichment_plan.md`
- a reduced active/transitional workflow in `src/`
- active runnable modules in `src/active/`
- transitional diagnostics in `src/transitional/`
- active config in `config/stage1_portable.toml`
- authoritative raw inputs in `Intersection Crash Analysis Layers/`
- transitional staged and normalized work products in `artifacts/staging/` and `artifacts/normalized/`
- generated run outputs and validation manifests in `work/output/` and `work/parity/`

Generated outputs are evidence, not architecture.
The old output ladder under `artifacts/output/` is preserved legacy evidence only.

## What remains active

Active code and commands are currently:

- `src/__main__.py` as the package entry shim
- `src/active/__main__.py`
- `src/active/config.py`
- `src/active/study_slice.py` for the standard CLI slice
- `src/active/directionality_experiment.py` as a direct-entry supporting experiment
- `src/active/upstream_downstream_prototype.py` as a direct-entry prototype
- `src/active/high_confidence_upstream_downstream_analysis.py` as a restored direct-entry downstream extension
- `src/transitional/bridge_key_audit.py` and `src/transitional/bridge_key_geojson_audit.py` as transitional diagnostics
