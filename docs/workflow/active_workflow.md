# Current Workflow and Output Contracts

**Status: CURRENT ACTIVE.** This file is the operational map for the current repository. The current active analytical method is the graph-first roadway_graph / Step 5 workflow; older signal-centered and directed-segment workflows are preserved as historical or supporting references unless a later task explicitly promotes them.

## Current bounded problem

The current bounded problem is:

- a graph-first roadway workflow that builds a clean Travelway-based signal scaffold before crashes are assigned or upstream/downstream interpretation is attempted

The current active method is:

full Travelway graph -> signal graph association -> signal eligibility gating -> TRUE reference signals -> signal-to-anchor segments -> roadway role classification -> crash-ready segment/bin subset -> divided carriageway pairing where geometry supports it -> undivided roads treated as shared centerline by default -> crashes added only after the roadway scaffold is clean -> upstream/downstream interpreted using roadway geometry, not crash direction -> unresolved/review-only cases preserved.

This repository is still in redesign mode, but the roadway_graph workflow is now the lead current method.

## Workflow surface

The active workflow currently has one standard CLI slice plus direct-entry roadway_graph analytical modules.

The older directed segment workflow is preserved as a superseded divided-road prototype. It built divided-road signal nodes, oriented signal-anchored legs, optional access termini, and 50-foot bins without reading crash data. It is no longer the current graph foundation.

The full-roadway graph foundation prototype is the active graph-first path. It uses normalized Travelway roads, retains divided and undivided roadways, and supersedes the divided-only directed segment workflow for graph foundation purposes. Its contract is documented in `docs/workflow/roadway_graph_workflow.md`.

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

### Direct-entry modules

These modules still exist, but their methodological status differs. Use roadway_graph modules for current graph-first work. Treat directionality, upstream/downstream, high-confidence downstream, and directed_segments as historical or supporting unless a later task explicitly promotes them.

- `python -m src.active.directionality_experiment`
  - historical directionality experiment
  - supporting reference only
  - direct-entry only
- `python -m src.active.upstream_downstream_prototype`
  - historical signal-centered crash-classification prototype
  - supporting reference only
  - direct-entry only
- `python -m src.active.high_confidence_upstream_downstream_analysis`
  - historical downstream descriptive-analysis extension built from prototype outputs
  - supporting reference only
  - direct-entry only
- `python -m src.active.context_enrichment`
  - supporting AADT, access, and crash-context enrichment for older upstream/downstream outputs
  - direct-entry only
  - implemented outside the standard package CLI slice
- `python -m src.active.context_enrichment_access_same_corridor_prototype`
  - reviewed same-corridor access prototype outside production matching
  - direct-entry only
  - uses an explicit reviewed family table and prototype-only outputs
- `python -m src.active.directed_segments`
  - superseded road-network-first oriented divided-road signal-leg and 50-foot bin workflow
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
- `python -m src.active.roadway_graph.geometric_direction`
  - roadway-geometry-derived direction/orientation model for the Step 5 crash-ready subset
  - direct-entry only
  - uses crash-ready Step 5 segment/bin outputs and roadway graph candidate tables
  - does not read crash data, infer direction from crash distributions, or promote termination-refined outputs
- `python -m src.active.roadway_graph.divided_carriageway_pairing`
  - no-crash divided-carriageway pairing diagnostic for TRUE reference-signal Step 5 rows
  - direct-entry only
  - uses roadway graph geometry and Step 5 geometry outputs
  - does not read crash data, assign crashes, or infer direction from crash distributions
- `python -m src.active.roadway_graph.divided_pairing_recovery`
  - no-crash divided-pairing recovery prototype using roadway role classification
  - direct-entry only
  - review-only and candidate-only
  - preserves existing accepted divided pairs and does not promote recovered candidates into the default geometric direction model
- `python -m src.active.roadway_graph.roadway_role_classification`
  - no-crash roadway-role classification prototype for crash-ready Step 5 rows and referenced graph edges
  - direct-entry only
  - uses normalized roadway source fields, roadway graph fields, and existing divided-pairing status
  - does not read crash data, assign crashes, infer vehicle direction, revise divided pairing, or overwrite accepted divided pairs
