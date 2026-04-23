# Repo Redesign Plan

## Purpose

This document is the first-pass execution plan for redesigning the repository under the current `docs/overview_methodology.md` and `AGENTS.md`.

It is not a methodology document.
It is not a historical summary.
It is an operational redesign plan.

Its purpose is to help Codex turn the current repository from a large, confusing, artifact-heavy structure into a smaller, clearer, more trustworthy active system.

Current package-path note:
- the active package directory is now `src/`
- historical references in this plan to `stage1_portable/` describe the same package under its former name

Current status note:
- the standard `stage-inputs` through `check-parity` slice has been rerun successfully in this working tree
- grouped output areas have been restored for `directionality_experiment` and `upstream_downstream_prototype`
- `high_confidence_upstream_downstream_analysis` has been restored as a direct-entry downstream step with its own grouped output contract
- this file remains a redesign plan, not the authoritative current-state note; use [current_repo_state_20260416.md](current_repo_state_20260416.md) and [active_workflow.md](active_workflow.md) for present-tense workflow status

The current bounded question is:

> **How should the repository be redesigned so that signals become the anchor object, a bounded near-signal evidence model can be assembled around them, and supporting flow-orientation inference can be used to classify crashes as approaching or leaving or upstream or downstream relative to the signal, without inherited repository complexity dominating the work?**

---

## Executive Summary

### What is wrong with the repository now

The repository currently mixes several different histories and intentions in one active space:

- ArcPy-era orchestration and runtime families
- migration-era GeoPandas portability work
- Oracle-safe bridge and matching branches
- packaging-heavy handoff and consumer layers
- generated artifacts and parity debris
- local cache and environment clutter
- documentation from multiple incompatible project postures

This creates several concrete problems:

1. there is no single obvious active execution story
2. there is no clean line between active code and preserved history
3. generated outputs sit next to source as if they are part of the design
4. methodology-specific machinery remains active by inertia
5. complexity from earlier abstract orientation assumptions still shapes the repo

### What the active repository should become

The active repository should become:

- one authoritative methodology
- one authoritative AGENTS contract
- one small active code path
- one obvious active doc set
- one clean raw data area
- one ignored working area for regenerated artifacts
- one clearly marked legacy area for preserved history and retired methods

### Biggest simplification opportunities

The largest first-pass gains come from:

- removing ArcPy families from the active path
- freezing the Oracle-safe packaging ladder as legacy reference, not active architecture
- splitting `stage1_portable` into a small active core and a preserved legacy portability branch
- removing generated run artifacts from the active repo story
- reducing root-level clutter so the active workflow is visible in one screen

---

## First-Pass Operating Rules

These rules govern execution of this redesign plan.

### Rule 1: First pass is reclassification and isolation, not full methodological completion

The first redesign pass is mainly about:

- isolating legacy material
- shrinking the active surface area
- clarifying what is current
- separating trusted guidance from untrusted implementation residue

It is **not** required to solve the full signal-centered downstream-classification problem in this pass.

### Rule 2: Preserve by moving before deleting

For code, docs, and outputs with any plausible analytical or historical value:

- move to `legacy/`
- stop treating them as active
- stop importing them
- stop documenting them as current

Do **not** hard delete such material in the first pass unless it is clearly expendable.

### Rule 3: Only obvious clutter should be directly removed in pass 1

Items that may be directly removed or ignored in the first pass include:

- IDE clutter
- temp/cache directories
- runtime spill
- pycompile residue
- duplicate output forms with no distinct meaning
- untracked local environment noise

### Rule 4: One active path by end of pass 1

By the end of the first redesign pass, the repository must expose:

- one active methodology document
- one active AGENTS file
- one active workflow note
- one clearly named active execution path
- one clearly marked legacy area

### Rule 5: `stage1_portable` must be decomposed, not treated as one unit

Codex must not classify `stage1_portable` as a single block.

It must be split into:
- active bootstrap/config/input-handling core
- inspect-further study-slice core
- inspect-further bridge-key evidence modules
- legacy Oracle lookup/matching chain
- legacy Oracle-safe packaging ladder
- legacy non-directional Stage 1C branch

### Rule 6: Outputs are evidence, not architecture

Generated outputs should be treated as:
- run evidence
- comparison evidence
- validation evidence

