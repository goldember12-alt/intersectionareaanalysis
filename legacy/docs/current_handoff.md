# Current Handoff

Current package path note:
- the active package folder is now `src/`
- historical references below to `stage1_portable/` or `-m stage1_portable ...` refer to the same package before the folder rename

## 1. Current task

- Implement the first bounded divided-road directionality experiment using the recommended first method:
  - crash direction-of-travel
  - single-vehicle subset
  - straight-ahead subset
- Stay inside the reduced active slice:
  - `stage-inputs`
  - `normalize-stage`
  - `build-study-slice`
  - `enrich-study-signals-nearest-road`
- Use three bounded sample corridor buckets only:
  - one Norfolk city-signal corridor
  - one Hampton city-signal corridor
  - one HMMS/VDOT corridor outside city-only inventories
- When interrupted, work was at the point of turning the inspected data into a small standalone experiment module and finalizing the assignment threshold for `assigned` vs `unresolved`.

## 2. Current status

### Completed

- Read and treated as controlling:
  - `docs/overview_methodology.md`
  - `AGENTS.md`
  - `docs/repo_redesign_plan.md`
  - `docs/active_workflow.md`
  - `docs/method_comparison.md`
- Confirmed the required project interpreter and used it for all substantive work:
  - `C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe`
- Rebuilt enough of the reduced slice to proceed and verified active outputs exist:
  - `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
  - `work/output/stage1b_study_slice/Study_Signals.parquet`
  - `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`
- Confirmed `CrashData_Details` is the required crash evidence source for this experiment because normalized `crashes.parquet` does not carry direction-of-travel or maneuver fields.
- Confirmed the needed detail fields exist in raw `crashdata.gdb`:
  - `DOCUMENT_NBR`
  - `DIRECTION_OF_TRAVEL_CD`
  - `VEHICLE_MANEUVER_TYPE_CD`
- Selected the three first corridor buckets from actual rebuilt reduced-slice data:
  - Norfolk: `R-VA   SR00337WB`
  - Hampton: `S-VA114PR BIG BETHEL RD`
  - HMMS: `R-VA029SC00620EB`
- Identified concrete first bounded windows inside those buckets:
  - Norfolk window:
    - route `R-VA   SR00337WB`
    - measure `29.99` to `31.72`
    - signals:
      - `HAMPTON & MAGNOLIA`
      - `BOLLING & HAMPTON`
      - `LARCHMONT ELEM (SB HAMPTON)`
      - `CAMERA-47TH & HAMPTON`
  - Hampton window:
    - route `S-VA114PR BIG BETHEL RD`
    - measure `3.12` to `5.26`
    - signals by Hampton IDs:
      - `24`
      - `25`
      - `167`
      - `168`
      - `185`
  - HMMS window:
    - route `R-VA029SC00620EB`
    - measures spanning `3.15` to `9.16`
    - signals:
      - `Sully Park Drive`
      - `Braddock Road / Walney Road`
      - `Colchester Road`
      - `Clifton Road`
      - `Nb Ramp / Fairfax County Parkway`

### Partially completed

- Crash filter definition was narrowed but not yet frozen in code:
  - single-vehicle via `VEH_COUNT == 1`
  - straight-ahead likely via exact `VEHICLE_MANEUVER_TYPE_CD == '1. Going Straight Ahead'`
  - parse `DIRECTION_OF_TRAVEL_CD` into one of `North`, `South`, `East`, `West`
  - reject `n/a`, blank, or mixed semicolon strings with conflicting directions
- Route-and-measure attachment strategy was chosen but not yet implemented as a module:
  - exact route match on `RTE_NM`
  - crash measure match on `RNS_MP` within study-road `FROM_MEASURE` / `TO_MEASURE`
- Strong-evidence assignment rule was under active consideration:
  - likely conservative rule: minimum qualifying-crash threshold plus directional agreement threshold
  - not yet finalized
- Baseline comparison design was chosen but not yet coded:
  - baseline 1: crash direction-of-travel only
  - baseline 2: roadway-context-only support

### Not started

- No standalone experiment module has been created yet.
- No final experiment outputs have been written yet.
- No final conflict summary, assignment table, or baseline-comparison tables have been produced yet.
- No small doc follow-up was made for this run beyond this handoff file.

## 3. Exact files touched in this interrupted session

### Changed files

- `stage1_portable/__main__.py`
  - small rerun-safety fix already made earlier in this interrupted session:
    - removed explicit manifest `unlink()` calls in `run_stage_inputs()` and `run_normalize_stage()`
    - reason: locked manifest files were causing `PermissionError`
- `docs/current_handoff.md`
  - created now to capture exact restart state

### Inspected files that matter

- `docs/overview_methodology.md`
- `AGENTS.md`
- `docs/repo_redesign_plan.md`
- `docs/active_workflow.md`
- `docs/method_comparison.md`
- `stage1_portable/__main__.py`
- `stage1_portable/config.py`
- `config/stage1_portable.toml`
- `stage1_portable/study_slice.py`
- `artifacts/normalized/crashes.parquet`
- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`
- raw crash detail layer:
  - `Intersection Crash Analysis Layers\crashdata.gdb` layer `CrashData_Details`

