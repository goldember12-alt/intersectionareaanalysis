# Recovery Audit 2026-04-16

## Executive summary

Status: **partially broken and logically inconsistent**.

The checked-out branch, `backup/pre-rewrite-main` at `c209803`, contains the redesign work that does not exist on `origin/main`, but the repository is still mixed-state:

- active docs describe a narrowed signal-centered workflow
- active code still contains hidden Stage 1B and Oracle-prep ladder logic
- tracked artifacts still reflect a wider earlier pipeline
- ignored local-only material hides important archive docs and outputs
- the active `work/` output tree is missing key operational products and newer grouped "current" packages referenced by surviving run summaries

Current working-tree note:

- this report was first written during the initial audit and some small repairs were made afterward in the working tree
- `.gitignore` now keeps `docs/` unmasked
- `check-parity` is now exposed through `src/active/__main__.py`
- `README.md`, `docs/README.md`, `docs/methodology/overview_methodology.md`, and this audit file currently exist in the working tree, but not all of them are part of committed `c209803`

Top 5 confirmed problems:

1. The redesign lives only on local branch `backup/pre-rewrite-main`; `origin/main` does not have it, and `main` has only one divergent cleanup commit.
2. `.gitignore` masked important local-only content, including `legacy/docs/`, because the broad `docs/` rule matched any directory named `docs`.
3. `work/output/stage1b_study_slice/` and `work/parity/` are absent even though current config and active workflow docs still require them.
4. Active docs and active code disagree: committed `c209803` left `AGENTS.md` pointing to root `overview_methodology.md`, `src/active/study_slice.py` still contains extensive Stage 1B and Oracle-prep logic, and the broader docs set exists mostly as working-tree material rather than committed history.
5. `artifacts/staging/` and `artifacts/normalized/` still represent an older wider pipeline, and tracked runtime spill files remain under `artifacts/staging/`.

## Confirmed findings

### Git and branch state

- `backup/pre-rewrite-main` exists and is the current branch.
- `backup/pre-rewrite-main` points to `c209803a79a94d2fad0456e199e3ac959c21473e`.
- `main` points to `c8f61c436471c0a24008256441dfde718f774733`.
- `origin/main` points to `56850d80806952972defc497a3801c6de1b66a2c`.
- Divergence counts:
  - `origin/main...backup/pre-rewrite-main` = `0 10`
  - `origin/main...main` = `0 1`
  - `main...backup/pre-rewrite-main` = `1 10`
- All three branches share merge-base `56850d80806952972defc497a3801c6de1b66a2c`.
- Recent reflog shows a reset to `origin/main` on 2026-04-16, a cherry-pick onto `main`, then checkout back to `backup/pre-rewrite-main`.

### Ignore-rule masking

- `.gitignore:91` contained `docs/`, which masked:
  - root `docs/` for new untracked files
  - `legacy/docs/` via name match
- `.gitignore:92` masks `work/`.
- `.gitignore:98` masks `legacy/outputs/`.
- `.gitignore:9` masks `__pycache__/`.
- `git check-ignore -v` confirmed:
  - `legacy/docs/` was ignored by `.gitignore:91:docs/`
  - `legacy/outputs/portability_branch_2026-04/` is ignored by `.gitignore:98:legacy/outputs/`
  - `work/` is ignored by `.gitignore:92:work/`

### Current repo structure

Top level currently present:

- `AGENTS.md`
- `artifacts/`
- `config/`
- `docs/`
- `Intersection Crash Analysis Layers/`
- `legacy/`
- `scripts/`
- `src/`
- `work/` (local, ignored)
- `.gitignore`
- `pyproject.toml`

Working-tree additions present now but not in committed `c209803`:

- root `README.md`
- `docs/README.md`
- `docs/methodology/overview_methodology.md`
- `docs/recovery_audit_20260416.md`

Not present in the current working tree:

- root `overview_methodology.md`
- `env_scripts/`

### Missing operational outputs

Confirmed absent:

