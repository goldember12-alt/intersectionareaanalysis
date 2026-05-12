# Current Workflow and Output Contracts

## Current bounded problem

The current bounded problem is:

- a signal-centered workflow that builds bounded near-signal evidence around each signal so nearby crashes can later be interpreted as approaching or leaving the signal, or upstream or downstream relative to it

This repository is still in redesign mode, but the restored workflow is now concrete enough to describe truthfully.

## Workflow surface

The active workflow currently has one standard CLI slice plus direct-entry analytical modules.

The road-network-first directed segment workflow is now a separate active direct-entry family. It builds divided-road signal nodes, oriented signal-anchored legs, optional access termini, and 50-foot bins without reading crash data, inferring true vehicle travel direction, or changing the existing crash classification modules. Its contract is documented in `docs/workflow/directed_segment_workflow.md`.

The full-roadway graph foundation prototype is now the active graph-foundation path. It uses normalized Travelway roads, retains divided and undivided roadways, and supersedes the divided-only directed segment workflow for graph foundation purposes. Its contract is documented in `docs/workflow/roadway_graph_workflow.md`.

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
- `python -m src.active.context_enrichment`
  - bounded AADT, access, and crash-context enrichment for current upstream/downstream outputs
  - direct-entry only
  - implemented outside the standard package CLI slice
- `python -m src.active.context_enrichment_access_same_corridor_prototype`
  - reviewed same-corridor access prototype outside production matching
  - direct-entry only
  - uses an explicit reviewed family table and prototype-only outputs
- `python -m src.active.directed_segments`
  - road-network-first oriented divided-road signal-leg and 50-foot bin workflow
  - direct-entry only
  - uses `Study_Roads_Divided.parquet` and `Study_Signals_NearestRoad.parquet`
  - uses `artifacts/normalized/access.parquet` only for optional access termini
  - does not read crash data, infer true vehicle travel direction, or modify crash classification logic
- `python -m src.active.roadway_graph`
  - full-roadway signal-adjacent graph foundation prototype
  - direct-entry only
  - uses `artifacts/normalized/roads.parquet` and `artifacts/normalized/signals.parquet`
  - retains both divided and undivided Travelway roads
  - does not read crash data, assign crashes, infer true vehicle travel direction, or modify crash/access modules

## Bootstrap entry story

Repository setup lives in `scripts/`.

The canonical working copy for this repository should now live outside OneDrive under a normal local path such as `C:\Users\Jameson.Clements\source\IntersectionCrashAnalysis`. Treat any OneDrive-hosted copy as transitional only.

If you are converting an older OneDrive working tree into the local canonical copy and need local continuity, copy these local-only directories deliberately:

- `artifacts/`
- `work/`
- `legacy/`
- `Intersection Crash Analysis Layers/`

Do not rely on moving a repo-local `.venv/` between locations. Use bootstrap to discover or recreate the active interpreter instead.

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

These artifacts are useful for context enrichment and prototype support, but they are not current required inputs for the standard package CLI slice. The upstream/downstream prototype reads posted-speed context directly for speed-informed approach lengths.

Expected outputs for the standard slice:

- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `work/output/stage1b_study_slice/Study_Signals.parquet`
- `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`
- `work/parity/stage1b_study_slice_qc.json`
- `work/parity/stage1b_signal_nearest_road_qc.json`
- `work/parity/stage1_parity_manifest.json`

Those outputs are currently present in this working tree.

## Roadway graph foundation prototype