They should not remain part of the active repository architecture story.

---

## Current Repository Interpretation

### Best current reading of the repository

The repository appears to contain at least three overlapping execution stories:

1. **ArcPy-era workflow**
   - `firststep/`
   - `secondstep/`
   - `thirdstep/`
   - `run_all.py`
   - `clearinggdb.py`

2. **GeoPandas portability / migration-era workflow**
   - `stage1_portable/`
   - `config/stage1_portable.toml`
   - associated portability docs
   - staging/normalized/output artifacts

3. **Oracle-safe bounded branch and packaging family**
   - bridge-key audits
   - Oracle lookup/disambiguation/matching
   - safe-subset narrowing
   - downstream-safe packaging ladder
   - Stage 1C non-directional completion chain

In addition, the repository contains:
- authoritative raw inputs
- generated artifacts
- parity outputs
- docs from both old and new project postures
- local runtime clutter

### Major repo problem

The repository still behaves as though proving a migration path is the main job.

Under the new methodology and AGENTS contract, that is no longer the governing question.

The governing question is whether the active repository structure helps the current bounded analytical problem:
- signal-centered near-signal evidence modeling
- supporting flow-orientation inference on divided carriageways near signals
- approaching-versus-leaving and upstream/downstream interpretation near signals
- simplest truthful active workflow

Large portions of the current structure do not.

---

## Classification Table

## A. Keep Active

| Component | Current Apparent Role | Classification | Rationale | Risk if Kept Active | Reuse if Moved |
|---|---|---|---|---|---|
| `AGENTS.md` | authoritative operating contract | Keep active | Governing repo contract | none | n/a |
| `docs/overview_methodology.md` | authoritative methodology | Keep active | Governing methodological posture | none | n/a |
| `pyproject.toml` | build/environment config | Keep active | Needed for runnable Python path | may drift if not simplified | low |
| `Intersection Crash Analysis Layers/` | authoritative raw inputs | Keep active | Raw data contract remains essential | low if clearly separated | n/a |
| `stage1_portable` bootstrap/config/input-handling core | current runnable open-source foundation | Keep active | Best current foundation for a smaller active system | command sprawl unless trimmed | medium |

---

## B. Inspect Further Before Deciding

| Component | Current Apparent Role | Classification | Rationale | Risk if Kept Active | Reuse if Moved |
|---|---|---|---|---|---|
| `.gitignore` | ignore policy | Inspect further | Current ignore behavior likely conflicts with new active/legacy/work split | repo hygiene remains confusing | low |
| `config/stage1_portable.toml` | active config mixed with old assumptions | Inspect further | Useful registration point, but likely embeds migration-era and Oracle-specific assumptions | old architecture remains encoded in config | medium |
| `Intersection Crash Analysis Layers/VDOT_Bidirectional_Traffic_Volume_2024.geojson` | supplemental flow-orientation candidate | Inspect further | Could support simpler non-Oracle or hybrid methods | false confidence if treated as authoritative too early | high |
| `stage1_portable/study_slice.py` | main study-slice and segment-building logic | Inspect further | Closest thing to active analytical core, but monolithic and likely overscoped | active core remains hard to explain and validate | high |
| `stage1_portable` bridge-key evidence/audit modules | supplemental evidence about link identity | Inspect further | May contain useful reusable logic or data understanding | can re-anchor redesign to bridge-key-first thinking | high |
| `stage1_portable/stage1b_study_roads_link_restoration_normalized_route_key.py` | bridge-bearing restoration logic | Inspect further | Could contain reusable lineage logic | can preserve old Oracle-centered assumptions | medium |
| `stage1_portable/stage1b_segment_link_inheritance.py` | downstream identity inheritance logic | Inspect further | May hold useful deterministic lineage logic | keeps active path coupled to old branch shape | medium |
| `docs/stage1_staging_contract.md` | portable input contract | Inspect further | Useful source of concrete staging behavior | preserves migration-first language if left active unchanged | medium |
| `artifacts/staging/` | generated staging outputs | Inspect further | May still be useful as work products | source/output boundary remains blurry | medium |
| `artifacts/normalized/` | generated normalized outputs | Inspect further | May still be useful as work products | repo treats generated boundaries like source | medium |
| `artifacts/parity/` | validation/parity outputs | Inspect further | Some validation may still be worth preserving | validation becomes tangled with obsolete architecture | medium |

