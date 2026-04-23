# AGENTS.md

## Project Mission

This repository implements a Virginia intersection crash-analysis pipeline used to evaluate downstream functional area requirements at signalized intersections.

This is not just a GIS scripting repository. It is an analytical workflow whose purpose is to:

1. compile and stage roadway, signal, crash, access, AADT, speed, and related intersection-context inputs
2. define downstream functional zones
3. segment roadways and assign downstream context
4. measure crash occurrence within downstream conditions
5. identify high-crash outlier intersections relative to comparable sites
6. support Virginia-specific downstream functional area guidance development

The repository must preserve this analytical purpose even while the implementation changes substantially.
That includes preserving the distinction between geometry-derived support that helps prepare later labeling and the stronger network-referenced direction logic needed for trustworthy final downstream directionality.

## Primary Operating Principle

Preserve **analytical intent** and **output meaning**, not ArcPy implementation details.

ArcPy is now **legacy reference behavior**.

The immediate priority is to transform the repository into a **self-runnable GeoPandas/open-source Python workflow** that Codex can execute, inspect, test, and iterate on without requiring ArcGIS Pro.

If preserving analytical meaning requires Oracle-backed network linkage, bridge-key integration through supplemental GIS inputs, or live Oracle access from the open-source path, those are valid Stage 1 migration moves. Geometry-only support can assist preparation, but it must not be presented as a substitute for trustworthy downstream directionality when the underlying lineage is insufficient.

Once the repository is self-runnable, the priority shifts to architectural cleanup, methodology alignment, and maintainability improvements.

## Two-Stage Contract

The repository is governed by two explicit stages.

### Stage 1: Migration-First

Goal: make the project runnable in a standard Python environment with no ArcPy dependency in the main execution path.

Success criteria:

- Codex can run the repo directly in a local Python environment
- the main workflow uses GeoPandas/open-source tooling instead of ArcPy
- outputs are written in open or portable formats where practical
- paths are portable and configuration-driven
- parity checks exist against legacy ArcPy outputs where possible
- the project no longer depends on ArcGIS Pro for routine execution and testing

### Stage 2: Architecture-First

Goal: once the repo is runnable in pure Python, improve structure, maintainability, and fidelity to the high-level methodology.

Success criteria:

- code structure is modular and understandable
- docs and code are aligned
- methodology is easier to trace through the implementation
- QC and validation are clearer and more reproducible
- module boundaries, naming, configs, and handoffs are clean
- the repository is easier to maintain and extend

## Stage 1 Breakdown

Stage 1 is not a vague rewrite. It is a fixed sequence.

### 1A. Portability First

Codex must first make the repository portable and self-runnable.

Required outcomes:

- centralize configuration
- remove or isolate machine-specific assumptions
- separate code from data dependencies
- define clean project entrypoints
- define environment/dependency requirements
- ensure the repo can be opened and run outside ArcGIS Pro

Preferred artifacts:

- `requirements.txt` or `pyproject.toml`
- config files for paths and runtime settings
- clear run instructions
- portable output directories
- repository layout that does not depend on ArcGIS project state

Do not spend time polishing structure before the repo is runnable.

### 1B. Replace ArcPy Runtime Dependencies

Codex must replace ArcPy-dependent execution in the main path with open-source geospatial tooling.

Preferred stack:

- `geopandas`
- `shapely`
- `pandas`
- `pyogrio` or `fiona`
- `pyproj`
- additional pure-Python libraries only where justified

Priority targets include:

- feature-class read/write logic
- CRS/projection handling
- buffering
- overlays/intersections
- spatial joins
- dissolves
- segmentation/splitting where possible
- tabular joins and summarization
- export logic
- bounded Oracle or other database-backed enrichment when base GIS lineage alone cannot preserve analytical meaning
- supplemental bridge-key integration, such as traffic-volume or AADT-adjacent link identity, when needed to support truthful downstream directionality

ArcPy behavior is a reference for expected results, not a required implementation model.
Pre-exported Oracle CSVs may remain useful transition artifacts, but they are not automatically the intended final mechanism if live Oracle access is needed for faithful migration.

### 1C. Build a Runnable Vertical Slice

Do not attempt a blind full-repo rewrite all at once.

Codex should first produce at least one complete end-to-end open-source vertical slice that can:

1. load inputs
2. construct zones or equivalent geometry products
3. segment or label roadway context
4. assign crashes/access where relevant
5. write outputs
6. produce QC summaries

