# Stage 1 Portable Staging and Normalization Contract

This document defines the portable input boundary for Stage 1A. It is the contract that later open-source vertical-slice work must consume.

## Purpose

Stage 1A creates two distinct portable layers:

- `artifacts/staging/`
  Raw/canonical preservation layer. This keeps source meaning intact while removing ArcGIS Pro as a runtime dependency.
- `artifacts/normalized/`
  Analysis-ready layer. This is the earliest portable boundary for downstream open-source processing.

Do not overwrite or reinterpret the preservation layer when building normalized analysis-ready inputs.

## Commands

```powershell
.\scripts\bootstrap.cmd
.\scripts\bootstrap.cmd -CreateVenv -UseExternalVenv
.\scripts\bootstrap.cmd -CreateVenv -UseExternalVenv -InstallDeps
<bootstrap-reported-python> -m src stage-inputs
<bootstrap-reported-python> -m src normalize-stage
```

Use the interpreter path reported by bootstrap instead of assuming `.\.venv\Scripts\python.exe`.
`scripts/bootstrap.ps1` is the implementation, but `.\scripts\bootstrap.cmd` is the preferred entrypoint because direct PowerShell-script execution may be blocked by execution policy.
The practical base Python for this repo is Python 3.11, and the active interpreter may be external to the repo.
TEMP/TMP and pip cache may also be externalized outside the repo.
If external venv mode is already in use, do not create a conflicting repo-local `.venv` unless explicitly instructed.

## Preservation Layer Contract

- Output format: one GeoParquet file per logical input in `artifacts/staging/`
- Active staged logical inputs for the current standard package CLI slice: `roads`, `signals`, `crashes`
- `signals` is the portable canonical equivalent of legacy `Master_Signal_Layer`
- `signals` is assembled from configured raw signal sources and retains `Stage1_SourceGDB` and `Stage1_SourceLayer`
- Other layers preserve their raw source schema plus Stage 1 provenance fields
- `aadt` remains available as an optional raw diagnostic source for the traffic-volume inspection commands, but it is not part of the required minimal standard package CLI slice
- `access` and `speed` staged files may exist in this working tree from an earlier wider staging run; their presence is residual evidence, not proof that the current standard CLI slice requires them

## Normalized Layer Contract

- Output format: one GeoParquet file per logical input in `artifacts/normalized/`
- Working CRS: `EPSG:3968`
- Null geometries are dropped during normalization and counted in the manifest
- Only `crashes` is year-filtered, using `CRASH_YEAR` in the inclusive range `2022-2024`
- `roads` and `signals` are not year-filtered in the active Stage 1A slice
- `aadt`, traffic-volume exports, access, and speed are not part of the required minimal standard package CLI slice
- the restored upstream/downstream prototype uses posted-speed context directly for speed-informed approach lengths; that direct-entry prototype behavior is documented in `docs/workflow/active_workflow.md`, not as a requirement of this Stage 1A standard slice

## Supplemental Input Direction

The historical six-layer portability set remains useful reference material, but the current required minimal active slice is narrower:

- required: `roads`, `signals`, `crashes`
- optional diagnostic: `aadt`
- not part of the required minimal standard package CLI slice: access, speed, traffic-volume exports, and Oracle-supporting bridge layers

Supplemental layers may still be inspected later, but they should be treated as comparison or redesign candidates until the active workflow explicitly adopts them.

The current context-enrichment plan in `docs/workflow/enrichment_plan.md` proposes reintroducing AADT and access as validated enrichment inputs after the upstream/downstream output contract, not by silently broadening Stage 1A.

## Parity Contract

Parity is checked across three boundaries:

1. raw source vs staged raw/canonical
2. staged raw/canonical vs normalized
3. normalized vs legacy ArcPy outputs, where real legacy outputs are accessible

Required metrics:

- row counts
- null geometry counts
- CRS
- schema and field-presence deltas
- key identifier presence/completeness
- geometry type mix and bounds
- manifest/output consistency

If supplemental traffic-volume, bridge-key, or Oracle-supporting inputs are introduced later, the staging contract should record whether they are already authoritative inputs, transition artifacts, or pending comparison candidates. Do not imply that a bridge-key path has been implemented merely because the staging contract allows for it.

If legacy ArcPy staged or working outputs are not accessible, the parity report must say so explicitly rather than infer parity.