---

## C. Move to Legacy

| Component | Current Apparent Role | Classification | Rationale | Risk if Kept Active | Reuse if Moved |
|---|---|---|---|---|---|
| `firststep/` | ArcPy-era workflow family | Move to legacy | Clearly legacy under new contract | false-active noise | medium |
| `secondstep/` | ArcPy-era workflow family | Move to legacy | Clearly legacy under new contract | false-active noise | medium |
| `thirdstep/` | ArcPy-era workflow family and refactor area | Move to legacy | Historically useful, not active default | confusing parallel architecture | high |
| `run_all.py` | legacy orchestration | Move to legacy | Not part of desired active path | users mistake it for current entrypoint | low |
| `clearinggdb.py` | legacy reset/orchestration | Move to legacy | ArcGIS-era reset logic should not look current | users mistake it for current workflow | low |
| Oracle lookup/disambiguation/matching family inside `stage1_portable/` | Oracle-dependent flow-orientation path | Move to legacy | Valuable comparison material, not default active method | Oracle remains mandatory by inertia | high |
| Oracle-safe packaging ladder inside `stage1_portable/` | packaging-heavy bounded branch | Move to legacy | Documentation already shows this family is packaging-heavy | presentation machinery continues to masquerade as active methodology | low |
| non-directional Stage 1C completion family inside `stage1_portable/` | bounded branch completion | Move to legacy | Useful historical endpoint, not current redesign core | active repo remains anchored to old bounded branch | medium |
| `docs/stage1_portability.md` | migration-path command ladder doc | Move to legacy | Historical migration doc, not active guidance | active repo remains ladder-shaped | medium |
| `docs/stage1b_study_slice.md` | migration-era slice contract | Move to legacy | Useful history, not active workflow note | over-preserves stage framing | medium |
| `docs/stage2_oracle_safe_branch_architecture_summary.md` | Oracle-safe branch documentation | Move to legacy | Documents an overbuilt branch | legitimizes ladder as target architecture | medium |
| `docs/stage2_oracle_safe_branch_packaging_ladder_cleanup_plan.md` | packaging-ladder cleanup doc | Move to legacy | Useful as historical evidence only | keeps branch shape psychologically active | medium |
| `docs/stage2_oracle_safe_branch_traceability_map.md` | Oracle-safe traceability doc | Move to legacy | Historical branch mapping, not active design | encourages branch preservation | medium |
| `docs/Legacy/` and other already-legacy docs | preserved historical documentation | Move to legacy | Should be clearly out of active doc path | low | medium |
| `oracle_exports/` | Oracle reference exports | Move to legacy | Reference-only until proven necessary | preserves Oracle bias | high |
| `layer_summaries/` | field-discovery summaries | Move to legacy | Useful reference, not active workflow | root clutter | medium |
| `artifacts/output/stage1b_study_slice/` | generated bounded run outputs | Move to legacy | Important run evidence, not active structure | analysts mistake artifacts for active contracts | high |
| `artifacts/output/stage1_bridge_boundary/` | bridge-boundary run outputs | Move to legacy | Historical run evidence, not active structure | analysts mistake artifacts for active contracts | high |

---

## D. Likely Remove

| Component | Current Apparent Role | Classification | Rationale | Risk if Kept Active | Reuse if Moved |
|---|---|---|---|---|---|
| `Intersection Crash Analysis Layers/VDOT_Bidirectional_Traffic_Volume_2024 (1)/` | duplicate traffic-volume export form | Likely remove | Appears duplicate unless field inspection proves otherwise | duplicate-source confusion | low |
| `artifacts/pycompile*/` | runtime spill | Likely remove | No analytical value | severe clutter | none |
| `artifacts/Users/` | accidental runtime spill | Likely remove | No analytical value | severe clutter | none |
| `.idea/` | IDE clutter | Likely remove/ignore | No analytical value | clutter and false repo size | none |
| `.tmp/` | temp clutter | Likely remove/ignore | No analytical value | clutter | none |
| `.npm-cache/`, `.npm-global/`, `.pip-cache/`, `pip_cache/`, `temp/`, `tmp/` | local cache/temp clutter | Likely remove/ignore | No analytical value | clutter | none |
| `intersection_crash_analysis.egg-info/` | build residue | Likely remove/ignore | No analytical value | clutter | none |
| `structure.txt` | root snapshot artifact | Likely remove/ignore | Temporary inspection output only | clutter | none |
| `.venv/` | local environment | Likely remove from repo view / ignore | Needed locally, not as repository content | source tree remains noisy | none |