Run:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph
```

Role:

- full-roadway graph foundation prototype for signal-adjacent roadway legs
- retains both divided and undivided roads from normalized Travelway
- supersedes the divided-only directed segment workflow for graph foundation purposes
- does not read crash data, assign crashes, infer true vehicle direction, or implement analysis-ready gating

Current output contract under `work/output/roadway_graph/`:

- `tables/current/roadway_graph_nodes.csv`
- `tables/current/roadway_graph_edges.csv`
- `tables/current/signal_graph_nodes.csv`
- `tables/current/signal_adjacent_edges.csv`
- `tables/current/signal_graph_edge_bins_50ft.csv`
- `tables/current/graph_gap_review.csv`
- `tables/current/divided_edge_directional_candidates.csv`
- `tables/current/undivided_edge_candidates.csv`
- `review/current/graph_build_summary.csv`
- `review/current/signal_adjacent_edge_count_summary.csv`
- `review/current/sample_signal_graph_review.csv`
- `review/geojson/current/*.geojson`
- `runs/current/run_summary.json`

The detailed contract is documented in `docs/workflow/roadway_graph_workflow.md`.

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

For grouped output contracts, each run should write both the stable `current/` artifact and a timestamped copy in the matching `history/` folder. `current/` is the active handoff lane; `history/` is the growing retention lane.

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

## Current/history output rule

For active workflow folders that expose paired `current/` and `history/` lanes, a successful run should:

- write the latest artifacts to the stable `current/` filenames
- write timestamped copies of the same run artifacts to the matching `history/` folders
- print or return the `current/` artifact paths in the run metadata so Codex can report those paths in chat
- leave history artifacts untouched when a human manually deletes reviewed files from `current/`

If Windows, OneDrive, QGIS, or another process blocks replacement of a `current/` artifact, the run should still keep the timestamped `history/` copy and the operator should treat the blocked `current/` file as stale until it is manually cleared or a later rerun replaces it.

## Context enrichment

Bounded context enrichment is now implemented as a direct-entry step for the active upstream/downstream outputs.
The active implementation contract is documented in:

- `docs/workflow/enrichment_plan.md`
- `docs/workflow/context_enrichment_implementation_memo.md`

It covers:

- AADT enrichment from `New_AADT.gdb` using exact route support, positive measure overlap, and local geometry distance `<= 3.0` feet
- access-point counts and densities from `accesspoints.gdb`
- route-conflict access diagnostics and review queues that do not change production assignment
- descriptive signal-relative distance fields and fixed `50`-foot downstream band summaries within the current approach-shaped study area
- rural/urban crash-context summaries from crash `AREA_TYPE`

The current bounded implementation keeps access matching conservative and reviewable:

- access runs exact normalized route support plus measure and distance checks first
- exact-route `route_conflict` rows may then use the reviewed same-corridor overlay, but only for `ReviewDecision = include` route-family pairs in `docs/workflow/context_enrichment_access_same_corridor_seed_families.csv`
- excluded, unreviewed, opposite-direction, and non-unique local-geometry candidates remain refused
- review outputs and validation summaries should make route-conflict and measure-conflict behavior explicit
- rural/urban remains crash-context only, with explicit no-crash-context rows instead of blank approach-row fields

The current first manual route-conflict family review queue is documented in:

- `docs/workflow/access_route_conflict_family_review_batch_001.md`

The first explicit same-corridor promotion comparison is documented in:

- `docs/workflow/access_route_conflict_promotion_batch_001_comparison.md`

The closure/integration check against the active upstream/downstream workflow is documented in:

- `docs/workflow/context_enrichment_upstream_downstream_integration_memo.md`

The April 28, 2026 raw-input and artifact recovery audit is documented in:

- `docs/workflow/repo_input_artifact_recovery_audit_20260428.md`

The current proposal-facing descriptive packaging phase is documented in:

- `docs/workflow/proposal_facing_descriptive_analysis_package_001.md`
- `docs/workflow/proposal_facing_descriptive_table_contracts_001.md`
- `docs/workflow/proposal_facing_distance_band_family_design_002.md`
- `docs/workflow/proposal_facing_descriptive_analysis_package_002.md`
- `docs/workflow/proposal_facing_descriptive_findings_package_003.md`

Current status:

- context enrichment is sufficient for the current divided-road vertical slice
- access route-conflict recovery batch 001 is closed for now
- remaining access route conflicts stay unresolved unless a later bounded analysis exposes a specific review need
- the current phase is proposal-facing descriptive table packaging, not matching recovery or modeling
- Package 001 is the frozen descriptive baseline
- Package 002 adds expanded descriptive downstream band families without changing Package 001
- Package 003 is the initial descriptive findings/readout phase and produces review queues, not model claims
- next future phases are manual review of Package 003 queues, limiting/desirable/policy band design from documented sources, comparison-ready table refinement, and a roadway-level geographic-context source decision

The current implementation location and invocation are:

```powershell
<bootstrap-reported-python> -m src.active.context_enrichment
```

Module location:

- `src/active/context_enrichment.py`

Optional overrides:

- `--prototype-root`
- `--study-slice-root`
- `--normalized-root`
- `--output-root`
- `--same-corridor-family-table`
- `--run-label`

The active implementation enriches the current approach-row, signal-study-area, and classified-crash outputs rather than creating a universal statewide segment product.
The same run now also writes exploratory signal-level downstream distance-band summaries for the current approach-shaped study area.
It remains outside the standard Stage 1A CLI slice as a bounded direct-entry step.

## Same-corridor access validation prototype

Run:

```powershell
<bootstrap-reported-python> -m src.active.context_enrichment_access_same_corridor_prototype
```

Role:

- historical/review validation for the reviewed same-corridor access assignment rule
- preserves pre-promotion prototype guardrails and review GeoJSONs
- should not be used to broaden production beyond the reviewed family table
- only evaluates explicit reviewed families from `docs/workflow/context_enrichment_access_same_corridor_seed_families.csv`

Current output contract under `work/output/context_enrichment_access_same_corridor_prototype/`:

- `README.md`
- `tables/current/`
- `tables/history/`
- `review/current/`
- `review/history/`
- `review/geojson/current/`
- `review/geojson/history/`
- `runs/current/`
- `runs/history/`

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

- authoritative methodology in `docs/methodology/overview_methodology.md`
- proposal alignment and growth guidance in `docs/methodology/proposal_alignment_growth_plan.md`
- operating instructions in `AGENTS.md`
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
- `src/active/directed_segments/` as the preserved divided-road directed signal-leg prototype
- `src/active/roadway_graph/` as the full-roadway graph foundation prototype
- `src/transitional/bridge_key_audit.py` and `src/transitional/bridge_key_geojson_audit.py` as transitional diagnostics





