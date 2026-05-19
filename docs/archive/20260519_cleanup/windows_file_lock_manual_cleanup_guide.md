# Windows File-Lock Manual Cleanup Guide

## Purpose

This guide explains what a human operator should do when workflow outputs cannot replace files under `current/` because Windows is holding one or more file handles open.

This is a manual recovery guide. It is intentionally conservative:
- do not force-delete files just because they look old
- do not kill processes unless you have confirmed they are safe to close
- do not treat `current/` as authoritative if a newer successful run already landed in `history/`

## When To Use This Guide

Use this guide when one or more of the following happens:
- a workflow run succeeds, but fresh outputs appear under `history/` instead of replacing files in `current/`
- files under `current/` keep old timestamps after a rerun
- Windows reports that a file is in use
- `current/` and `history/` disagree about which run is latest
- you suspect Excel, GIS software, Explorer preview, or an old Python process is holding output files open

## Main Failure Modes

The relevant Windows failure modes in this workspace are:

1. A `current/` output file is open in another application.
   Common examples: Excel, ArcGIS Pro, QGIS, VS Code preview, Notepad++, Power BI, a CSV viewer, or a GIS table preview.

2. Explorer is holding a handle.
   Preview pane, details pane, thumbnail generation, or a folder window parked on an output directory can be enough.

3. A prior Python run is still alive.
   A previous `python.exe` process may still hold a file handle even after the main workflow appears finished.

4. GIS or analysis software has cached a layer or table.
   GeoPackage, GeoJSON, shapefile sidecars, CSVs, and Parquet-backed previews can remain open after a map or table view was left open.

5. Sync, indexing, or antivirus activity briefly blocks replacement.
   OneDrive is one example, but the broader issue is any sync/indexing/AV process touching newly written files at the wrong time.

6. `current/` is stale while `history/` contains the real latest successful run.
   This is the most important output-hygiene risk. A new run may finish correctly, but only the `history/` copy reflects it.

7. `history/` has multiple recent runs and it is unclear which one is authoritative.
   This can happen after several reruns while `current/` stayed locked.

## Output Layout Reminder

The workflow uses two lanes:

- `current/`
  Intended stable, easy-to-find outputs.

- `history/`
  Timestamped fallback outputs when stable replacement is blocked or when historical retention is desired.

If `current/` did not update but `history/` did, the newest successful `history/` run may be the real authoritative output for that rerun.

## How To Tell Whether `current/` Is Stale

Check all three of these before trusting `current/`:

1. Compare timestamps.
   If the files in `work/output/.../tables/current/` or `runs/current/` did not change, but matching files in `history/` have newer timestamps, `current/` is probably stale.

2. Check the latest run summary.
   Look in `work/output/.../runs/history/` for the newest `*_run_summary_YYYYMMDD_HHMMSS.json`. If that file is newer than `runs/current/...run_summary.json`, the latest successful run may only exist in `history/`.

3. Check whether the expected set of outputs was written together.
   Treat a history run as authoritative only if the run summary and its companion outputs appear to come from the same run window and the run completed successfully.

## How To Identify The Newest Authoritative History Run

Use this order of operations:

1. Start with the newest run-summary JSON in `runs/history/`.
2. Open it and confirm the run completed successfully.
3. Check that the expected tables or other outputs from that run have matching or near-matching timestamps.
4. Prefer a complete set from one run over a mixture of files from different runs.

Do not pick files from multiple history runs unless you have explicitly verified that mixing them is safe for that workflow.

## Common Applications To Close Before Rerunning

Close these first if they are open on repo outputs:

- Excel
- ArcGIS Pro
- QGIS
- VS Code tabs or preview panes showing output files
- Notepad++ or other editors opened directly on output CSV/JSON files
- Power BI or similar data viewers
- Windows Explorer windows pointed at `work/output/.../current/` or `history/`
- any custom GIS/table viewer

Also verify that no old `python.exe` process from this repo is still running.

## How To Check For Open Handles

Manual Windows-oriented options:

1. Task Manager
   Check for leftover `python.exe`, GIS applications, spreadsheet applications, or viewers that should already be closed.

2. Resource Monitor
   Open Resource Monitor, use the CPU tab search for part of the filename or folder name, and inspect Associated Handles.

3. Sysinternals Process Explorer or `handle.exe`
   Use these only if you are comfortable reviewing open handles before closing anything.

