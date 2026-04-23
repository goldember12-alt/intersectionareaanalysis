# GitHub Publishing Guide for the Current Redesign Repo

## Purpose

This guide walks through the safest way to align the GitHub repository with the current redesigned working directory.

It is specific to the current repo state:

- the active redesign work lives on local branch `backup/pre-rewrite-main`
- local `main` has a separate cleanup commit not on that redesign branch
- `origin/main` still reflects the older GitHub repo layout
- the redesign branch history includes very large tracked data blobs that GitHub will reject

Because of that last point, the correct publishing path is **not** "push the redesign branch as-is."

The correct path is:

1. preserve the current working directory safely in local git
2. create a clean publish branch from `origin/main`
3. copy only the publishable repo content into that branch
4. exclude raw inputs and large generated artifacts
5. push the clean publish branch and merge it through a pull request

## Why direct push fails

The current redesign branch contains tracked blobs far above GitHub's 100 MB hard file limit.

Examples already observed in local history:

- `Intersection Crash Analysis Layers/crashdata.gdb/a0000000c.gdbtable` at about `751 MB`
- `Intersection Crash Analysis Layers/crashdata.gdb/a0000000b.gdbtable` at about `700 MB`
- `Intersection Crash Analysis Layers/VDOT_Bidirectional_Traffic_Volume_2024.geojson` at about `636 MB`
- `artifacts/normalized/aadt.parquet` at about `405 MB`

That means a direct push of `backup/pre-rewrite-main` will be rejected by GitHub even if the current working tree itself looks reasonable.

## Publish target

The publish target should be a GitHub branch that contains the redesigned repository structure but **does not** contain:

- `Intersection Crash Analysis Layers/`
- `artifacts/staging/`
- `artifacts/normalized/`
- `work/`
- raw geodatabase contents
- large GeoJSON, shapefile, or parquet outputs

The publish branch should contain the active repo structure only:

- `.gitignore`
- `AGENTS.md`
- `README.md`
- `pyproject.toml`
- `config/`
- `docs/`
- `scripts/`
- `src/`
- selected `legacy/` docs or metadata that you intentionally want versioned

## Recommended publish flow

### Step 1: Freeze the current redesign state locally

Work in the existing repo first and preserve the exact redesign state before doing any publish cleanup.

```powershell
git checkout backup/pre-rewrite-main
git status --short --branch
git add -A
git commit -m "refactor: align redesigned repo layout and docs"
git tag safety/pre-github-alignment-20260423
```

If `git commit` reports nothing to commit, keep the tag step anyway.

Why:

- this preserves the working directory exactly as it exists now
- it gives you a recovery point before any publish-specific filtering or copying

### Step 2: Create a separate clean publish clone

Do **not** perform the publish cleanup in the only working copy.

Create a second clone beside the current repo:

```powershell
cd ..
git clone https://github.com/goldember12-alt/intersectionareaanalysis.git IntersectionCrashAnalysis_publish
cd IntersectionCrashAnalysis_publish
git checkout -b publish/redesign origin/main
```

Why:

- the publish clone starts from the current GitHub branch tip
- it keeps the messy large-file history out of the branch you plan to push
- it protects the current redesign workspace from accidental deletion or cleanup mistakes

### Step 3: Remove the old GitHub-tracked repo layout

The GitHub repo still has the older top-level structure.
Remove that tracked content from the publish clone before copying in the redesigned layout.

```powershell
git rm -r clearinggdb.py docs firststep layer_summaries oracle_exports run_all.py secondstep structure.txt thirdstep
```

If a path is already absent in the publish clone, remove it from the command and rerun.

### Step 4: Copy only the publishable redesigned repo content

From the clean publish clone, copy files from the current working repo.

Assuming these two folders sit side by side:

