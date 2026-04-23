# Phase State Contract

Authoritative operational contract for phase execution, staged outputs, resume prerequisites, and canonical field expectations in the refactored `thirdstep` pipeline.

This document is meant to be the stable reference for:

- what each phase requires to start
- what each phase produces
- whether an output is staged or final
- what must already exist for resume mode
- which canonical fields are required versus optional at each major milestone

## Why this document exists

The pipeline now supports partial/resume execution in a meaningful way. That makes it important to separate:

- **task tracking** in `THIRDSTEP_NEXT_STEPS.md`
- **run instructions** in `docs/workflow.md`
- **operational truth** in this phase/state contract

Use this document when deciding whether a resume run is valid, whether a field audit is actually reporting a problem, or whether a missing output is expected for the selected phase range.

---

## 1. Phase index

`thirdstep.py` currently runs phases in this order:

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

---

## 2. Per-phase inputs and outputs

## Phase 1 — Input staging

### Requires to start
- configured source feature classes exist in the active workspace:
  - `Travelway`
  - `Master_Signal_Layer`
  - `CrashData_Basic`
  - `layer_lrspoint`
  - `New_AADT`
  - `SDE_VDOT_SPEED_LIMIT_MSTR_RTE`

### Produces
Typical staged datasets include:
- projected and/or copied study datasets
- normalized working copies of roads, signals, crashes, access, AADT, and speed layers

### Output type
- staged only

### Notes
This phase prepares the working data context for everything downstream.

---

## Phase 2 — Functional-area construction

### Requires to start
- Phase 1 staging outputs exist

### Produces
Typical staged outputs include:
- `Study_Roads_Divided`
- `Study_Signals`
- `Study_Signals_Speed`
- `Zone1_Critical`
- `Zone2_Full`
- `Zone2_Functional`
- `All_Functional_Zones`
- related zone-construction intermediates

### Output type
- staged only

### Notes
These outputs define the signal-centered geometry that later claim/segmentation logic depends on.

---

## Phase 3 — Signal-ownership cleanup

### Requires to start
- Phase 2 zone outputs exist
- divided-road study roads and signal-zone relationship layers are available

### Produces
Typical staged outputs include:
- `Zone_Road_Claims`
- `Zone_Road_Claims_Clean`
- trimmed/claimed road pieces
- neighbor-based trim/QC fields related to claim cleanup

### Output type
- staged only

### Notes
This phase resolves contested ownership of road pieces across signal influence zones.

---

## Phase 4 — Road segmentation

### Requires to start
- cleaned road-claim pieces from Phase 3 exist

### Produces
Typical staged outputs include:
- `Functional_Segments_Raw`
- `Functional_Segments_Clean`
- intermediate segmented road feature classes

### Output type
- staged only

### Notes
This is the first phase where the core segment geometry becomes stable enough for later assignment/enrichment.

---

## Phase 5 — Initial ArcPy crash/access/AADT assignments

### Requires to start
- cleaned segments from Phase 4 exist
- staged crash, access, roads, and AADT layers exist

### Produces
Typical staged outputs include:
- `Crash_Assigned_Initial`
- `Access_Assigned_Initial`
- segment-level inherited/fallback canonical metadata
- segment-level ArcPy assignment fields and counts

### Output type
- staged only

### Notes
This is the main ArcPy assignment phase. It is also the most important partial-run checkpoint for non-GeoPandas debugging.

---

## Phase 6 — GeoPandas prep/export

### Requires to start
- Phase 5 segment outputs exist
- GeoPandas export/runtime path is enabled and available if the phase is expected to run meaningfully

### Produces
Typical staged outputs include:
- exported/intermediate tables for GeoPandas processing
- linear-reference helper tables
- segment/signal reference tables for downstream directional logic

### Output type
- staged only

### Notes
If GeoPandas runtime is unavailable, this phase may be reduced, skipped, or limited depending on configuration and guards.

---

## Phase 7 — GeoPandas directional pipeline

### Requires to start
- Phase 6 prep/export artifacts exist
- pandas/geopandas/shapely runtime is available if the directional path is enabled
- optional Oracle CSVs exist if Oracle-aware matching is intended

### Produces
Typical staged outputs include:
- directional labels
- Oracle match/context fields
- segment-level supplemental tabular results for write-back

### Output type
- staged only

### Notes
This phase is optional in practice because runtime availability can disable it.

---

## Phase 8 — Final write-back

### Requires to start
- the final segment feature class to be written can be built from prior staged outputs
- any optional GeoPandas/Oracle attributes to be written back are available if enabled

### Produces
Primary final outputs:
- `Final_Functional_Segments`
- `QC_ThirdStep`

Optional final outputs:
- `Final_Study_Signals`
- `Final_Functional_Zones_Stage3`
- QC review layers such as:
  - `QC_UnknownDirection`
  - `QC_OverlapClaims`
  - `QC_CrashesFarSnap`

### Output type
- final

### Notes
This is the earliest phase at which the wrapper should expect final outputs to exist.

---

## Phase 9 — QA / diagnostics

### Requires to start
- final write-back output exists or equivalent final in-memory state exists

### Produces
- QC reporting
- QC summaries
- optional review layers and summary counts

### Output type
- final/supporting

### Notes
This phase is for validation, not core geometry generation.

---

## Phase 10 — Cleanup

### Requires to start
- prior phases have completed or exited cleanly enough for cleanup to proceed