Do not terminate a process just because it appears in a list. First confirm it is not doing useful work and is actually holding the relevant output file.

## Safe Manual Cleanup Procedure

### Pre-run check

Before rerunning a workflow:

1. Close likely handle-holding applications listed above.
2. Close Explorer windows parked on the relevant output folders.
3. Confirm no old repo-related `python.exe` process is still active.
4. Verify that the latest good outputs are preserved somewhere before touching anything.
   If `history/` has the only fresh good copy, leave it alone until you have verified the rerun or manual promotion plan.

### If a rerun wrote to `history/` instead of `current/`

Use this sequence:

1. Identify the newest successful history run.
2. Confirm `current/` is stale by comparing timestamps and run summaries.
3. Close any application that could still be holding the stale `current/` file open.
4. Only after that, decide whether manual promotion from `history/` to `current/` is safe.

### When It Is Safe To Copy A History Artifact Into `current/`

Manual copy or replace is reasonable when all of the following are true:

- the history artifact comes from the newest successful run
- you have confirmed the corresponding `current/` artifact is stale
- the target file is no longer open in another application
- you are copying a complete, known-good artifact rather than guessing
- you are not deleting the history copy first

If the workflow output is logically a coordinated set, prefer promoting the whole verified set from one run rather than cherry-picking files.

### When It Is Not Safe To Copy A History Artifact Into `current/`

Do not manually promote if any of the following is true:

- you are unsure which history run is the latest successful run
- the run appears partial or failed
- the target `current/` file is still in use
- the files you want to copy come from different runs
- `current/` may contain edits or outputs from a different workflow stage that you have not checked
- the history copy is the only good copy and you were planning to move instead of copy

When in doubt, preserve both copies and review before replacing anything.

### When Manual Deletion Is Safe

Manual deletion should be rare and deliberate.

Usually safe:
- deleting an obviously stale `current/` file only after you have verified a newer good replacement exists elsewhere
- deleting a temporary duplicate you created during manual promotion after confirming the final file is readable

Usually not safe:
- bulk-deleting old `history/` directories without checking whether they contain the only good run
- deleting a locked file just to make a rerun work
- deleting entire output trees because timestamps look inconsistent

## Practical Manual Recovery Pattern

When a run succeeded but `current/` stayed stale:

1. Find the newest successful run summary in `runs/history/`.
2. Confirm the matching history outputs are complete and newer than `current/`.
3. Close Excel, GIS software, Explorer previews, editors, and old Python processes.
4. Recheck whether the stale `current/` file is still locked.
5. If the file is no longer locked, copy the verified history artifact into `current/`.
6. Keep the original history copy intact.
7. Reopen the promoted `current/` artifact and verify that it matches the intended latest run.

## Post-run Check

After each rerun:

1. Check whether `runs/current/` updated.
2. Check whether `tables/current/` or other expected `current/` outputs updated.
3. If not, inspect `history/` immediately rather than assuming the run failed.
4. Record which run is authoritative before doing any manual replacement.

## What Not To Do

Avoid these shortcuts:

- do not assume `current/` is always the latest output
- do not delete `history/` just to reduce clutter
- do not move the only good history copy
- do not kill Python, GIS, sync, or indexing processes without checking what they are doing
- do not mix files from multiple runs unless you have verified compatibility

## Small Future Improvements Worth Implementing Later

These are reasonable follow-up improvements, but they should be implemented deliberately rather than during manual cleanup:

1. Add a clear latest-success marker.
   Example: a small JSON or text pointer under each output root identifying the latest authoritative successful run.

2. Add a manual `promote-history-to-current` helper.
   This should be an explicit human-invoked script or checklist, not an automatic aggressive cleanup step.

3. Add clearer run metadata links from output READMEs.
   The README should tell an operator exactly where to look first when `current/` is stale.

4. Strengthen temp-write then promote conventions.
   Keep writes atomic where possible and make fallback behavior obvious in run metadata.

5. Add an operator checklist to active workflow docs.
   Include pre-run closeouts, post-run verification, and manual promotion rules.

## Minimum Operator Checklist

Before rerun:
- close Excel, GIS, editors, preview panes, and Explorer windows on output folders
- verify no old repo-related Python process is still running
- preserve the latest good outputs before changing anything

After rerun:
- compare `current/` and `history/` timestamps
- inspect the newest run summary
- treat `history/` as authoritative if it contains the only fresh successful run
- manually promote only verified outputs and keep the history copy