- `python -m src.active.roadway_graph.crash_assignment`
  - conservative spatial crash assignment prototype for the crash-ready segment/bin subset
  - direct-entry only
  - assigns crashes to nearest crash-ready segment/bin within tolerance
  - does not finalize event direction or upstream/downstream interpretation
- `python -m src.active.roadway_graph.reference_signal_directional_scaffold`
  - read-only reference-signal-centered directional scaffold candidate/audit
  - direct-entry only
  - creates downstream-of-reference and upstream-of-reference records for TRUE reference signals to defensible far anchors, including non-TRUE signals, non-signal intersections, endpoints, and valid one-sided boundaries
  - creates two pseudo-directional records for undivided centerlines, uses accepted physical divided carriageway pairs where available, and preserves unpaired divided rows as blocked/review candidates
  - does not read crash data, read crash assignment outputs, use crash direction fields, infer direction from crash distributions, or modify crash assignment logic
- `python -m src.active.roadway_graph.reference_signal_directional_scaffold_qa`
  - read-only QA and conservative prototype usable surface for the reference-signal-centered directional scaffold
  - direct-entry only
  - keeps non-review/non-blocked records, includes accepted divided physical records and undivided pseudo-direction records, and excludes blocked divided, low-confidence recovery, and unknown-role rows
  - does not read crash data, read crash assignment outputs, repair geometry, force divided pairs, promote review-only recovery rows, or modify crash assignment logic
- `python -m src.active.roadway_graph.reference_signal_directional_bin_catchments`
  - read-only roadway-only directional catchment polygon surface for prototype usable directional bins
  - direct-entry only
  - buffers accepted divided physical bin geometry and creates side-specific undivided pseudo-direction polygons from local bin vectors, with bins still indexed from the TRUE reference signal
  - exports catchment GeoJSON in the repository working projected CRS, `EPSG:3968`, with `directional_bin_catchment_crs_metadata.json` as the authoritative CRS sidecar for downstream consumers
  - does not read crash data, read crash assignment outputs, use crash direction fields, recover excluded records, force divided pairs, or perform crash analysis
- `python -m src.active.roadway_graph.crash_directional_catchment_assignment_prototype`
  - crash-point-to-directional-catchment assignment prototype for the usable roadway-only catchment surface
  - direct-entry only
  - uses only `catchment_status = usable` catchment polygons and normalized crash point geometry
  - assigns crashes only when a point is contained by exactly one usable catchment; preserves multiple matches as ambiguous and no matches as unresolved
  - uses the shared catchment CRS metadata convention rather than assignment-local CRS overrides
  - does not read crash direction fields, use crash distributions, infer upstream/downstream from crashes, modify scaffold/catchment construction, include unstable or blocked catchments, force divided pairs, or perform crash analysis
- `python -m src.active.roadway_graph.crash_directional_catchment_assignment_qa`
  - read-only QA summaries for the crash-point-to-directional-catchment assignment prototype
  - direct-entry only
  - summarizes unique assignments, downstream/upstream balance, undivided and divided assignment patterns, ambiguity burden, unresolved reasons, and catchment CRS sanity
  - does not read crash direction fields, use crash distributions, infer upstream/downstream from crashes, modify scaffold/catchment/assignment logic, recover unresolved rows, or perform final crash analysis
- `python -m src.active.roadway_graph.crash_directional_assignment_analysis_readiness`
  - read-only analysis-readiness filter for uniquely assigned directional catchment crashes
  - direct-entry only
  - classifies assignments into conservative distance windows and separates long-distance review, ambiguous, and unresolved records
  - does not read crash direction fields, use crash distributions, modify scaffold/catchment/assignment logic, recover blocked or unresolved records, or perform policy-ready crash analysis