### Produces
- removed temporary datasets depending on cleanup policy
- final retained deliverables

### Output type
- housekeeping only

---

## 3. Resume prerequisites

Resume mode is valid only when the required earlier-phase artifacts already exist and are trustworthy.

## Resume at Phase 3
Must already exist:
- staged/projected inputs from Phase 1
- signal/zone outputs from Phase 2

## Resume at Phase 4
Must already exist:
- valid cleaned claim inputs from Phase 3 or the exact Phase 3 predecessors needed to build them

## Resume at Phase 5
Must already exist:
- valid segmented roads from Phase 4
- the necessary staged roads/crashes/access/AADT reference layers

## Resume at Phase 6
Must already exist:
- valid Phase 5 assignment outputs
- segment-level inherited/fallback metadata from the ArcPy path

## Resume at Phase 7
Must already exist:
- valid Phase 6 exports/helpers
- GeoPandas runtime available if the directional phase is expected to run

## Resume at Phase 8
Must already exist:
- the complete staged segment state needed for final write-back
- optional GeoPandas/Oracle supplemental data if it is expected to be written back

## Resume at Phase 9
Must already exist:
- final write-back outputs or equivalent final segment/QC state

### Operational rule
If you cannot state clearly which upstream artifacts the selected phase depends on, do not resume there.

---

## 4. Partial-run output expectations

This is the wrapper-facing rule set.

### If `phase_stop < 8`
- do **not** expect final outputs such as `Final_Functional_Segments`
- do **not** add final outputs to the map
- treat a clean stop as a valid partial success if all requested phases completed

### If `phase_stop >= 8`
- final outputs may be expected
- map-add behavior may be enabled for final outputs

This rule is already consistent with the current patched wrapper behavior.

---

## 5. Canonical field contract

This section defines required versus optional canonical metadata at major milestones.

## After road normalization / early staging

Expected required road-identity context where available:
- `RouteID_Norm`
- `RouteNm_Norm`
- `DirCode_Norm`

Often optional or source-dependent at this stage:
- `LinkID_Norm`
- `FromNode_Norm`
- `ToNode_Norm`
- `AADT`

## After road AADT enrichment

Required on roads for the normal downstream identity path:
- `LinkID_Norm`
- `RouteID_Norm`
- `DirCode_Norm`
- `AADT`

Still optional/opportunistic:
- `FromNode_Norm`
- `ToNode_Norm`

## After segment direct inheritance in Phase 5

Operationally required for Phase 5 identity checks:
- `LinkID_Norm`
- `RouteID_Norm`
- `DirCode_Norm`
- `AADT`

Informational only through this checkpoint:
- `FromNode_Norm`
- `ToNode_Norm`

### Important interpretation
Given the current code, node fields are not part of the core required fallback contract for Phase 5. They should be treated as expected-missing or informational through this phase unless the implementation changes.

## After segment fallback in Phase 5

Required by the end of the Phase 5 fallback path:
- `LinkID_Norm`
- `RouteID_Norm`
- `DirCode_Norm`
- `AADT`

Optional / informational:
- `FromNode_Norm`
- `ToNode_Norm`

This is the current recommended audit contract.

## After final write-back

Required deliverable fields depend on whether the run used only ArcPy or also GeoPandas/Oracle enrichment.

Always expected on the final segment deliverable:
- core segment geometry
- assignment counts/metrics
- canonical identity fields required by the ArcPy path
- QC fields written by the final QC step

Conditionally expected:
- directional fields from GeoPandas
- Oracle match/context fields
- `OracleAADT`
- `AADT_Source`
- crash summary enrichments from the GeoPandas path

---

## 6. Auditing guidance

The audit should only escalate fields that are truly contract-critical for the current milestone.

### Phase 5 segment audit should treat as required
- `LinkID_Norm`
- `RouteID_Norm`
- `DirCode_Norm`
- `AADT`

### Phase 5 segment audit should treat as informational / expected-missing
- `FromNode_Norm`
- `ToNode_Norm`

### Why
The current code already:
- uses node fields opportunistically
- does not require node fields to complete the main Phase 5 fallback path
- uses roads/AADT fallback mainly to preserve canonical identity and AADT, not to guarantee nodes

That means flagging every missing node field as an unexpected failure at Phase 5 creates noise rather than useful signal.

---

## 7. AADT strategy contract

Current recommended default behavior:

- keep the faster baseline AADT path as the default
- treat route+measure AADT matching as disabled by default
- use slower route+measure logic only as a debug/profiling path until it is redesigned

Why:
- the baseline path is operationally sufficient
- the recent residual miss count is very small
- the cost/benefit of the slower route+measure approach is not favorable right now

---

## 8. Definition of success for common runs

## Successful Phase 3–5 resume run
A Phase 3–5 run is successful when:

- the runtime header reports `PHASE_RANGE=3-5`
- `REUSE_STAGED_OUTPUTS=True` when requested
- Phases 3, 4, and 5 all complete
- the run ends as partial success
- the wrapper does not expect final outputs

## Successful full run
A full run is successful when:

- all intended phases complete
- `Final_Functional_Segments` is written
- QC output is written as expected
- optional outputs are judged relative to the config flags and runtime path

---

## 9. When to update this document

Update this contract when any of the following changes:

- a phase boundary changes
- a staged output name changes materially
- resume prerequisites change
- the wrapper’s final-output expectations change
- canonical field requirements change
- node fields become truly required earlier in the pipeline
- the AADT default strategy changes again