## 4. Commands run

### Project interpreter used

- `C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe`

### Important workflow commands

- Succeeded:
  - `& 'C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe' -m stage1_portable build-study-slice`
  - `& 'C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe' -m stage1_portable enrich-study-signals-nearest-road`
- Failed earlier because of existing-file overwrite / lock behavior:
  - `& 'C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe' -m stage1_portable stage-inputs`
  - `& 'C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe' -m stage1_portable normalize-stage`
- Important nuance:
  - the reduced active outputs needed for the experiment do exist and were usable
  - `stage-inputs` / `normalize-stage` are still not fully rerun-safe because existing parquet overwrite can also hit `PermissionError`

### Important inspection commands

- Output / field inspection:
  - multiple inline commands of the form:
    - `@' ... '@ | & 'C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe' -`
- Key inspections already run:
  - verified columns and sample rows in:
    - `Study_Roads_Divided.parquet`
    - `Study_Signals_NearestRoad.parquet`
    - `artifacts/normalized/crashes.parquet`
  - ranked candidate corridors by signal count from `Study_Signals_NearestRoad`
  - inspected `CrashData_Details` direction and maneuver coding by route
  - scored 3-to-5-signal windows on the three chosen corridors using:
    - all parseable crash direction-of-travel counts
    - filtered single-vehicle straight-ahead counts

### Interrupted

- No long-running coding or experiment-run command was in progress at interruption time.
- The next step had not yet been started; implementation was paused before creating the standalone experiment module.

## 5. Outputs / artifacts produced

### Existing active outputs confirmed usable

- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `work/output/stage1b_study_slice/Study_Signals.parquet`
- `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`
- `work/parity/stage1b_study_slice_qc.json`
- `work/parity/stage1b_signal_nearest_road_qc.json`

### New outputs produced in this interrupted session

- No new directionality experiment output files yet
- No assignment tables yet
- No conflict summary yet
- No baseline-comparison files yet

## 6. Current reasoning state

### Conclusions already reached

- The recommended first method is feasible without reviving Oracle or link-propagation logic.
- The reduced slice is sufficient for corridor selection and nearest-road context.
- `CrashData_Details` must be joined to normalized/basic crashes on `DOCUMENT_NBR`; normalized crashes alone are insufficient.
- The simplest bounded attachment path is:
  - `RTE_NM` exact match
  - `RNS_MP` within selected study-road measure range
- The three selected corridor buckets are good first bounded samples.
- Empirical crash direction on Norfolk `SR00337WB` appears physically `South`, which is a useful reminder that route suffix support is weaker than observed travel direction.
- Roadway-context-only support will likely be weak:
  - Hampton `BIG BETHEL RD` has no direction suffix in the route name
  - Norfolk route suffix may not reflect the physical cardinal travel direction seen in crash DOT