Once a complete slice is working, expand outward until ArcPy is no longer required in the main workflow.

### 1D. Build Parity Checks Against Legacy Outputs

Stage 1 is not complete without parity checking.

Where legacy ArcPy outputs exist, Codex should build comparison checks such as:

- row counts
- feature counts
- schema comparisons
- null-count checks
- key field presence/completeness
- geometry length totals where relevant
- join completeness
- sample-location spot checks
- output naming consistency
- QC summary comparisons

Exact geometric identity is not always required initially. The goal is credible behavioral parity and analytical equivalence.

When parity is incomplete, Codex must clearly state what matches, what differs, and what remains unverified.

## Stage 2 Breakdown

Only after Stage 1 is sufficiently complete should Codex prioritize deeper cleanup.

Stage 2 includes:

1. improving module boundaries
2. reducing monolithic script structure
3. aligning naming and responsibilities across modules
4. improving documentation fidelity
5. clarifying methodology-to-code traceability
6. improving logging and diagnostics
7. improving QC outputs and reproducibility
8. simplifying future maintenance and extension

Stage 2 is subordinate to Stage 1. Do not prioritize elegance over runnable portability.

## Analytical Intent

The code implements a crash-based screening and comparison workflow, not merely geometric processing.

The high-level analytical logic is:

1. compile a merged statewide dataset of intersections and roadway context
2. assign roadway, traffic control, speed, volume, crash, and access context
3. use external downstream functional-distance guidance as an initial baseline
4. define downstream comparison zones
5. measure Virginia crash occurrence within those baseline conditions
6. identify outlier intersections with elevated crash experience
7. evaluate outliers in terms of downstream design, access density, roadway context, and related factors
8. support synthesis into Virginia-specific downstream functional area guidance

Codex must preserve this analytical purpose through all migration and cleanup work.
That includes preserving a truthful basis for downstream direction assignment. Geometry-derived endpoint support may help prepare later labeling, but it is not equivalent to final downstream directionality when the methodology depends on network-referenced Oracle linkage.

## What Must Be Preserved

Preserve:

- analytical meaning of outputs
- role of downstream zones and segmentation
- crash/access assignment intent
- context-sensitive interpretation of roadway conditions
- truthful downstream directionality, even if it ultimately depends on Oracle-backed linkage or supplemental bridge-key inputs rather than geometry-only inference
- canonical final outputs unless explicitly changed
- methodology distinctions between baseline guidance, observed Virginia crash performance, and outlier interpretation

Do not preserve ArcPy-specific implementation details just because they existed.

## What Is Legacy

The following are legacy reference behavior, not long-term constraints:

- ArcPy-specific geometry implementations
- ArcGIS Pro as the primary execution environment
- FGDB-only assumptions
- ArcGIS-specific orchestration patterns
- machine-specific workspace logic
- brittle dependencies on ArcGIS project state

These can be replaced so long as analytical meaning and output contracts are preserved or clearly redefined.

## Project Structure

Current known structure includes:

Top-level orchestration/reset:

- `run_all.py`
- `clearinggdb.py`

Phase-grouped directories:

- `firststep/`
- `secondstep/`
- `thirdstep/`

Main modular stage-3 refactor area:

- `thirdstep/thirdstep_module_refactor/`

Known stage-3 modules include:

- `config.py`
- `thirdstep.py`
- `geometry_pipeline.py`
- `assignments.py`
- `backfill.py`
- `field_normalization.py`
- `geopandas_oracle.py`
- `writeback_qc.py`

Supporting materials:

- `docs/`
- `oracle_exports/`
- `layer_summaries/`

Figure-generation scripts:

- `firststepfigures.py`
- `secondstepfigures.py`
- `thirdstepfigures.py`

## Repository Redesign Contract

Codex may restructure the repository to improve navigation, portability, and maintainability.

Preferred direction:

- Codex may move ArcPy-era implementations and assets into a `legacy/` area, including `firststep/`, `secondstep/`, legacy `thirdstep/` assets, figure-generation scripts, and ArcGIS-specific orchestration, so long as traceability and parity checking are preserved
- establish a clean active source tree under `src/`
- separate raw inputs, staged data, outputs, docs, tests, and scripts
- create an explicit home for Oracle-related inputs/exports
- reduce clutter at the repository root
- optimize for a stock-standard Python geospatial repo layout