- `work/output/stage1b_study_slice/`
- `work/parity/`
- `work/output/directionality_experiment/tables/current/`
- `work/output/directionality_experiment/review/current/`
- `work/output/directionality_experiment/review/geojson/current/`
- `work/output/directionality_experiment/runs/current/`
- `work/output/upstream_downstream_prototype/tables/current/`
- `work/output/upstream_downstream_prototype/review/current/`
- `work/output/upstream_downstream_prototype/review/geojson/current/`
- `work/output/upstream_downstream_prototype/runs/current/`

Docs/config still require them:

- `docs/workflow/active_workflow.md` requires Stage 1B study-slice outputs and parity JSON.
- `docs/workflow/active_workflow.md` says directionality outputs use grouped `tables/current`, `review/current`, `review/geojson/current`, and `runs/current`.
- `docs/workflow/active_workflow.md` says prototype outputs use grouped `tables/current`, `review/current`, `review/geojson/current`, and `runs/current`.
- `config/stage1_portable.toml:6-7` still sets `output_dir = "work/output"` and `parity_dir = "work/parity"`.

### Active docs vs active code mismatches

- committed `c209803` had `AGENTS.md:414` and `AGENTS.md:452` pointing to root `overview_methodology.md`, while the working-tree methodology file lives under `docs/methodology/overview_methodology.md`
- `src/active/__main__.py` contains `run_check_parity()` at line `483`; the current working tree now exposes it through `check-parity`
- `src/active/study_slice.py` is not actually slimmed down. It still contains:
  - `run_stage1b_study_slice()`
  - `run_stage1b_signal_nearest_road()`
  - `run_stage1b_signal_speed_context()`
  - `run_stage1b_signal_functional_distance()`
  - `run_stage1b_signal_buffers()`
  - `run_stage1b_signal_donut()`
  - `run_stage1b_signal_multizone()`
  - `run_stage1b_road_zone_intersection()`
  - `run_stage1b_road_zone_cleanup()`
  - `run_stage1b_road_claim_ownership()`
  - `run_stage1b_segment_raw()`
  - `run_stage1b_segment_support()`
  - `run_stage1b_segment_identity_qc_support()`
  - `run_stage1b_segment_canonical_road_identity()`
  - `run_stage1b_segment_link_identity_support()`
  - `run_stage1b_segment_directionality_support()`
  - `run_stage1b_segment_oracle_direction_prep()`
- Oracle-prep logic remains active in `src/active/study_slice.py`, including:
  - `ORACLE_EXPORT_DIRNAME`
  - `ORACLE_BROAD_LOOKUP_FILENAME`
  - `enrich_segment_oracle_direction_prep_fields()`
  - `OracleDirection_DependencyStatus = "oracle_required_for_trustworthy_downstream_directionality"`

### Orphaned or mislocated modules/files

- `src/active/high_confidence_upstream_downstream_analysis.py` is not referenced by CLI or active docs.
- It requires grouped prototype outputs under:
  - `work/output/upstream_downstream_prototype/review/geojson/current/`
  - `work/output/upstream_downstream_prototype/tables/current/`
  - `work/output/upstream_downstream_prototype/review/current/`
  - `work/output/upstream_downstream_prototype/runs/current/`
- Those required inputs are currently absent.
- Conclusion: it is effectively orphaned in the current repo state, but there is not yet enough evidence to move or delete it safely.

### Stale tracked artifacts

- `config/stage1_portable.toml` currently defines `roads`, `signals`, `crashes`, and optional `aadt`.
- `artifacts/staging/stage1_input_manifest.json` still includes `access` and `speed`.
- `artifacts/normalized/stage1_normalized_manifest.json` still includes `access` and `speed`.
- `artifacts/staging/` still tracks runtime spill-like files:
  - `roads.gpkg` length `0`
  - `roads.gpkg-journal` length `512`
  - `roads_temp.fgb`
- `stage1_input_manifest.json` and `stage1_normalized_manifest.json` therefore do not reflect the narrow current contract cleanly.

### Legacy/reference placement issues

