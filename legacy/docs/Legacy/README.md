# Crash Intersection Pipeline

Refactored `thirdstep` pipeline for functional-area segmentation, crash/access assignment, AADT enrichment, optional Oracle-aware directional context, and final QC output generation.

## Overview

This pipeline implements the roadway functional-area workflow used in the crash intersection analysis project. The current codebase is organized as a thin ArcPy entry point plus focused support modules.

Core responsibilities:

- stage and standardize GIS inputs
- construct signal-centered functional zones
- resolve overlapping signal ownership on divided roads
- segment roads into functional segments
- assign crashes and access points to segments
- enrich segments with canonical road metadata and AADT
- optionally run GeoPandas/Oracle-aware directional logic when the runtime is available
- write final outputs and QC artifacts back to the geodatabase

Main ArcPy entry point:

`C:\Users\Jameson.Clements\IntersectionCrashAnalysis\thirdstep\thirdstep_module_refactor\thirdstep.py`

ArcGIS Pro toolbox wrapper:

`CrashIntersectionPipeline.pyt`

## Current status

The recent wrapper/runtime fixes are now working as intended.

Verified from the latest acceptance run:

- partial resume runs now honor the toolbox phase range
- `REUSE_STAGED_OUTPUTS=True` is reaching the runtime correctly
- a Phase 3–5 run completes successfully as a partial run
- the wrapper no longer expects final outputs for a Phase 3–5 run
- final-output map-add behavior is now phase-aware

A successful acceptance example is:

- `Phase start = 3`
- `Phase stop = 5`
- `Reuse staged outputs = True`

Expected runtime header:

- `PHASE_RANGE=3-5`
- `REUSE_STAGED_OUTPUTS=True`

## Module layout

The refactored module directory contains:

- `thirdstep.py`  
  Thin orchestration entry point. Runs the major phases in order.

- `config.py`  
  Central configuration for input feature class names, staging/output names, tolerances, behavior flags, Oracle CSV paths, and field-candidate logic.

- `logging_utils.py`  
  Message, timing, count, and phase logging helpers.

- `arcpy_utils.py`  
  Shared ArcPy helpers for field lookup, copying/projecting, joins, layers, length/midpoint calculations, and QC/report helpers.

- `field_normalization.py`  
  Canonical field/value normalization, missing-value detection, and road-identity preservation logic.

- `backfill.py`  
  Missing-only transfer and targeted fallback logic for segment canonical metadata and AADT.

- `geometry_pipeline.py`  
  ArcPy geometry-heavy phases including speed assignment, zone creation, neighbor trimming, claim cleanup, and segmentation.

- `assignments.py`  
  Initial ArcPy crash and access assignment logic.

- `geopandas_oracle.py`  
  Optional GeoPandas/pandas/shapely export, Oracle CSV loading, directional labeling, and summary logic.

- `writeback_qc.py`  
  Final schema defaults, density metrics, QC flag consolidation, QC layers, and QC summary reporting.

## Execution order

`thirdstep.py` runs these phases in order:

1. Input staging
2. Functional-area construction
3. Signal-ownership cleanup
4. Road segmentation
5. Initial ArcPy crash/access/AADT assignments
6. GeoPandas prep/export
7. GeoPandas directional pipeline
8. Final write-back to geodatabase
9. QA / diagnostics
10. Cleanup

See `docs/phase_state_contract.md` for the current phase-by-phase contract, including resume prerequisites and required fields.

## Default inputs

From `config.py`, the default input feature class names are:

- `roads   = Travelway`
- `signals = Master_Signal_Layer`
- `crashes = CrashData_Basic`
- `access  = layer_lrspoint`
- `aadt    = New_AADT`
- `speed   = SDE_VDOT_SPEED_LIMIT_MSTR_RTE`

These are expected to exist in the active ArcGIS Pro workspace/geodatabase.

## Verified source-layer inventory

The current docs were checked against the verified source-layer inventory in the uploaded field-checked documentation set.

### Travelway
Example verified fields:
- `RTE_NM`
- `FROM_MEASURE`
- `TO_MEASURE`
- `RTE_FROM_M`
- `RTE_TO_MSR`
- `RTE_COMMON`
- `RTE_TYPE_N`
- `RTE_CATEGO`
- `RIM_ACCESS`
- `MEDIAN_WID`