### Current assumptions

- Use `VEH_COUNT == 1` for single-vehicle filtering.
- Use exact `VEHICLE_MANEUVER_TYPE_CD == '1. Going Straight Ahead'` for the first bounded pass.
- Treat `9. Ran Off Road - Right` and `10. Ran Off Road - Left` as excluded for now.
- Parse direction-of-travel conservatively:
  - keep only one clear cardinal direction
  - reject blank / `n/a`
  - reject conflicting semicolon-coded multi-direction strings

### Uncertainties still open

- Final `assigned` threshold is not yet frozen.
- Best first threshold options still under consideration:
  - minimum qualifying count `>= 3` with dominant share `>= 0.75`
  - or stricter all-agree rule
- Need final decision on whether assignment happens at:
  - selected study-road row level inside each corridor bucket
  - with corridor-level summary on top
- Need actual experiment outputs before judging whether filtered method is clearly stronger than crash-DOT-only.

### What I was about to do next

- Create a small standalone module, likely:
  - `stage1_portable/directionality_experiment.py`
- Have it:
  - load reduced outputs and crash detail data
  - build the three selected corridor buckets
  - apply the crash filter
  - attach crashes by route + measure
  - write:
    - assignment table
    - evidence summary
    - conflict summary
    - lightweight baseline-comparison summary

## 7. Resume instructions

### Smallest good next step

- Implement the standalone bounded experiment module.

### Next commands to run

- First inspect current git/worktree state briefly, then implement:
  - `git status --short`
- After the module is added, run it with the project interpreter:
  - `& 'C:\Users\Jameson.Clements\.venvs\IntersectionCrashAnalysis\Scripts\python.exe' -m stage1_portable.directionality_experiment`

### What should NOT be done next

- Do not return to broad infrastructure cleanup.
- Do not revive Oracle, bridge propagation, Stage 1C, or packaging ladders.
- Do not rerun long statewide logic.
- Do not use bare `py -3.11`.
- Do not broaden beyond the three chosen corridor buckets.
- Do not force labels if the filtered evidence is sparse or conflicting.

## 8. Blockers / risks

- `stage-inputs` and `normalize-stage` still have rerun risk on existing parquet outputs because overwrite behavior can hit `PermissionError`.
- The reduced-slice outputs needed for this experiment are present now, so this is not an immediate blocker unless a full clean rerun is attempted.
- Hampton signal naming is sparse; corridor selection there relies on route and signal IDs more than descriptive intersection names.
- HMMS windows can include ramp-adjacent signals; the chosen first window is still acceptable, but downstream interpretation should stay bounded and cautious.
- The assignment threshold choice will materially affect:
  - assigned rate
  - unresolved rate
  - reported conflict rate

## 9. One-paragraph restart summary

The repo is ready for the first bounded directionality experiment without more infrastructure work: the reduced slice outputs exist in `work/output/stage1b_study_slice/`, the required crash evidence is confirmed to live in raw `CrashData_Details` inside `crashdata.gdb`, and the three first corridor buckets have already been selected from actual data: Norfolk `R-VA   SR00337WB` at measures `29.99-31.72`, Hampton `S-VA114PR BIG BETHEL RD` at `3.12-5.26`, and HMMS `R-VA029SC00620EB` at `3.15-9.16`. Resume by creating a small standalone module, likely `stage1_portable/directionality_experiment.py`, that joins normalized/basic crashes to `CrashData_Details` on `DOCUMENT_NBR`, filters to `VEH_COUNT == 1` plus exact `VEHICLE_MANEUVER_TYPE_CD == '1. Going Straight Ahead'`, parses one clear cardinal `DIRECTION_OF_TRAVEL_CD`, attaches crashes to selected study-road rows by exact `RTE_NM` and `RNS_MP` within road measures, then writes the assignment table, evidence summary, conflict summary, and two lightweight baselines (`crash DOT only` and `roadway-context only`) without touching broader legacy machinery.