Codex may be moderately creative in proposing this redesign, but must preserve:
- analytical intent
- canonical output meaning
- traceability back to legacy behavior
- the ability to run parity checks against legacy outputs

## Preferred Open-Source Direction

Preferred characteristics of the migrated repository:

- standard Python execution
- portable paths
- repo-local configuration
- open data formats where practical
- clear separation of code, configs, inputs, temporary work products, and outputs
- reproducible dependency installation
- no hidden dependency on GUI state or ArcGIS session state
- ability to incorporate configured supplemental bridge datasets and live Oracle-backed enrichment when they are required to preserve analytical meaning

Preferred output/storage formats where practical:

- GeoPackage
- GeoJSON
- Parquet
- CSV

Use FGDB only if temporarily necessary for parity or transition purposes.
Repo-local Oracle exports are acceptable transition artifacts, but the open-source path may also need documented live Oracle access where pre-exported extracts are not sufficient for faithful downstream directionality.

## Build, Run, and Development Rules

The repository should evolve toward ordinary Python execution.

Preferred future execution pattern:

- run from repo root
- use documented commands/scripts
- avoid requiring ArcGIS Pro for normal development
- ensure Codex can run the main pipeline or sub-pipeline directly

If there are temporary dual paths during migration, document clearly:

- During Stage 1 migration, the GeoPandas/open-source execution path is the authoritative build target; the legacy ArcPy path is a parity reference only.
- legacy ArcPy path
- new GeoPandas/open-source path
- which one is authoritative
- what parity has been checked

## Python Environment Contract

This repository must be run with the repo-local virtual environment.

On Windows, Codex should use:

- `.\.venv\Scripts\python.exe` for Python execution
- `.\.venv\Scripts\pip.exe` for package installation when needed

Do not assume `python`, `pip`, or PATH resolve to the correct interpreter.

Before running Python tasks, verify:

- `Test-Path .\.venv\Scripts\python.exe`

If the local `.venv` does not exist, create it and install dependencies before proceeding.

When installing dependencies in this repo, keep temp and cache directories inside the workspace.

For pip installs in this repo, set `TMP`, `TEMP`, and `PIP_CACHE_DIR` to repo-local directories before running install commands.

## Raw Input Data Contract

The current baseline raw input layers live inside the repo in a configured input root and should be treated as authoritative source inputs, not ad hoc files.

The current baseline input families are:

- roads
- signals
- crashes
- access
- aadt
- speed

Supplemental datasets may be added later, especially if the baseline inputs prove insufficient for Oracle joins, directional logic, or other integration needs.
This can include traffic-volume or AADT-adjacent sources that carry GIS-side link identity needed to bridge into Oracle `rns.eyroadxx` through `tmslinkid`.

When a newly added traffic-volume layer overlaps with the AADT source already used by the repo, Codex should treat comparison between those sources as part of the justified migration path rather than as unrelated exploratory work. The purpose of that comparison is to determine whether the bridge key already exists in the current AADT lineage, is joinable to it, or should enter the pipeline at a different boundary such as a merged base layer or the road/segment lineage.

Codex should register raw and supplemental inputs through configuration rather than hardcoding paths in pipeline code.

## Canonical Outputs

Treat the following as output contracts unless methodology explicitly changes:

Primary outputs:

- `Final_Functional_Segments`
- `Final_Study_Signals`
- final downstream/functional-zone outputs
- stage-3 QC layers and QC tables

Supporting outputs that may also matter:

- staged `Study_*` outputs
- staged `TW_*` outputs
- `Final_*` outputs used by figures or downstream steps

Codex must not silently rename, repurpose, or remove canonical outputs without updating documentation and parity notes.

## Coding Style and Refactor Rules

General style rules:

- 4-space indentation
- descriptive snake_case
- small, focused functions
- thin orchestration layers
- centralized configuration
- explicit naming for outputs, fields, and data products
- avoid top-level procedural sprawl where modular functions are practical
- add logging where useful
- add docstrings to public helpers where useful

During Stage 1, prioritize operational clarity over elegance.

During Stage 2, improve architecture without obscuring execution flow.

## Path and Configuration Rules

Prefer:

- relative paths
- config-driven paths
- project-local runtime assumptions
- explicit environment requirements

Avoid:

- new hardcoded machine-specific paths
- hidden dependence on OneDrive layout
- hidden dependence on ArcGIS project workspace state
- ad hoc path logic spread across scripts