- current working repo: `..\IntersectionCrashAnalysis`
- clean publish clone: current directory `.\`

Copy the top-level files:

```powershell
copy "..\IntersectionCrashAnalysis\.gitignore" "."
copy "..\IntersectionCrashAnalysis\AGENTS.md" "."
copy "..\IntersectionCrashAnalysis\README.md" "."
copy "..\IntersectionCrashAnalysis\pyproject.toml" "."
```

Copy the active folders:

```powershell
robocopy "..\IntersectionCrashAnalysis\config" ".\config" /E
robocopy "..\IntersectionCrashAnalysis\docs" ".\docs" /E
robocopy "..\IntersectionCrashAnalysis\scripts" ".\scripts" /E
robocopy "..\IntersectionCrashAnalysis\src" ".\src" /E
```

Create `legacy/` only if you want selected archived docs available in GitHub:

```powershell
New-Item -ItemType Directory -Force legacy | Out-Null
robocopy "..\IntersectionCrashAnalysis\legacy\docs" ".\legacy\docs" /E
if (Test-Path "..\IntersectionCrashAnalysis\legacy\README.md") {
    copy "..\IntersectionCrashAnalysis\legacy\README.md" ".\legacy\README.md"
}
```

Notes:

- `robocopy` uses non-zero success codes, so codes `0` through `7` are still normal
- do not copy `Intersection Crash Analysis Layers`, `artifacts`, or `work`

### Step 5: Verify that raw data and generated outputs did not come across

Run these checks in the publish clone:

```powershell
git status --short
git ls-files | Select-String "Intersection Crash Analysis Layers|artifacts/|work/"
```

The second command should return nothing.

Also check for unexpectedly large tracked files:

```powershell
git ls-files | ForEach-Object {
    if (Test-Path $_) {
        $size = (Get-Item $_).Length
        [PSCustomObject]@{ SizeMB = [math]::Round($size / 1MB, 2); Path = $_ }
    }
} | Sort-Object SizeMB -Descending | Select-Object -First 20
```

If anything large or clearly data-like appears, remove it before continuing.

### Step 6: Review the branch diff before committing

Review what the publish branch will actually change:

```powershell
git diff --stat
git status
```

You want to see:

- the old GitHub repo layout removed
- the redesigned active repo layout added
- no raw data or generated runtime outputs

### Step 7: Commit the clean publish branch

```powershell
git add -A
git commit -m "refactor: publish redesigned workflow, docs, and active source tree"
```

### Step 8: Push the clean publish branch

```powershell
git push -u origin publish/redesign
```

If GitHub rejects the push, stop and inspect whether a large file or blocked path slipped into the branch.

## Pull request step

Open a PR with:

- base branch: `main`
- compare branch: `publish/redesign`

Before merging, review the PR file list carefully.

The PR should contain:

- repo redesign docs
- active source tree
- scripts and config
- selected legacy docs only if intentionally included

The PR should **not** contain:

- raw data directories
- `.gdb` content
- parquet artifacts
- `work/` outputs
- OneDrive spill or runtime junk

## After merge

After the PR merges:

1. update local `main`
2. optionally tag the publish point
3. decide whether the old local redesign branch should stay as a deep archive or be rebased onto the new published `main`

Suggested commands:

```powershell
git checkout main
git pull origin main
git tag publish/redesign-20260423
```

## Optional follow-up cleanup

Once GitHub is aligned with the redesigned repo structure, consider these follow-up tasks:

- tighten `.gitignore` further if any local-only artifacts are still at risk of being staged
- add a short repo policy note stating that raw inputs and generated outputs are intentionally excluded from GitHub
- decide whether `legacy/docs/` should be fully versioned or selectively curated
- decide whether a future large-file strategy such as Git LFS is actually needed

## What not to do

Do not:

- force-push `backup/pre-rewrite-main` to `main`
- try to merge the redesign branch history directly into GitHub without removing large-file history first
- copy `Intersection Crash Analysis Layers/`, `artifacts/`, or `work/` into the publish clone
- treat the current local redesign branch as a safe GitHub publish branch

## Short version

If you need the short operational summary:

1. commit and tag the current redesign workspace locally
2. make a new clean clone from `origin/main`
3. create `publish/redesign`
4. remove the old GitHub repo layout
5. copy in only code, docs, config, scripts, and selected legacy docs
6. verify no raw data or artifacts are tracked
7. commit and push `publish/redesign`
8. merge it to `main` through a PR

That is the safest path that aligns GitHub with the current working directory without pushing the oversized local data history.