### Master_Signal_Layer
Example verified fields:
- `REG_SIGNAL_ID`
- `SIGNAL_NO`
- `INTNO`
- `INTNUM`
- `MAJ_NAME`
- `MINOR_NAME`
- `STATUS`

### CrashData_Basic
Example verified fields:
- `DOCUMENT_NBR`
- `CRASH_YEAR`
- `CRASH_DT`
- `RTE_NM`
- `RNS_MP`
- `NODE`
- `OFFSET`
- `INTERSECTION_TYPE`

### layer_lrspoint
Example verified fields:
- `ACCESS_CONTROL`
- `ACCESS_DIRECTION`
- `CROSS_STREET`
- `NUMBER_OF_APPROACHES`
- `_rte_nm`
- `_m`

### New_AADT
Example verified fields:
- `AADT`
- `AADT_YR`
- `AADT_QUALITY`
- `LINKID`
- `MASTER_RTE_NM`
- `RTE_NM`
- `FROM_MEASURE`
- `TO_MEASURE`

### SDE_VDOT_SPEED_LIMIT_MSTR_RTE
Example verified fields:
- `CAR_SPEED_LIMIT`
- `TRUCK_SPEED_LIMIT`
- `ROUTE_FROM_MEASURE`
- `ROUTE_TO_MEASURE`
- `ROUTE_COMMON_NAME`

Important scope note:

- the uploaded field-checked docs validate source-layer names and source fields
- they do **not** validate pipeline-created staging datasets, pipeline-created output fields, QC fields, or Oracle CSV columns

## Current outputs

Primary outputs:

- `Final_Functional_Segments`
- `QC_ThirdStep`

Optional outputs, depending on config/runtime:

- `Final_Study_Signals`
- `Final_Functional_Zones_Stage3`
- `QC_UnknownDirection`
- `QC_OverlapClaims`
- `QC_CrashesFarSnap`

Notes:

- `Final_Functional_Segments` is the main authoritative deliverable
- optional final copies depend on `WRITE_OPTIONAL_OUTPUT_COPIES`
- QC review layers depend on `WRITE_QC_LAYERS`

## Important current behavior

### Resume and partial-run behavior

This is now working correctly.

- toolbox phase selections are being passed into runtime
- staged-output reuse is being honored
- partial runs no longer pretend final outputs should exist
- final map-add expectations are now gated by the phase range

### Segment field expectations by Phase 5

Given the current code path, the Phase 5 contract should be interpreted as:

Required by the end of Phase 5:
- `LinkID_Norm`
- `RouteID_Norm`
- `DirCode_Norm`
- `AADT`

Informational / optional through Phase 5:
- `FromNode_Norm`
- `ToNode_Norm`

That matches the current implementation better than forcing node-field completion before Phase 5.

### AADT matching strategy

The recommended default is the faster baseline path.

- route+measure AADT matching should remain disabled by default
- targeted fallback should focus on the normal missing-only baseline path
- slower route+measure logic should be treated as an optional debug/profiling path until it is redesigned

## Oracle support

The current refactored module does **not** connect to Oracle directly. It expects pre-exported Oracle reference CSVs.

Relevant config entries:

- `ORACLE_BROAD_LOOKUP_SOURCE`
- `ORACLE_GIS_KEYS_SOURCE`

Expected broad Oracle columns:

- `TMSLINKID`
- `RTE_NM`
- `BEGINNODE`
- `ENDNODE`
- `LINKSEQUENCE`
- `ROUTEMILEPOINT`
- `BEGINOFFSET`
- `ENDOFFSET`
- `AVERAGEDAILYTRAFFIC`
- `RURALURBANDESIGNATION`

Expected GIS-key columns:

- `LINKID`
- `MASTER_RTE_NM`
- `FromNode_Norm`
- `ToNode_Norm`
- `SegMid_M`
- `Signal_M`
- `Delta_M`
- `Flow_Role`
- `AADT_GIS`

If `ORACLE_BROAD_LOOKUP_SOURCE` is unset or missing, Oracle-aware matching is effectively skipped.

## Practical use notes

- edit `config.py` when changing inputs, flags, tolerances, or Oracle CSV paths
- use the toolbox for the normal ArcGIS Pro workflow
- run `thirdstep.py` directly only when you want to execute the entry point outside the toolbox
- keep all refactored module files together in the same folder
- use `docs/workflow.md` for run instructions
- use `docs/phase_state_contract.md` for resume, phase, and field-contract rules