---

## Active Repository Target Shape

The redesigned active repository should aim for a high-level shape like this:

```text
AGENTS.md
pyproject.toml
config/
  active.toml
docs/
  overview_methodology.md
  active_workflow.md
  method_comparison.md
  validation_notes.md
src/
  intersection_crash_analysis/
    config.py
    inputs.py
    staging.py
    study_slice.py
    directionality/
    crash_access.py
    validation.py
data/
  raw/
    base/
    supplemental/
work/              # ignored
  staging/
  normalized/
  runs/
legacy/
  arcpy/
  portability_branch/
  docs/
  outputs/
  reference/
```

### Design goals of this shape

- active code path visible immediately
- active docs visible immediately
- raw data separate from generated work
- legacy content preserved but clearly non-active
- no dozens of intermediate run products in the active root story
- no ambiguity about what Codex should read first

---

## Legacy Isolation Plan

### Move to legacy first

These should be moved first because they are unambiguous sources of active confusion:

- `firststep/`
- `secondstep/`
- `thirdstep/`
- `run_all.py`
- `clearinggdb.py`
- Oracle-safe branch docs
- already-legacy docs
- `oracle_exports/`
- `layer_summaries/`
- generated run outputs under `artifacts/output/*`

### Mark transitional for now

These may remain temporarily but must be clearly treated as transitional:

- `stage1_portable` bootstrap/staging core
- `config/stage1_portable.toml`
- `artifacts/staging/`
- `artifacts/normalized/`
- selected parity manifests or validation summaries

### Prevent future confusion

To keep Codex and humans from getting confused later:

1. create `legacy/README.md` that states legacy content is reference-only
2. stop importing from legacy in active code
3. stop documenting legacy paths as current workflow
4. move generated outputs under dated or named run folders
5. keep only one active workflow note
6. keep only one active execution path
7. update `.gitignore` to reflect active vs legacy vs work separation

---

## Methodology-Risk Diagnosis

### Main signs of overbuild

The repository contains several clear signals that inherited complexity has been preserved longer than necessary:

- The repo still acts as though proving a migration path is the primary job.
- The Oracle-safe branch accumulates contract, handoff, review, triage, decision-support, consumer, and minislice layers long after the data is already narrowed to a 77-row subset.
- The docs themselves describe this branch as packaging-heavy.
- `stage1_portable/study_slice.py` has grown into a very large module, suggesting the active problem boundary is unclear.
- The repo invested in documenting the ladder and cleaning the ladder instead of first deciding whether the ladder should remain active.
- ArcPy families, legacy orchestration, and `stage1_portable` still coexist without a clear retirement line.

### Where “working too hard” was likely mistaken for rigor

The clearest examples are:

- preserving a bridge-key + Oracle + re-audit + packaging chain as if it were natural active architecture
- producing many intermediate artifacts instead of retiring wrong assumptions
- treating documentation of the ladder as progress even when the ladder itself may be the wrong active design
- maintaining branch-specific packaging helpers on top of a methodology that is no longer the active target

### Key redesign insight

Oracle linkage may still prove useful later.

But the current repo structure appears to have treated one Oracle-shaped flow-orientation path as the default target before explicitly comparing it against simpler empirical or hybrid methods for divided roads.

That is exactly the type of methodological inertia the redesign is meant to stop.

---

## Immediate Next Actions

The first concrete redesign sequence should be:

1. Freeze the current repo state as evidence, not architecture.
2. Create `legacy/` and move unambiguous ArcPy-era code and legacy docs there.
3. Move generated historical outputs into a dated or named legacy run area.
4. Remove or ignore obvious runtime spill and local clutter.
5. Split `stage1_portable` conceptually into:
   - active core
   - inspect-further core
   - legacy portability branch