- `python -m src.active.roadway_graph.crash_directional_assignment_descriptive_summary`
  - read-only descriptive summary for readiness-gated roadway-derived directional crash assignments
  - direct-entry only
  - summarizes core 0-500 ft, standard 0-1,000 ft, extended 0-2,500 ft sensitivity, signal-level balance, roadway representation, long-distance review, and ambiguous/unresolved context
  - does not read crash direction fields, use crash distributions, modify scaffold/catchment/assignment/readiness logic, include ambiguous or unresolved crashes in unique-assignment summaries, or make policy-ready claims
- `python -m src.active.roadway_graph.undivided_catchment_assignment_failure_diagnostic`
  - read-only QA/debugging module for the undivided pseudo-direction catchment assignment surface
  - direct-entry only
  - compares divided and undivided usable catchment geometry, assignment-surface inclusion, CRS/coordinate sanity, synthetic point containment, and crash-to-undivided proximity samples
  - does not read crash direction fields, use crash distributions to change scaffold logic, modify scaffold/catchment/assignment construction, recover excluded records, force divided pairs, or perform crash analysis
- `python -m src.active.roadway_graph.crash_assignment_analysis_eligibility`
  - read-only gatekeeping layer over current crash assignment QA, interpretation-readiness, and mapless review outputs
  - direct-entry only
  - classifies assigned crashes and unresolved near-scaffold cases for spatial descriptive eligibility, caveated review, directional exclusion, manual/GIS review priority, possible assignment-logic issues, and unresolved assignment gaps
  - does not construct scaffold rows, assign crashes, repair geometry, use crash direction fields, or make any row ready for upstream/downstream interpretation

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

The roadway-geometry-derived direction/orientation pass is a separate roadway graph module:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.geometric_direction
```

It writes `signal_oriented_roadway_segments_geometric_direction.csv`, `signal_oriented_segment_bins_geometric_direction.csv`, and review summaries/GeoJSON under `work/output/roadway_graph/`. It is documented in `docs/workflow/roadway_graph_geometric_direction_model.md`.

The divided-carriageway pairing diagnostic is also separate:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.divided_carriageway_pairing
```

It writes `divided_carriageway_pair_candidates.csv`, `signal_oriented_roadway_segments_divided_pairing_enriched.csv`, and review summaries/GeoJSON under `work/output/roadway_graph/`. It is documented in `docs/workflow/roadway_graph_divided_carriageway_pairing.md`.