- `Intersection Crash Analysis Layers/layer_summaries/README.md` says the active reference copy was preserved under `legacy/reference/layer_summaries/` and this in-place copy is residual only.
- `legacy/reference/layer_summaries/` exists.
- This is a confirmed duplicate reference area, with the raw-data-side copy explicitly marked non-active.

## Unconfirmed but plausible findings

- `legacy/docs/` likely contains curated archive material worth versioning, but that should be decided file-by-file rather than by blindly unignoring the whole tree.
- `legacy/outputs/portability_branch_2026-04/` likely contains valuable reference outputs, but it is not yet clear whether full binaries belong in git or whether only a manifest plus README should be tracked.
- The missing grouped `current` trees under `work/output/directionality_experiment/` and `work/output/upstream_downstream_prototype/` may have existed briefly and then been lost during OneDrive conflicts or folder cleanup. The surviving `README.md` and timestamped run summaries strongly suggest they were intended to exist, but the repo does not prove they were ever fully materialized on disk in this workspace.
- `env_scripts/` may have been intentionally absent rather than deleted. No repo contract currently depends on it.

## Git state and branch divergence

### Branch answers

- `backup/pre-rewrite-main` exists: **yes**
- current commit: **`c209803a79a94d2fad0456e199e3ac959c21473e`**
- relative to `main`: `backup/pre-rewrite-main` has 10 unique commits; `main` has 1 unique commit
- relative to `origin/main`: `backup/pre-rewrite-main` has 10 unique commits; `origin/main` has 0 unique commits

### Structural commits of interest

- `b3c3313` - align entrypoint and bootstrap scripts with repo layout
- `4159e6d` - delete tracked `artifacts/output/*` and `artifacts/parity/*` stage outputs and parity artifacts
- `2fe36ee` - move retired workflow code and references into `legacy/`
- `610be7f` - add reduced active workflow runtime and config
- `c209803` - add redesign contract and active workflow docs
- `c8f61c4` on `main` is a separate cleanup commit not present on `backup/pre-rewrite-main`

### Immediate safety recommendation

Before further cleanup, create a safety ref at `c209803`:

```powershell
git tag safety/pre-recovery-audit-20260416-c209803 c209803
git branch safety/pre-recovery-audit-20260416 c209803
```

Creating either one is sufficient; creating both is safer if more history surgery is likely.

## Ignore-rule masking problems

| Rule | Effect | Confirmed masked path(s) | Assessment |
|---|---|---|---|
| `.gitignore:91 docs/` | masked any directory named `docs` | `legacy/docs/`, new files under root `docs/` | overbroad and incorrect for current repo |
| `.gitignore:92 work/` | masks runtime/output tree | `work/` | expected for generated outputs, but hides operational gaps |
| `.gitignore:98 legacy/outputs/` | masks archive outputs | `legacy/outputs/portability_branch_2026-04/` | may be acceptable only if archive stays intentionally external to git |
| `.gitignore:9 __pycache__/` | masks bytecode spill | `src/__pycache__/` | appropriate |

Rules that should likely be narrowed:

- remove or replace the broad `docs/` rule
- decide intentionally whether `legacy/outputs/` should stay ignored wholesale or be replaced by a narrower archive policy

## Missing operational outputs

Highest-priority missing files inferred from current docs/config:

- `work/output/stage1b_study_slice/Study_Roads_Divided.parquet`
- `work/output/stage1b_study_slice/Study_Signals.parquet`
- `work/output/stage1b_study_slice/Study_Signals_NearestRoad.parquet`
- `work/parity/stage1b_study_slice_qc.json`
- `work/parity/stage1b_signal_nearest_road_qc.json`

Grouped packages referenced by surviving run summaries but absent on disk:

- `work/output/directionality_experiment/run_summary_20260414_155808.json` references grouped `tables/current`, `review/current`, `review/geojson/current`, and `runs/current` paths that do not exist.
- `work/output/upstream_downstream_prototype/run_summary_20260414_181217.json` references grouped `tables/current`, `review/current`, `review/geojson/current`, `runs/current`, and `README.md`; the grouped folders do not exist, but the root `README.md` does exist.