6. Write one short active workflow note naming the real bounded task:
   - signal-centered near-signal evidence modeling
   - supporting flow-orientation inference on divided carriageways near signals
   - approaching-versus-leaving and upstream/downstream interpretation support
7. Compare candidate flow-orientation methods explicitly before preserving any Oracle family as active.
8. Rebuild or preserve the smallest trustworthy active vertical slice:
   - load raw roads, signals, crashes, and the most promising supplemental flow-orientation candidate
   - produce the divided-road study slice
   - test 2–4 candidate flow-orientation methods on representative corridors
   - report coverage, ambiguity, conflict rate, and validation notes

---

## Open Questions

These questions should remain open until directly examined:

1. Does the traffic-volume GeoJSON carry a trustworthy identity or direction signal that supports a simpler method?
2. Is the apparent duplicate shapefile export truly redundant, or does it preserve fields missing from the GeoJSON?
3. How much signal-relative flow orientation can be inferred empirically from crash travel direction and carriageway continuity without Oracle?
4. Which current outputs are actually consumed by analysts, versus merely produced because the old ladder exists?
5. Are `artifacts/staging/` and `artifacts/normalized/` cheap enough to regenerate that they should become ignored work products?
6. Which pieces of `study_slice.py` are truly core, and which are migration carryover?
7. Is any part of the Oracle matching family materially better than a simpler divided-road-only method?
8. Which parity outputs are still genuinely useful once active and legacy are separated?
9. Should the active raw-data contract for the current bounded scope start with all six baseline layers, or with a smaller initial subset?
10. Which exact sample corridors should be used to define “truthful enough” validation for the divided-road scope?

---

## First-Pass Filesystem Move Plan

### Move to legacy/arcpy/

- `firststep/`
- `secondstep/`
- `thirdstep/`
- `run_all.py`
- `clearinggdb.py`

### Move to legacy/docs/

- already-legacy docs
- `docs/stage1_portability.md`
- `docs/stage1b_study_slice.md`
- all Stage 2 Oracle-safe branch docs
- other migration-era or branch-specific docs no longer governing active work

### Move to legacy/reference/

- `oracle_exports/`
- `layer_summaries/`

### Move to legacy/outputs/<dated-or-named-run>/

- `artifacts/output/stage1b_study_slice/`
- `artifacts/output/stage1_bridge_boundary/`
- most step-specific parity or output residue tied to the old ladder

### Remove or ignore local clutter

- `.idea/`
- `.tmp/`
- `.npm-*`
- `.pip-cache/`
- `pip_cache/`
- `temp/`
- `tmp/`
- `artifacts/pycompile*`
- `artifacts/Users/`
- `intersection_crash_analysis.egg-info/`
- `structure.txt`

---

## Top 10 Highest-Priority Components To Inspect Immediately

1. `stage1_portable/study_slice.py`
2. `config/stage1_portable.toml`
3. `stage1_portable/bridge_key_audit.py`
4. `stage1_portable/bridge_key_boundary.py`
5. `Intersection Crash Analysis Layers/VDOT_Bidirectional_Traffic_Volume_2024.geojson`
6. `stage1_portable/stage1b_study_roads_link_restoration_normalized_route_key.py`
7. `stage1_portable/stage1b_segment_link_inheritance.py`
8. any study-scoped Oracle lookup module still active in `stage1_portable/`
9. `artifacts/output/stage1b_study_slice/`
10. `artifacts/output/stage1_bridge_boundary/`

---

## End State for First Pass

The first redesign pass is complete when:

- `legacy/` exists and contains clearly retired ArcPy-era and packaging-era material
- active docs contain only the current methodology, the current AGENTS contract, and one active workflow note
- active source tree is visibly smaller
- generated outputs are no longer presented as active repo structure
- `stage1_portable` has been conceptually decomposed into active core versus legacy branch material
- Codex can name one active bounded workflow for signal-centered near-signal evidence work, with flow orientation treated as a supporting inference on divided roads
- a human can open the repo and understand what is current in one screen

---

## Final Target Feeling

After redesign, the active repository should feel:

- small
- opinionated
- easy to explain
- easy to inspect
- easy to validate
- clearly separated from legacy history
- visibly aligned with the bounded signal-centered downstream problem instead of inherited implementation momentum