Treat source datasets and Oracle exports as inputs, not files to rewrite casually.

## Validation Rules

There is currently no fully automated test suite. Codex must therefore build practical validation as part of the migration.

Minimum expectations for meaningful changes:

- verify code runs
- verify expected outputs are written
- verify key schemas/fields
- verify counts and joins where relevant
- compare results against legacy outputs where available
- document what was checked and what was not

For Stage 1:

- parity checks are mandatory where feasible
- runnable open-source execution matters more than stylistic cleanup
- every migrated component should have some observable check
- directionality-related claims must state whether they come from geometry-only support, Oracle-backed linkage, or a still-incomplete bridge path
- route-only Oracle preparation must not be presented as final downstream directionality when ambiguity remains unresolved

For Stage 2:

- preserve or improve validation coverage
- improve clarity of QC artifacts
- improve traceability of assumptions and outputs

Do not claim parity or validation unless it was actually checked.

## Figure and Reporting Rules

Figure-generation code is analytical support code.

When changing figure logic:

- preserve interpretability
- keep zone definitions and labels understandable
- keep figures aligned with migrated output semantics
- document changed assumptions
- include visual comparison notes when outputs materially change

## Documentation Rules

Documentation must track reality.

Primary documentation roles:

- `AGENTS.md` = Codex operating contract
- `docs/` = methodology, workflow notes, migration notes, handoff notes
- inline comments/docstrings = local implementation detail

When migration decisions materially change implementation or outputs, update the relevant docs rather than letting code and documentation drift apart.

## State and Handoff Rules

For meaningful changes, preserve a handoff trail.

After substantial changes, record:

- what changed
- why it changed
- whether the change was Stage 1 or Stage 2 work
- which scripts/modules were affected
- what was run
- what parity checks were performed
- what remains unverified
- any known output differences from legacy behavior
- whether downstream directionality at that boundary is geometry-support only, Oracle-dependent, Oracle-enriched, or still blocked by missing GIS-side bridge keys

Prefer updating existing handoff or migration notes over creating redundant status clutter.

## Task Completion Rule

A task is not complete until the relevant combination of:

- code
- configuration
- documentation
- validation/parity notes
- output checks

has been updated consistently.

## Commit Guidance

Commits should be focused and descriptive.

Good commit style:

- short imperative summary
- identify affected phase/module
- indicate migration vs cleanup intent where useful
- avoid mixing unrelated methodology changes with structural changes

## Codex Operating Rules

### Default First Actions

For a new session in this repo, Codex should generally:

1. verify that the repo-local `.venv` exists and identify the correct Python interpreter
2. identify the repo root and current active source path
3. distinguish active migration targets from legacy reference areas
4. identify the current executable entrypoint for the open-source path
5. classify the next task as Stage 1 or Stage 2
6. propose the next bounded task before making broad structural changes

Codex should avoid starting with ornamental cleanup, broad renaming, or documentation polishing unless those are the explicit task.

### Operating Posture

Codex should behave like a structured migration operator, not a freeform artist.

Default behavior:

1. understand the affected workflow first
2. identify whether the task belongs to Stage 1 or Stage 2
3. prefer runnable portability over stylistic cleanup during Stage 1
4. treat ArcPy as legacy reference behavior
5. preserve analytical intent and output meaning
6. prefer open formats and portable paths
7. make the repo self-runnable
8. build parity checks where possible
9. only after runnable migration, shift focus to cleanup and methodology alignment

For major tasks, Codex should first produce:

1. task classification: Stage 1 or Stage 2
2. dependency/impact summary
3. concrete proposed edit plan
4. implementation in bounded steps
5. explicit validation/parity summary

## Codex Non-Negotiables

Codex should not:

- default to preserving ArcPy just because it exists
- assume ArcGIS Pro will be available for validation
- hardcode new machine-specific paths
- silently change output meaning
- rename canonical outputs casually
- perform architecture polish before establishing runnable portability
- claim equivalence without comparison evidence

## Definition of Good Progress

Good progress is:

- making the repo more runnable
- making the workflow more portable
- making output meaning more explicit
- making parity easier to check
- making the code easier to validate
- making future cleanup easier

Good progress is not:

- ornamental refactoring
- unnecessary renaming
- broad rewrites without runnable checkpoints
- preserving legacy implementation for its own sake