Recovery classification:

- Stage 1B study-slice outputs: likely regenerable from current raw data, `artifacts/staging/`, `artifacts/normalized/`, and active code
- Stage 1B parity JSON: likely regenerable after Stage 1B rebuild
- grouped directionality/prototype outputs: likely regenerable, but any manually curated review notes or ad hoc grouped packages may require external recovery

## Active-docs vs active-code mismatches

### Broken contract

- committed `c209803` did point to a non-existent root `overview_methodology.md`: **yes**
- `docs/methodology/overview_methodology.md` is the live file: **yes**
- cleanest repair in the current working tree: point `AGENTS.md` directly to `docs/methodology/overview_methodology.md`

### CLI exposure

- `run_check_parity()` exists: **yes**
- it was exposed through CLI before repair: **no**
- current working-tree status: **now exposed through `check-parity`**

### Study-slice reality check

- `src/active/study_slice.py` is not slimmed to just the reduced entry slice
- hidden ladder logic is proven by the retained `run_stage1b_*` family and `run_stage1b_segment_oracle_direction_prep()`
- Oracle dependence is still spelled out directly in `enrich_segment_oracle_direction_prep_fields()`

## Orphaned or mislocated modules/files

### `src/active/high_confidence_upstream_downstream_analysis.py`

- orphaned: **effectively yes**
- called by anything current: **no direct references found**
- required inputs present: **no**
- recommended action now: **leave untouched, document as dependent on regenerated grouped prototype outputs**

### `Intersection Crash Analysis Layers/layer_summaries/`

- status: residual duplicate reference copy
- recommended action now: leave untouched; do not treat as active input

## Stale tracked artifact assessment

Authoritative enough to keep for now:

- `artifacts/staging/stage1_input_manifest.json`
- `artifacts/normalized/stage1_normalized_manifest.json`
- core staged/normalized `roads`, `signals`, `crashes`, `aadt` parquet files

Suspicious or disposable:

- `artifacts/staging/roads.gpkg`
- `artifacts/staging/roads.gpkg-journal`
- `artifacts/staging/roads_temp.fgb`
- tracked `access` and `speed` staged/normalized artifacts if the narrowed workflow no longer uses them

Important nuance:

- some tracked artifacts are still useful as transitional rebuild inputs even if they no longer reflect the ideal final contract
- this is a cleanup problem, not evidence that they should be deleted immediately

## Recovery classification table

| path/item | current status | evidence | severity | likely recovery path | should be tracked in git? |
|---|---|---|---|---|---|
| `backup/pre-rewrite-main` | local-only redesign branch | branch list and divergence counts | critical | preserve immediately with safety tag/branch | yes |
| `legacy/docs/` | present locally, ignored | `git check-ignore -v legacy/docs` | critical | decide curated files, then track intentionally | depends |
| `legacy/outputs/portability_branch_2026-04/` | present locally, ignored | ignore rule and local directory listing | important | keep external or add manifest/README | depends |
| `work/output/stage1b_study_slice/` | missing | `Test-Path` false; docs require it | critical | regenerate | no |
| `work/parity/` | missing | `Test-Path` false; docs/config require it | critical | regenerate | no |
| `work/output/directionality_experiment/tables/current/` and peers | missing | grouped paths in `run_summary_20260414_155808.json`; `Test-Path` false | important | regenerate or recover from OneDrive/Recycle if exact review package matters | no |
| `work/output/upstream_downstream_prototype/tables/current/` and peers | missing | grouped paths in `run_summary_20260414_181217.json`; `Test-Path` false | important | regenerate or recover from OneDrive/Recycle if exact review package matters | no |
| `AGENTS.md` overview path | repaired in working tree, broken in committed `c209803` | `AGENTS.md` now points to `docs/methodology/overview_methodology.md`; committed `c209803` pointed to root | important | keep the direct `docs/methodology/overview_methodology.md` reference | yes |
| `src/active/__main__.py` parity surface | repaired in working tree | `run_check_parity()` present and now exposed through `check-parity` | important | keep current CLI exposure | yes |
| `src/active/study_slice.py` | mixed reduced+legacy ladder logic | retained `run_stage1b_*` family and Oracle-prep fields | important | document and later split or retire deliberately | yes |
| `src/active/high_confidence_upstream_downstream_analysis.py` | orphaned by missing inputs | no refs found; inputs absent | low | leave untouched pending regeneration | yes |
| `artifacts/staging/roads.gpkg` | tracked spill-like file | zero-byte file | low | remove in later cleanup after confirming unused | likely no |
| `artifacts/staging/roads.gpkg-journal` | tracked spill-like file | journal file in tracked tree | low | remove in later cleanup after confirming unused | likely no |
| `artifacts/staging/roads_temp.fgb` | likely transient export | filename and artifact placement | low | remove in later cleanup after confirming unused | likely no |
| root `README.md` | present only as working-tree addition | current working tree file exists; not part of committed `c209803` | important | keep and stage when ready | yes |
| `docs/README.md` | present only as working-tree addition | current working tree file exists; older version also exists in history | low | keep and stage when ready | yes |
| root `overview_methodology.md` | absent by choice | `Test-Path` false; current repair should point AGENTS to `docs/methodology/overview_methodology.md` instead | low | do not add unless later contract design changes | no |