The divided-pairing recovery prototype is review-only:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.divided_pairing_recovery
```

It writes `divided_carriageway_pair_candidates_recovery.csv`, `signal_oriented_roadway_segments_divided_pairing_recovery_enriched.csv`, and recovery review summaries/GeoJSON under `work/output/roadway_graph/`. It is documented in `docs/workflow/roadway_graph_divided_pairing_recovery.md`.

The roadway-role classification prototype is a separate pre-recovery review step:

```powershell
<bootstrap-reported-python> -m src.active.roadway_graph.roadway_role_classification
```

It writes `roadway_role_classification.csv`, `signal_oriented_roadway_segments_role_enriched.csv`, role summaries, unpaired divided summaries, and review examples/GeoJSON under `work/output/roadway_graph/`. It is documented in `docs/workflow/roadway_graph_roadway_role_classification.md`.

## Historical directionality experiment

Run:

```powershell
<bootstrap-reported-python> -m src.active.directionality_experiment
```

Historical role:

- supporting flow-orientation experiment for divided roads near signals
- superseded by the current graph-first roadway geometry method for upstream/downstream interpretation

Preserved output contract under `work/output/directionality_experiment/`:

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

## Historical upstream/downstream prototype

Run:

```powershell
<bootstrap-reported-python> -m src.active.upstream_downstream_prototype
```

Historical role:

- first bounded signal-centered upstream/downstream crash-classification prototype
- depends on grouped current outputs from the directionality experiment
- not the current roadway_graph method

Preserved output contract under `work/output/upstream_downstream_prototype/`:

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

## Historical high-confidence downstream descriptive step

Run:

```powershell
<bootstrap-reported-python> -m src.active.high_confidence_upstream_downstream_analysis
```

Historical role:

- downstream descriptive-analysis extension built from the restored grouped prototype outputs
- preserved as prior signal-centered descriptive evidence
- direct-entry only for now

Preserved output contract under `work/output/upstream_downstream_prototype/high_confidence_descriptive_analysis/`:

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

Bounded context enrichment remains implemented as a direct-entry support step for the older upstream/downstream outputs.
The supporting implementation contract is documented in:

- `docs/workflow/enrichment_plan.md`
- `docs/workflow/context_enrichment_implementation_memo.md`

It covers:

- AADT enrichment from `New_AADT.gdb` using exact route support, positive measure overlap, and local geometry distance `<= 3.0` feet
- access-point counts and densities from `accesspoints.gdb`
- route-conflict access diagnostics and review queues that do not change production assignment
- descriptive signal-relative distance fields and fixed `50`-foot downstream band summaries within the current approach-shaped study area
- rural/urban crash-context summaries from crash `AREA_TYPE`

The supporting bounded implementation keeps access matching conservative and reviewable:

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

- `../../legacy/docs/workflow/repo_input_artifact_recovery_audit_20260428.md`

The current proposal-facing descriptive packaging phase is documented in:

- `docs/workflow/proposal_facing_descriptive_analysis_package_001.md`
- `docs/workflow/proposal_facing_descriptive_table_contracts_001.md`
- `docs/workflow/proposal_facing_distance_band_family_design_002.md`
- `docs/workflow/proposal_facing_descriptive_analysis_package_002.md`
- `docs/workflow/proposal_facing_descriptive_findings_package_003.md`

Supporting historical status:

- context enrichment is sufficient for the older divided-road signal-centered vertical slice
- access route-conflict recovery batch 001 is closed for now
- remaining access route conflicts stay unresolved unless a later bounded analysis exposes a specific review need
- the prior phase was proposal-facing descriptive table packaging, not matching recovery or modeling
- Package 001 is the frozen historical descriptive baseline
- Package 002 added expanded descriptive downstream band families without changing Package 001
- Package 003 was the initial descriptive findings/readout phase and produced review queues, not model claims
- next future phases are manual review of Package 003 queues, limiting/desirable/policy band design from documented sources, comparison-ready table refinement, and a roadway-level geographic-context source decision

The preserved implementation location and invocation are:

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

The preserved implementation enriches the older approach-row, signal-study-area, and classified-crash outputs rather than creating a universal statewide segment product.
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

### Historical or supporting direct-entry steps

- `directionality_experiment` is historical directionality evidence with a grouped output contract.
- `upstream_downstream_prototype` is a historical signal-centered prototype built on the directionality outputs.
- `high_confidence_upstream_downstream_analysis` is a historical downstream extension with a grouped output contract.

## Active repo posture

Treat the active repository as:

- authoritative current methodology in `docs/methodology/roadway_graph_methodology.md`, with repository-level support in `docs/methodology/overview_methodology.md`
- proposal alignment and growth guidance in `docs/methodology/proposal_alignment_growth_plan.md`
- operating instructions in `AGENTS.md`
- current workflow/status guidance in this file and `docs/workflow/roadway_graph_workflow.md`
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
- `src/active/roadway_graph/` as the full-roadway graph foundation prototype
- `src/active/roadway_graph/crash_assignment.py`, `src/active/roadway_graph/geometric_direction.py`, `src/active/roadway_graph/divided_carriageway_pairing.py`, `src/active/roadway_graph/divided_pairing_recovery.py`, and `src/active/roadway_graph/roadway_role_classification.py` as current roadway_graph direct-entry modules
- `src/active/directionality_experiment.py`, `src/active/upstream_downstream_prototype.py`, `src/active/high_confidence_upstream_downstream_analysis.py`, and `src/active/directed_segments/` as historical or supporting direct-entry modules, not the current methodology
- `src/transitional/bridge_key_audit.py` and `src/transitional/bridge_key_geojson_audit.py` as transitional diagnostics

## Next Recommended Implementation Step

The divided-pairing recovery prototype now exists as review-only evidence. The next technical task is QGIS review of `divided_pairing_recovery_review.geojson` and `divided_pairing_still_unresolved_review.geojson`, followed by a narrower recovery rule only if mapped review supports promotion.





