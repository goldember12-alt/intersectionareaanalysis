# Workflow

Operational runbook for the refactored crash intersection pipeline.

This document explains how to run the current `thirdstep` module, how partial/resume execution now works, and when to use the optional Oracle-aware pass.

## Purpose

Use this workflow when you need to:

- run the standard ArcPy segmentation pipeline from ArcGIS Pro
- perform a partial resume run starting at a later phase
- run the module directly for debugging
- perform a second pass with Oracle reference CSVs
- understand which outputs are expected for a full run versus a partial run

## Current runtime behavior

The current wrapper and module now support partial resume execution correctly.

Confirmed behavior:

- toolbox `Phase start` and `Phase stop` reach the runtime correctly
- `Reuse staged outputs` reaches the runtime correctly
- a partial Phase 3–5 run ends in `PARTIAL SUCCESS` rather than trying to write full final outputs
- final-output expectations are skipped automatically for runs that stop before final write-back

That means the Phase 3–5 acceptance case is now a valid operational debug pattern.

## A. Standard ArcGIS Pro run

Use this when you want the normal GIS workflow and are not supplying Oracle CSVs.

1. Place the refactored module files in:

   `C:\Users\Jameson.Clements\IntersectionCrashAnalysis\thirdstep\thirdstep_module_refactor`

2. Make sure the toolbox points to that folder.

3. Open `config.py` and verify the basic inputs:

   - `roads   = Travelway`
   - `signals = Master_Signal_Layer`
   - `crashes = CrashData_Basic`
   - `access  = layer_lrspoint`
   - `aadt    = New_AADT`
   - `speed   = SDE_VDOT_SPEED_LIMIT_MSTR_RTE`

4. For a non-Oracle run, leave:

   - `ORACLE_BROAD_LOOKUP_SOURCE = None`
   - `ORACLE_GIS_KEYS_SOURCE = None`

5. In ArcGIS Pro, run the toolbox tool.

6. Choose toolbox options as needed:

   - run `clearinggdb.py`
   - run `thirdstepfigures.py`
   - add final outputs to the active map

7. Review expected outputs after completion:

   Main outputs:
   - `Final_Functional_Segments`
   - `QC_ThirdStep`

   Optional outputs:
   - `Final_Study_Signals`
   - `Final_Functional_Zones_Stage3`
   - QC review layers if enabled

## B. Partial/resume run from ArcGIS Pro

Use this when a prior run already created the needed staged datasets and you want to restart at a later phase.

### Recommended acceptance/debug case

Use this exact setup to validate resume behavior:

- `Run clear step = False`
- `Run figures step = False`
- `Add output to map = False`
- `Phase start = 3`
- `Phase stop = 5`
- `Reuse staged outputs = True`

Expected runtime header:

- `PHASE_RANGE=3-5`
- `REUSE_STAGED_OUTPUTS=True`

Expected ending:

- `PARTIAL SUCCESS. COMPLETED THROUGH PHASE 5.`

Expected wrapper behavior:

- no expectation that final outputs exist
- no attempt to add final outputs to the map

### General resume guidance

Before starting at a later phase, make sure the staged outputs required by that phase already exist. See `docs/phase_state_contract.md` for the authoritative prerequisite list.

Operational rule:

- use resume mode only when the earlier-phase outputs already exist and are trustworthy
- otherwise restart from an earlier phase or run a clean full pass

## C. Direct module run without the toolbox

Use this only for debugging or isolated testing.

1. Open the ArcGIS Pro Python environment.
2. Change into the module folder.
3. Run `thirdstep.py`.

Notes:

- `thirdstep.py` expects sibling module files to stay in the same folder
- the active ArcGIS Pro workspace/geodatabase still needs to be configured correctly for the feature class names in `config.py`
- direct runs are useful for debugging module behavior, but the toolbox remains the normal front-end

## D. Oracle-aware workflow

Use this only when you already have exported Oracle reference CSVs and want a second-pass refinement.

The current code does **not** query Oracle directly.

### Step 1: run the standard GIS pipeline first

First run the standard GIS pipeline with:

- `ORACLE_BROAD_LOOKUP_SOURCE = None`
- `ORACLE_GIS_KEYS_SOURCE = None`

The first pass should build the normal GIS segment outputs successfully.

### Step 2: generate Oracle reference CSVs separately

Run your separate Oracle retrieval/export process.

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

### Step 3: point config at the exported CSVs

Set in `config.py`:

- `ORACLE_BROAD_LOOKUP_SOURCE = <path>`
- `ORACLE_GIS_KEYS_SOURCE = <path or None>`

Keep the Oracle-related behavior flags enabled only if you are intentionally using the Oracle pass.

### Step 4: run the pipeline again

Run through the toolbox or directly through `thirdstep.py`.

Review Oracle-related final fields such as:

- `OracleMatchStatus`
- `OracleMatchLevel`
- `OracleTMSLINKID`
- `OracleRouteNm`
- `OracleBeginNode`
- `OracleEndNode`
- `OracleAADT`
- `AADT_Source`

## E. What the toolbox currently does

`CrashIntersectionPipeline.pyt` currently performs this sequence:

1. validate the refactored module directory and required files
2. optionally run `clearinggdb.py`
3. set runtime flags for the current run
4. clear cached module imports so the current phase/config settings are re-read
5. run `thirdstep.py`
6. optionally run `thirdstepfigures.py`
7. optionally add final outputs to the active map only when the phase range is expected to produce them

This phase-aware final-output behavior is important for partial runs.

## F. Recommended practical workflow

For normal use:

1. update `config.py`
2. run the toolbox
3. review `Final_Functional_Segments` and `QC_ThirdStep`

For a resume/debug run:

1. confirm staged prerequisites exist
2. set the desired phase range
3. set `Reuse staged outputs = True`
4. disable final map-add unless you are finishing the run
5. review the log header and phase completion messages

For an Oracle pass:

1. finish a standard GIS run first
2. generate Oracle CSVs separately
3. set Oracle CSV paths in `config.py`
4. run the second pass
5. review Oracle-related output fields and QC

## G. Important cautions

- do not move individual module files out of the refactored folder
- do not expect Oracle-aware logic to run unless valid Oracle CSV paths are set
- `USE_GEOPANDAS = True` in config does not guarantee runtime availability
- `Final_Study_Signals` and `Final_Functional_Zones_Stage3` are optional outputs
- `Final_Functional_Segments` is the main authoritative deliverable
- do not treat partial runs as full-pipeline outputs unless the stopping phase actually includes final write-back