## Bounded recovery sequence

1. Preserve the redesign state before further cleanup.
   - tag or branch `c209803`
2. Preserve local-only archive material before changing ignore policy.
   - inventory `legacy/docs/`
   - inventory `legacy/outputs/portability_branch_2026-04/`
3. Repair small contract surfaces in-repo.
   - unmask active docs
   - add root `README.md`
   - add `docs/README.md`
   - point `AGENTS.md` to `docs/methodology/overview_methodology.md`
   - expose `check-parity`
4. Recover or regenerate the missing operational base slice.
   - `build-study-slice`
   - `enrich-study-signals-nearest-road`
   - `check-parity`
5. Recover grouped experiment/prototype outputs.
   - first search OneDrive/Recycle for the exact grouped-current packages named in the April 14, 2026 run summaries
   - if not found, regenerate them from active code
6. Only after outputs exist again, reassess active-vs-legacy placement.
   - especially `high_confidence_upstream_downstream_analysis.py`
   - and stale tracked artifacts under `artifacts/`

## Do not change yet

- do not delete `src/active/high_confidence_upstream_downstream_analysis.py`
- do not move `src/active/study_slice.py` pieces to legacy without a deliberate split plan
- do not delete `legacy/outputs/portability_branch_2026-04/` just because it is ignored
- do not delete `artifacts/staging/access.parquet` or `artifacts/staging/speed.parquet` until the narrowed workflow is confirmed to have no remaining dependency
- do not fabricate missing `work/` outputs

## Safe immediate fixes

Applied in this session because they repair broken contracts or visibility without claiming missing outputs exist:

- removed the overbroad `.gitignore` rule that masked `docs/` and `legacy/docs/`
- added a minimal root `README.md`
- added a minimal `docs/README.md`
- aligned `AGENTS.md` to `docs/methodology/overview_methodology.md` instead of inventing a root shim
- exposed `check-parity` through the active CLI

## Needs regeneration, not editing

- `work/output/stage1b_study_slice/`
- `work/parity/`
- grouped `current` trees under `work/output/directionality_experiment/`
- grouped `current` trees under `work/output/upstream_downstream_prototype/`
- any downstream analysis output that depends on those grouped prototype inputs

## Likely requires Recycle Bin / OneDrive / git-history recovery

- exact grouped review packages referenced by:
  - `work/output/directionality_experiment/run_summary_20260414_155808.json`
  - `work/output/upstream_downstream_prototype/run_summary_20260414_181217.json`
- any manually curated review memo or GeoJSON package that existed only under `work/`
- older tracked Stage 1B and parity outputs deleted by commit `4159e6d`

Git-history recovery anchors:

- `4159e6d` is the commit that deleted tracked Stage 1B and parity outputs
- `db43f99` still contains the older `docs/README.md`
