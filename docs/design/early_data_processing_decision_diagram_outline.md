# Outline for the Early Data Processing Decision Diagram

## Diagram Title

Early Data Processing for Later Directionality and Upstream/Downstream Work

## Subtitle / Guiding Question

How do the earliest roadway, signal, crash, and support layers become the bounded study inputs later consumed by the directionality experiment and the signal-centered upstream/downstream prototype?

## Figure Intent

Show the bounded preprocessing path that stages and normalizes active inputs, builds the divided-road study slice, and prepares the specific crash and speed context later modules actually use.

## Core Reading Structure

- one centered processing spine with three phases
- one left input cluster showing the raw layers and later support sources
- one right rules cluster for staging, normalization, study-slice, nearest-road, crash-prep, and speed-prep logic
- one bottom output cluster showing the handoff layers and QC products

## Cluster A: Inputs / Starts Here

- raw roadway layer from `Travelway.gdb`
- raw signal sources from HMMS, Norfolk, and Hampton
- raw crash geometry from `crashdata.gdb / CrashData_Basic`
- later support layers still available for downstream prep:
  - `CrashData_Details` for direction-of-travel and maneuver fields
  - posted-speed segments for prototype study areas

## Main Processing Spine

### Phase 1: stage and normalize active inputs

1. Start from configured raw layers under the bounded active slice.
2. Stage raw inputs as GeoParquet, one file per active layer.
3. Merge the three signal sources and preserve source provenance.
4. Normalize staged layers into the working CRS.
5. Drop null geometry.
6. Keep crashes only for `CRASH_YEAR` `2022-2024`.

### Phase 2: build the bounded divided-road study slice

1. Filter normalized roads.
2. Decision: does the road row match the divided-road criteria?
3. Write `Study_Roads_Divided`.
4. Filter normalized signals.
5. Decision: does the signal fall inside the bounded divided-road slice?
6. Write `Study_Signals`.
7. Enrich each kept signal with one nearest study-road row plus distance, route identity, and deterministic tie metadata.
8. Write `Study_Signals_NearestRoad`.

### Phase 3: prepare later-module handoffs

1. Prepare experiment-ready crashes.
2. Join normalized `CrashData_Basic` to raw `CrashData_Details` on `DOCUMENT_NBR`.
3. Derive parsed travel direction and qualifying crash flags for the directionality experiment.
4. Prepare speed-informed signal context for the upstream/downstream prototype.
5. Join posted-speed segments to eligible signals.
6. Convert assigned speed into functional-distance and approach-length fields.

## Cluster B: Definitions / Processing Rules

- `Stage-inputs` contract:
  - copy active raw layers into one-file-per-layer GeoParquet
  - merge HMMS, Norfolk, and Hampton signals
  - retain Stage 1 source provenance
- `Normalize-stage` contract:
  - working CRS is `EPSG:3968`
  - drop null geometry
  - trim crashes to `2022-2024`
- study-slice rules:
  - roads keep facility codes `2` or `4`
  - exclude median code `1`
  - signals must intersect a `20`-foot road buffer
- nearest-road rule:
  - choose the nearest `Study_Roads_Divided` row
  - break ties deterministically by distance, `RTE_ID`, `RTE_NM`, `FROM_MEASURE`, `TO_MEASURE`, `EVENT_SOUR`, then `RowID`
- crash evidence prep:
  - use normalized crashes plus raw `CrashData_Details`
  - parse one clear cardinal direction of travel
  - mark single-vehicle straight-ahead qualifiers
- speed context prep:
  - use posted-speed segments as prototype support
  - assign a usable speed
  - map speed to functional distance and approach length

## Cluster C: Outputs / Handoff

- active handoff layers are:
  - `Study_Roads_Divided`
  - `Study_Signals`
  - `Study_Signals_NearestRoad`
  - normalized crashes
- the directionality experiment consumes:
  - `Study_Roads_Divided`
  - `Study_Signals_NearestRoad`
  - normalized crashes
  - `CrashData_Details`
- the upstream/downstream prototype reuses those roads, nearest-road signals, and prepared crash evidence, then adds speed-informed study-area context
- QC and traceability outputs include:
  - `stage1_input_manifest`
  - `stage1_normalized_manifest`
  - stage1b study-slice QC JSON
  - nearest-road QC JSON
  - parity manifest

## Visual Posture

- keep the three-phase processing spine visually dominant
- place raw inputs on the left and rules on the right so the center column reads as the main flow
- make the handoff box explicit so the reader can see exactly what later modules inherit
- keep crash-prep and speed-prep visibly downstream of the core study-slice build rather than presenting them as separate workflows

## Optional Caption

This figure shows how the bounded active slice turns raw roadway, signal, crash, and support layers into the specific study-road, signal, crash, and speed-context handoffs later used by the directionality experiment and the signal-centered upstream/downstream prototype.
